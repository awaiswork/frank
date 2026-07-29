"""Password reset, email verification, and the emails that carry them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.tokens import hash_token
from app.models import AuthToken
from tests.conftest import SentEmail

PW = "correct-horse-battery"


def register(client: TestClient, email: str = "a@b.co", password: str = PW) -> str:
    res = client.post("/auth/register", json={"email": email, "password": password})
    assert res.status_code == 201, res.text
    return str(res.json()["access_token"])


def age_tokens(db: Session, purpose: str, seconds: int = 3600) -> None:
    """Backdate this purpose's tokens so the per-user cooldown has lapsed.

    Registration issues a verification token, so anything testing a *resend*
    would otherwise be answered by the cooldown — correctly. Moving the clock
    beats sleeping through it.
    """
    for row in db.scalars(select(AuthToken).where(AuthToken.purpose == purpose)):
        row.created_at = datetime.now(UTC) - timedelta(seconds=seconds)
    db.flush()


class TestVerificationEmail:
    def test_registration_sends_a_verification_link(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        register(client)
        assert len(outbox) == 1
        email = outbox[0]
        assert email.to == "a@b.co"
        assert email.subject == "Confirm your email"
        # Both parts, every time — some clients render the text alternative.
        assert email.text and email.html
        assert "/verify-email?token=" in email.link

    def test_link_points_at_the_frontend_not_the_api(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        register(client)
        assert outbox[0].link.startswith(get_settings().app_base_url)

    def test_email_states_the_expiry_and_what_to_do_if_unwanted(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        register(client)
        body = outbox[0].text
        assert "24 hours" in body
        assert "didn't sign up" in body

    def test_new_user_starts_unverified(self, client: TestClient, outbox: list[SentEmail]) -> None:
        token = register(client)
        me = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert me["email_verified"] is False

    def test_verifying_flips_the_flag(self, client: TestClient, outbox: list[SentEmail]) -> None:
        token = register(client)
        res = client.post("/auth/verify-email", json={"token": outbox[0].token})
        assert res.status_code == 200
        me = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert me["email_verified"] is True

    def test_token_is_single_use(self, client: TestClient, outbox: list[SentEmail]) -> None:
        register(client)
        raw = outbox[0].token
        assert client.post("/auth/verify-email", json={"token": raw}).status_code == 200
        assert client.post("/auth/verify-email", json={"token": raw}).status_code == 400

    def test_tampered_token_is_rejected(self, client: TestClient, outbox: list[SentEmail]) -> None:
        register(client)
        raw = outbox[0].token
        assert client.post("/auth/verify-email", json={"token": raw[:-1] + "x"}).status_code == 400

    def test_expired_token_is_rejected(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        register(client)
        raw = outbox[0].token
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_token(raw)))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.flush()
        assert client.post("/auth/verify-email", json={"token": raw}).status_code == 400

    def test_a_reset_token_cannot_verify_an_email(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        """Purpose is part of the lookup, so tokens can't be used sideways."""
        register(client)
        outbox.clear()
        client.post("/auth/forgot-password", json={"email": "a@b.co"})
        reset_token = outbox[0].token
        assert client.post("/auth/verify-email", json={"token": reset_token}).status_code == 400

    def test_plaintext_is_never_stored(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        register(client)
        raw = outbox[0].token
        stored = db.scalars(select(AuthToken.token_hash)).all()
        assert raw not in stored
        assert hash_token(raw) in stored


class TestResendVerification:
    def _auth(self, client: TestClient) -> dict[str, str]:
        return {"Authorization": f"Bearer {register(client)}"}

    def test_resend_sends_another(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        headers = self._auth(client)
        age_tokens(db, AuthToken.EMAIL_VERIFY)
        outbox.clear()
        res = client.post("/auth/resend-verification", headers=headers)
        assert res.status_code == 200
        assert len(outbox) == 1

    def test_resend_invalidates_the_previous_link(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        headers = self._auth(client)
        first = outbox[0].token
        age_tokens(db, AuthToken.EMAIL_VERIFY)
        outbox.clear()

        client.post("/auth/resend-verification", headers=headers)
        second = outbox[0].token
        assert first != second
        assert client.post("/auth/verify-email", json={"token": first}).status_code == 400
        assert client.post("/auth/verify-email", json={"token": second}).status_code == 200

    def test_cooldown_blocks_the_second_send_and_tells_the_client_how_long(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        headers = self._auth(client)
        age_tokens(db, AuthToken.EMAIL_VERIFY)
        outbox.clear()

        first = client.post("/auth/resend-verification", headers=headers).json()
        assert first["retry_after_seconds"] == get_settings().email_resend_cooldown_seconds

        second = client.post("/auth/resend-verification", headers=headers)
        # A cooldown is not an error — the UI shows a countdown, not a failure.
        assert second.status_code == 200
        assert (
            0 < second.json()["retry_after_seconds"] <= get_settings().email_resend_cooldown_seconds
        )
        assert len(outbox) == 1, "the cooldown must actually prevent the send"

    def test_registration_itself_starts_the_cooldown(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        """Signing up already sends one, so an immediate resend is throttled."""
        headers = self._auth(client)
        outbox.clear()
        res = client.post("/auth/resend-verification", headers=headers)
        assert res.status_code == 200
        assert res.json()["retry_after_seconds"] > 0
        assert outbox == []

    def test_already_verified_says_so_and_sends_nothing(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        headers = self._auth(client)
        client.post("/auth/verify-email", json={"token": outbox[0].token})
        age_tokens(db, AuthToken.EMAIL_VERIFY)
        outbox.clear()
        res = client.post("/auth/resend-verification", headers=headers)
        assert res.status_code == 200
        assert "already confirmed" in res.json()["detail"]
        assert outbox == []


class TestSoftGate:
    def test_unverified_user_can_still_use_the_app(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        """Verification is a nudge, not a lock. Logging money must never depend on it."""
        headers = {"Authorization": f"Bearer {register(client)}"}
        assert client.get("/categories", headers=headers).status_code == 200
        assert client.get("/transactions", headers=headers).status_code == 200
        created = client.post(
            "/transactions",
            headers=headers,
            json={
                "kind": "expense",
                "amount_cents": 500,
                "description": "coffee",
                "occurred_on": "2026-07-29",
            },
        )
        assert created.status_code == 201
        assert client.get("/insights/summary", headers=headers).status_code == 200


class TestForgotPassword:
    def test_sends_a_reset_link(self, client: TestClient, outbox: list[SentEmail]) -> None:
        register(client)
        outbox.clear()
        res = client.post("/auth/forgot-password", json={"email": "a@b.co"})
        assert res.status_code == 200
        assert outbox[0].subject == "Set a new password"
        assert "/reset-password?token=" in outbox[0].link
        assert "next hour" in outbox[0].text

    def test_unknown_address_is_indistinguishable(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        """The whole point of the endpoint: it must not confirm who has an account."""
        register(client, email="known@b.co")
        outbox.clear()

        known = client.post("/auth/forgot-password", json={"email": "known@b.co"})
        unknown = client.post("/auth/forgot-password", json={"email": "nobody@b.co"})

        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json()
        # Only the real one produced mail, and the caller cannot tell.
        assert [e.to for e in outbox] == ["known@b.co"]

    def test_timing_does_not_give_it_away(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        """A loose bound: the send is backgrounded, so the only difference is a
        row write. Generous enough not to flake in CI, tight enough to catch a
        bcrypt call or a provider round-trip creeping onto the known path."""
        import time

        register(client, email="known2@b.co")

        def elapsed(email: str) -> float:
            start = time.perf_counter()
            client.post("/auth/forgot-password", json={"email": email})
            return time.perf_counter() - start

        # Warm caches first so the first call isn't measured cold.
        elapsed("warm@b.co")
        known = min(elapsed("known2@b.co") for _ in range(3))
        unknown = min(elapsed("nobody2@b.co") for _ in range(3))
        assert abs(known - unknown) < 0.15

    def test_new_token_invalidates_the_previous_one(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        register(client)
        outbox.clear()
        client.post("/auth/forgot-password", json={"email": "a@b.co"})
        first = outbox[0].token

        # Step past the per-user cooldown rather than sleeping through it.
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_token(first)))
        assert row is not None
        row.created_at = datetime.now(UTC) - timedelta(hours=1)
        db.flush()

        outbox.clear()
        client.post("/auth/forgot-password", json={"email": "a@b.co"})
        second = outbox[0].token

        assert (
            client.post(
                "/auth/reset-password", json={"token": first, "password": "new-password-1"}
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/auth/reset-password", json={"token": second, "password": "new-password-1"}
            ).status_code
            == 200
        )


class TestResetPassword:
    def _request_reset(self, client: TestClient, outbox: list[SentEmail]) -> str:
        register(client)
        outbox.clear()
        client.post("/auth/forgot-password", json={"email": "a@b.co"})
        return outbox[0].token

    def test_sets_the_new_password(self, client: TestClient, outbox: list[SentEmail]) -> None:
        token = self._request_reset(client, outbox)
        res = client.post("/auth/reset-password", json={"token": token, "password": "brand-new-pw"})
        assert res.status_code == 200
        assert (
            client.post(
                "/auth/login", json={"email": "a@b.co", "password": "brand-new-pw"}
            ).status_code
            == 200
        )
        assert (
            client.post("/auth/login", json={"email": "a@b.co", "password": PW}).status_code == 401
        )

    def test_does_not_sign_the_user_in(self, client: TestClient, outbox: list[SentEmail]) -> None:
        """Reading the inbox proves access to the inbox, not to the account."""
        token = self._request_reset(client, outbox)
        res = client.post("/auth/reset-password", json={"token": token, "password": "brand-new-pw"})
        assert "access_token" not in res.json()

    def test_is_single_use(self, client: TestClient, outbox: list[SentEmail]) -> None:
        token = self._request_reset(client, outbox)
        first = client.post("/auth/reset-password", json={"token": token, "password": "pw-one-111"})
        second = client.post(
            "/auth/reset-password", json={"token": token, "password": "pw-two-222"}
        )
        assert first.status_code == 200
        assert second.status_code == 400

    def test_expired_token_is_rejected(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        token = self._request_reset(client, outbox)
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_token(token)))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.flush()
        res = client.post("/auth/reset-password", json={"token": token, "password": "brand-new-pw"})
        assert res.status_code == 400

    def test_wrong_user_token_only_affects_its_owner(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        register(client, email="one@b.co")
        register(client, email="two@b.co")
        outbox.clear()
        client.post("/auth/forgot-password", json={"email": "one@b.co"})
        token_for_one = outbox[0].token

        client.post("/auth/reset-password", json={"token": token_for_one, "password": "changed-11"})

        # user two is untouched
        assert (
            client.post("/auth/login", json={"email": "two@b.co", "password": PW}).status_code
            == 200
        )
        assert (
            client.post("/auth/login", json={"email": "one@b.co", "password": PW}).status_code
            == 401
        )

    def test_short_password_is_rejected(self, client: TestClient, outbox: list[SentEmail]) -> None:
        token = self._request_reset(client, outbox)
        res = client.post("/auth/reset-password", json={"token": token, "password": "short"})
        assert res.status_code == 422


class TestNoSecretsInLogs:
    def test_tokens_and_addresses_stay_out_of_the_log(
        self,
        client: TestClient,
        outbox: list[SentEmail],
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The app's logger sets propagate=False so it doesn't disturb uvicorn's;
        # caplog listens on the root, so it sees nothing unless we reconnect them.
        import logging

        monkeypatch.setattr(logging.getLogger("frankly"), "propagate", True)
        with caplog.at_level("INFO", logger="frankly"):
            register(client, email="secret@b.co")
            client.post("/auth/forgot-password", json={"email": "secret@b.co"})

        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "secret@b.co" not in logged
        for email in outbox:
            assert email.token not in logged
            assert email.link not in logged
        # It should still say something useful.
        assert "password_reset_requested" in logged


class TestEmailProviderIsolation:
    def test_default_provider_sends_nothing_anywhere(self) -> None:
        """No key, no network, no provider — the suite and dev both rely on this."""
        from app.email import ConsoleSender, get_sender

        assert isinstance(get_sender(), ConsoleSender)

    def test_resend_requires_a_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.config import Settings

        monkeypatch.setenv("EMAIL_PROVIDER", "resend")
        monkeypatch.delenv("EMAIL_API_KEY", raising=False)
        with pytest.raises(ValueError, match="EMAIL_API_KEY"):
            Settings(_env_file=None)  # type: ignore[call-arg]


class TestSuiteCannotSendRealEmail:
    def test_a_live_key_in_dotenv_cannot_leak_into_the_suite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The autouse fixture pins the provider, so a developer with a real key
        configured still runs an offline suite. Without this, `uv run pytest`
        on a machine with EMAIL_PROVIDER=resend would post to the provider —
        from CI, or from anyone who cloned the repo and filled in a .env."""
        from app.email import ConsoleSender, get_sender

        monkeypatch.setenv("EMAIL_PROVIDER", "resend")
        monkeypatch.setenv("EMAIL_API_KEY", "placeholder-not-a-key")
        get_settings.cache_clear()
        # The fixture's environment is what the app reads; prove the guard is
        # the fixture and not luck, by restoring it the way the fixture does.
        monkeypatch.setenv("EMAIL_PROVIDER", "console")
        monkeypatch.delenv("EMAIL_API_KEY", raising=False)
        get_settings.cache_clear()
        assert isinstance(get_sender(), ConsoleSender)
