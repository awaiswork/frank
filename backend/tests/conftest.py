"""Test fixtures: an isolated PostgreSQL schema and a TestClient bound to it.

Each test runs inside an outer transaction that is rolled back on teardown
(`join_transaction_mode="create_savepoint"` turns the app's commits into
savepoints), so tests never see each other's data.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, get_db
from app.email import EmailMessage
from app.main import create_app


def _test_db_url() -> str:
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        return override
    base, _, _name = get_settings().database_url.rpartition("/")
    return f"{base}/frank_test"


def _ensure_database(url: str) -> None:
    base, _, dbname = url.rpartition("/")
    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": dbname}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = _test_db_url()
    _ensure_database(url)
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    outer = connection.begin()
    session = Session(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def _ai_off(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Default every test to the shipped state: the billable AI features are off.

    Set explicitly (rather than relying on the default) so a developer's local
    ``.env`` can't quietly change what the suite is testing.
    """
    monkeypatch.setenv("LLM_ENABLED", "false")
    # The suite registers more accounts per minute than the per-IP limit allows,
    # and every test shares one client host. Throttling is exercised separately.
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    # No test may reach a mail provider, whatever is in the developer's .env.
    # The `outbox` fixture covers tests that assert on email, but a test that
    # merely registers a user also triggers a send — and with a real key present
    # that send would go out over the network, to a real inbox, from CI or from
    # anyone who ran the suite. Pinning the provider here is what makes "runs
    # with no provider and no network" true rather than merely usual.
    monkeypatch.setenv("EMAIL_PROVIDER", "console")
    # setenv, not delenv: pydantic-settings also reads backend/.env, so deleting
    # the process variable leaves the file's value in place. Overriding with an
    # empty string is what actually blanks it.
    monkeypatch.setenv("EMAIL_API_KEY", "")
    # Same reasoning for Google: a developer with real credentials configured
    # would otherwise be running a different app from CI, and the tests that
    # assert the routes stay hidden when unconfigured would fail on their
    # machine only. Tests that need Google opt in via the `google` fixture.
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def ai_on(_ai_off: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Switch the AI features on, for tests that mock the model itself.

    Depends on ``_ai_off`` purely for ordering — it must run after the default.
    """
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@dataclass
class SentEmail:
    to: str
    subject: str
    text: str
    html: str

    @property
    def link(self) -> str:
        """The one URL in the body — the thing a person would click."""
        match = re.search(r"https?://\S+", self.text)
        assert match, f"no link in email: {self.subject}"
        return match.group(0).rstrip(".")

    @property
    def token(self) -> str:
        return parse_qs(urlparse(self.link).query)["token"][0]


#: Emails captured during the current test. Module-level so plain helper
#: functions can read it without every call site having to thread a fixture
#: through — cleared before each test by the autouse fixture below.
SENT: list[SentEmail] = []


@pytest.fixture(autouse=True)
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[SentEmail]:
    """Capture email instead of sending it, and hand back what was sent.

    Patches the sender lookup rather than the provider's HTTP call, so nothing in
    the suite can reach the network even if a key leaks into the environment.
    Autouse because *every* test that registers an account now sends a code, not
    just the ones that assert on it.
    """
    SENT.clear()

    class Recorder:
        def send(self, message: EmailMessage) -> None:
            SENT.append(
                SentEmail(
                    to=message.to,
                    subject=message.subject,
                    text=message.text,
                    html=message.html,
                )
            )

    monkeypatch.setattr("app.email.delivery.get_sender", lambda: Recorder())
    return SENT


def create_account(client: TestClient, email: str, password: str = "supersecret") -> str:
    """Register, redeem the emailed code, and return an access token.

    Signing up is two steps now — nothing is issued until the address is proven —
    so every test that just wants an authenticated client goes through here
    rather than repeating the dance.
    """
    res = client.post("/auth/register", json={"email": email, "password": password})
    assert res.status_code == 202, res.text
    match = re.search(r"\b(\d{6})\b", SENT[-1].text)
    assert match, f"no code in the verification email: {SENT[-1].subject}"
    token = client.post("/auth/verify-code", json={"email": email, "code": match.group(1)})
    assert token.status_code == 200, token.text
    return str(token.json()["access_token"])


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
