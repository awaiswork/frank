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
from app.main import create_app

PASSWORD = "supersecret"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # What Railway/Neon/Heroku hand out — SQLAlchemy would pick psycopg2.
        ("postgresql://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        # Already explicit: left alone.
        ("postgresql+psycopg://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
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
