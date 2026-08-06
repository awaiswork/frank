"""Sign in with Google.

Google is never contacted. The token exchange and the JWKS lookup are both
stubbed, and the id_token is signed with a throwaway RSA key so the signature
path is exercised for real rather than skipped — a test that disabled signature
verification would pass just as happily against a forged token.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import OAuthAccount, OAuthState, User
from tests.conftest import SentEmail
from tests.test_auth_codes import PW, register

CLIENT_ID = "test-client-id.apps.googleusercontent.com"
SUBJECT = "108234567890123456789"

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def google(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure the client, and point JWKS at our throwaway key."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    get_settings.cache_clear()

    class _Key:
        key = _key.public_key()

    monkeypatch.setattr(
        "app.routers.oauth._jwks_client.get_signing_key_from_jwt", lambda _token: _Key()
    )


def id_token(**overrides: Any) -> str:
    claims: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": SUBJECT,
        "email": "someone@gmail.com",
        "email_verified": True,
        "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
        "iat": int(datetime.now(UTC).timestamp()),
    }
    claims.update(overrides)
    return jwt.encode(claims, _key, algorithm="RS256")


@pytest.fixture
def exchange(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Stub Google's token endpoint. Returns a setter for the id_token."""
    box: dict[str, str] = {"token": id_token()}

    class _Response:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict[str, str]:
            return {"id_token": box["token"]}

    monkeypatch.setattr("app.routers.oauth.httpx.post", lambda *a, **k: _Response())
    return box


def begin(client: TestClient) -> str:
    """Start the flow and return the state Google would hand back."""
    res = client.get("/auth/google/start", follow_redirects=False)
    assert res.status_code == 302
    query = parse_qs(urlparse(res.headers["location"]).query)
    return str(query["state"][0])


class TestNotConfigured:
    def test_routes_404_without_credentials(self, client: TestClient) -> None:
        """The app has to run for someone who never set Google up."""
        assert client.get("/auth/google/start", follow_redirects=False).status_code == 404
        assert client.get("/auth/google/callback", follow_redirects=False).status_code == 404


class TestStart:
    def test_redirects_to_google_with_pkce(self, client: TestClient, google: None) -> None:
        res = client.get("/auth/google/start", follow_redirects=False)
        assert res.status_code == 302
        target = urlparse(res.headers["location"])
        assert target.netloc == "accounts.google.com"
        query = parse_qs(target.query)
        assert query["client_id"] == [CLIENT_ID]
        assert query["response_type"] == ["code"]
        assert query["code_challenge_method"] == ["S256"]
        assert query["scope"] == ["openid email profile"]
        assert query["code_challenge"][0]

    def test_only_non_sensitive_scopes_are_requested(
        self, client: TestClient, google: None
    ) -> None:
        """Anything beyond these three would require Google review and a
        verified domain, which is exactly what this flow exists to avoid."""
        res = client.get("/auth/google/start", follow_redirects=False)
        query = parse_qs(urlparse(res.headers["location"]).query)
        assert set(query["scope"][0].split()) == {"openid", "email", "profile"}

    def test_state_is_stored_hashed(self, client: TestClient, db: Session, google: None) -> None:
        state = begin(client)
        stored = db.scalars(select(OAuthState.state_hash)).all()
        assert state not in stored


