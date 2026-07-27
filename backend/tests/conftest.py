"""Test fixtures: an isolated PostgreSQL schema and a TestClient bound to it.

Each test runs inside an outer transaction that is rolled back on teardown
(`join_transaction_mode="create_savepoint"` turns the app's commits into
savepoints), so tests never see each other's data.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, get_db
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


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
