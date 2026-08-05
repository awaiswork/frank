"""The production-only settings and guards that the public deploy depends on.

These are the things that fail in production rather than at build time, so they
get tests: the driver rewrite, the cross-site cookie policy, the CORS list, and
the two fail-fast guards.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import DEV_SECRET, Settings, get_settings
from app.db import get_db
from app.limits import limiter
from app.main import create_app

PASSWORD = "supersecret"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # What managed Postgres hands out — SQLAlchemy would pick psycopg2.
        ("postgresql://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        # Already explicit: left alone.
        ("postgresql+psycopg://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        # Neon's real shape: the TLS query string must survive the rewrite, or
        # the connection is refused.
        (
            "postgresql://u:p@ep-cool-name-123.eu-central-1.aws.neon.tech/frankly"
            "?sslmode=require&channel_binding=require",
            "postgresql+psycopg://u:p@ep-cool-name-123.eu-central-1.aws.neon.tech/frankly"
            "?sslmode=require&channel_binding=require",
        ),
    ],
)
def test_database_url_is_pinned_to_psycopg3(given: str, expected: str) -> None:
    assert Settings(database_url=given).database_url == expected


def test_cors_origins_splits_on_commas() -> None:
    settings = Settings(frontend_origin="https://frankly.app, https://www.frankly.app")
    assert settings.cors_origins == ["https://frankly.app", "https://www.frankly.app"]


def test_prod_refuses_the_dev_secret() -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(env="prod", secret_key=DEV_SECRET)


def test_samesite_none_requires_prod() -> None:
    """SameSite=None is only valid on a Secure cookie, and Secure follows ENV."""
    with pytest.raises(ValueError, match="COOKIE_SAMESITE"):
        Settings(env="dev", cookie_samesite="none")

    ok = Settings(env="prod", secret_key="x" * 32, cookie_samesite="none")
    assert ok.cookie_samesite == "none"


def test_refresh_cookie_follows_the_samesite_setting(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cross-site hosting needs SameSite=None or the browser drops the cookie."""
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("COOKIE_SAMESITE", "none")
    get_settings.cache_clear()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        resp = client.post(
            "/auth/register", json={"email": "cookie@example.com", "password": PASSWORD}
        )
    assert resp.status_code == 201
    set_cookie = resp.headers["set-cookie"]
    assert "samesite=none" in set_cookie.lower()
    assert "secure" in set_cookie.lower()


def test_auth_routes_are_rate_limited(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """An open signup route on a public URL has to have a ceiling."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    get_settings.cache_clear()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        codes = [
            client.post(
                "/auth/login", json={"email": f"nobody{i}@example.com", "password": PASSWORD}
            ).status_code
            for i in range(12)
        ]

    assert 429 in codes, f"expected a 429 within 12 attempts, got {codes}"
    assert codes.index(429) >= 10, "the limit should not bite before 10 attempts"


def test_rate_limit_body_uses_detail(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """The frontend client reads `detail`, not slowapi's default `error` key."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    get_settings.cache_clear()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        last = None
        for i in range(12):
            last = client.post(
                "/auth/login", json={"email": f"x{i}@example.com", "password": PASSWORD}
            )
    assert last is not None
    assert last.status_code == 429
    assert isinstance(last.json()["detail"], str)


def test_email_routes_have_a_tighter_ceiling(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Abusing these costs somebody else's inbox and a finite send quota, so the
    limit is lower than the general auth one."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    get_settings.cache_clear()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        codes = [
            client.post(
                "/auth/forgot-password", json={"email": f"nobody{i}@example.com"}
            ).status_code
            for i in range(8)
        ]

    assert 429 in codes, f"expected a 429 within 8 attempts, got {codes}"
    assert codes.index(429) >= 5, "the limit should not bite before 5 attempts"


def test_rate_limit_resets_when_the_window_passes(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ceiling that never lifts is an outage. `limiter.reset()` is what
    `create_app` calls per process; this asserts the counters really do clear."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    get_settings.cache_clear()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        for i in range(12):
            client.post("/auth/login", json={"email": f"z{i}@example.com", "password": PASSWORD})
        blocked = client.post(
            "/auth/login", json={"email": "z-final@example.com", "password": PASSWORD}
        )
        assert blocked.status_code == 429

        limiter.reset()
        allowed = client.post(
            "/auth/login", json={"email": "z-final@example.com", "password": PASSWORD}
        )
        assert allowed.status_code != 429


def test_empty_frontend_origin_is_refused_at_boot() -> None:
    """Nothing can be built from an empty origin list — not CORS, and not the
    links we email. Failing here beats a 500 the first time someone asks to
    reset a password, long after the deploy looked healthy."""
    with pytest.raises(ValueError, match="FRONTEND_ORIGIN"):
        Settings(_env_file=None, frontend_origin="")  # type: ignore[call-arg]


def test_a_bad_public_app_url_degrades_instead_of_taking_the_api_down() -> None:
    """These settings govern one feature. Refusing to boot over them would take
    budgets, transactions and everything else down with the emails — a far worse
    outcome than links pointing at the wrong-but-allowed origin."""
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        frontend_origin="https://app.example.com",
        public_app_url="https://evil.example.com",
    )
    # Never the unlisted host: the point is that the origin is ours, not theirs.
    assert settings.app_base_url == "https://app.example.com"


def test_origins_are_compared_after_normalising_both_sides() -> None:
    """A trailing slash on FRONTEND_ORIGIN used to make an identically-typed
    PUBLIC_APP_URL fail to match itself, and that was a boot failure."""
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        frontend_origin="https://app.example.com/",
        public_app_url="https://app.example.com",
    )
    assert settings.cors_origins == ["https://app.example.com"]
    assert settings.app_base_url == "https://app.example.com"


def test_a_provider_without_a_key_still_boots_and_sends_nothing() -> None:
    from app.email import ConsoleSender, get_sender

    settings = Settings(_env_file=None, email_provider="resend", email_api_key="")  # type: ignore[call-arg]
    assert settings.email_provider == "resend"
    get_settings.cache_clear()
    assert isinstance(get_sender(), ConsoleSender)