class TestCallbackSecurity:
    def test_rejects_an_unverified_google_email(
        self, client: TestClient, db: Session, google: None, exchange: Any
    ) -> None:
        """The linking rule trusts Google's assertion that the address is real.
        Without this check, anyone who could add an unverified address to a
        Google account could claim the matching Frankly account."""
        state = begin(client)
        exchange["token"] = id_token(email_verified=False)
        res = client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
        assert res.status_code == 302
        assert "oauth=failed" in res.headers["location"]
        assert db.scalar(select(User).where(User.email == "someone@gmail.com")) is None

    def test_rejects_a_token_minted_for_another_app(
        self, client: TestClient, google: None, exchange: Any
    ) -> None:
        state = begin(client)
        exchange["token"] = id_token(aud="someone-elses-client-id")
        res = client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
        assert "oauth=failed" in res.headers["location"]

    def test_rejects_a_wrong_issuer(self, client: TestClient, google: None, exchange: Any) -> None:
        state = begin(client)
        exchange["token"] = id_token(iss="https://evil.example.com")
        res = client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
        assert "oauth=failed" in res.headers["location"]

    def test_rejects_an_expired_token(
        self, client: TestClient, google: None, exchange: Any
    ) -> None:
        state = begin(client)
        exchange["token"] = id_token(
            exp=int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())
        )
        res = client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
        assert "oauth=failed" in res.headers["location"]

    def test_rejects_a_token_signed_by_someone_else(
        self, client: TestClient, google: None, exchange: Any
    ) -> None:
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        state = begin(client)
        exchange["token"] = jwt.encode(
            {
                "iss": "https://accounts.google.com",
                "aud": CLIENT_ID,
                "sub": SUBJECT,
                "email": "someone@gmail.com",
                "email_verified": True,
                "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
            },
            other,
            algorithm="RS256",
        )
        res = client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
        assert "oauth=failed" in res.headers["location"]

    def test_state_is_single_use(self, client: TestClient, google: None, exchange: Any) -> None:
        """A captured callback URL must not be replayable."""
        state = begin(client)
        first = client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
        assert "/auth/callback" in first.headers["location"]
        second = client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
        assert "oauth=expired" in second.headers["location"]

    def test_unknown_state_is_refused(
        self, client: TestClient, google: None, exchange: Any
    ) -> None:
        res = client.get("/auth/google/callback?code=x&state=never-issued", follow_redirects=False)
        assert "oauth=expired" in res.headers["location"]

    def test_expired_state_is_refused(
        self, client: TestClient, db: Session, google: None, exchange: Any
    ) -> None:
        state = begin(client)
        row = db.scalar(select(OAuthState))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.flush()
        res = client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
        assert "oauth=expired" in res.headers["location"]

    def test_cancelling_at_the_consent_screen_is_not_an_error(
        self, client: TestClient, google: None
    ) -> None:
        res = client.get("/auth/google/callback?error=access_denied", follow_redirects=False)
        assert res.status_code == 302
        assert "oauth=cancelled" in res.headers["location"]


class TestCallbackSuccess:
    def test_creates_an_account_and_a_session(
        self, client: TestClient, db: Session, google: None, exchange: Any
    ) -> None:
        state = begin(client)
        res = client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)

        assert res.status_code == 302
        assert res.headers["location"].endswith("/auth/callback")
        # The cookie rides on the redirect. Setting it on an injected Response
        # would be dropped the moment a different Response is returned.
        assert "frankly_refresh" in res.cookies

        user = db.scalar(select(User).where(User.email == "someone@gmail.com"))
        assert user is not None
        assert user.email_verified_at is not None, "Google proved the address"
        assert user.password_hash is None, "never had a password"

    def test_the_access_token_never_appears_in_the_url(
        self, client: TestClient, google: None, exchange: Any
    ) -> None:
        """URLs reach history, Referer headers and server logs."""
        state = begin(client)
        res = client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
        location = res.headers["location"]
        assert "token" not in location and "?" not in location

    def test_a_new_account_gets_its_default_categories(
        self, client: TestClient, google: None, exchange: Any
    ) -> None:
        state = begin(client)
        client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
        token = client.post("/auth/refresh").json()["access_token"]
        categories = client.get("/categories", headers={"Authorization": f"Bearer {token}"})
        assert categories.status_code == 200
        assert len(categories.json()) > 0

    def test_signing_in_twice_reuses_the_same_account(
        self, client: TestClient, db: Session, google: None, exchange: Any
    ) -> None:
        for _ in range(2):
            state = begin(client)
            client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
        assert len(db.scalars(select(User)).all()) == 1
        assert len(db.scalars(select(OAuthAccount)).all()) == 1

    def test_a_changed_google_email_still_finds_the_account(
        self, client: TestClient, db: Session, google: None, exchange: Any
    ) -> None:
        """Matching is on the stable `sub`, not the address, which people change."""
        state = begin(client)
        client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)

        exchange["token"] = id_token(email="renamed@gmail.com")
        state = begin(client)
        client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)

        assert len(db.scalars(select(User)).all()) == 1


class TestLinking:
    def test_google_links_to_an_existing_password_account(
        self, client: TestClient, db: Session, google: None, exchange: Any, outbox: list[SentEmail]
    ) -> None:
        register(client, email="someone@gmail.com", password=PW)
        before = db.scalar(select(User).where(User.email == "someone@gmail.com"))
        assert before is not None and before.email_verified_at is None

        state = begin(client)
        client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)

        assert len(db.scalars(select(User)).all()) == 1
        after = db.scalar(select(User).where(User.email == "someone@gmail.com"))
        assert after is not None
        assert after.email_verified_at is not None, "Google's assertion unblocks the gate"
        assert after.password_hash is not None, "the existing password survives linking"

    def test_the_password_still_works_after_linking(
        self, client: TestClient, google: None, exchange: Any, outbox: list[SentEmail]
    ) -> None:
        """Linking is additive — it must not lock someone out of the way in
        they already had."""
        register(client, email="someone@gmail.com", password=PW)
        state = begin(client)
        client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)

        res = client.post("/auth/login", json={"email": "someone@gmail.com", "password": PW})
        assert res.status_code == 200, "linking verified the address, so login now works"
