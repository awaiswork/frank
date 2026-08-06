"""The OTP gate: signup verification and the two-step password reset."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuthToken, User
from tests.conftest import SentEmail

PW = "correct-horse-battery"
EMAIL = "a@b.co"


def code_from(email: SentEmail) -> str:
    match = re.search(r"\b(\d{6})\b", email.text)
    assert match, f"no six-digit code in: {email.subject}"
    return match.group(1)


def register(client: TestClient, email: str = EMAIL, password: str = PW) -> None:
    res = client.post("/auth/register", json={"email": email, "password": password})
    assert res.status_code == 202, res.text


def sign_up(client: TestClient, outbox: list[SentEmail], email: str = EMAIL) -> str:
    """Register and verify. Returns the access token."""
    register(client, email)
    res = client.post("/auth/verify-code", json={"email": email, "code": code_from(outbox[-1])})
    assert res.status_code == 200, res.text
    return str(res.json()["access_token"])


def age_codes(db: Session, purpose: str, seconds: int = 3600) -> None:
    """Backdate so the per-user cooldown has lapsed, rather than sleeping."""
    for row in db.scalars(select(AuthToken).where(AuthToken.purpose == purpose)):
        row.created_at = datetime.now(UTC) - timedelta(seconds=seconds)
    db.flush()


class TestTheGate:
    def test_register_returns_no_token(self, client: TestClient, outbox: list[SentEmail]) -> None:
        """The gate is that no credential exists yet, not a per-request check."""
        res = client.post("/auth/register", json={"email": EMAIL, "password": PW})
        assert res.status_code == 202
        assert "access_token" not in res.json()

    def test_register_sends_a_six_digit_code(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        register(client)
        assert len(outbox) == 1
        assert outbox[0].to == EMAIL
        assert re.fullmatch(r"\d{6}", code_from(outbox[0]))
        assert "10 minutes" in outbox[0].text
        assert "didn't sign up" in outbox[0].text

    def test_no_link_in_the_email(self, client: TestClient, outbox: list[SentEmail]) -> None:
        """Codes replaced links outright; a stray link would be a second way to
        spend the same secret."""
        register(client)
        assert "http" not in outbox[0].text

    def test_unverified_account_cannot_reach_the_app(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        register(client)
        # Nothing was issued, so there is nothing to present.
        assert client.get("/me").status_code == 401
        assert client.get("/transactions").status_code == 401

    def test_login_before_verifying_is_refused(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        register(client)
        res = client.post("/auth/login", json={"email": EMAIL, "password": PW})
        assert res.status_code == 403
        # The header is what the client keys on to route to the code screen
        # rather than showing the message as an error.
        assert res.headers.get("x-verification-required") == "1"

    def test_the_refused_login_can_then_get_a_fresh_code(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        """Login raises, and a raised response discards its background tasks —
        so the code comes from resend-code, which is the only sender."""
        register(client)
        age_codes(db, AuthToken.EMAIL_VERIFY_CODE)
        outbox.clear()

        assert client.post("/auth/login", json={"email": EMAIL, "password": PW}).status_code == 403
        assert client.post("/auth/resend-code", json={"email": EMAIL}).status_code == 200
        assert len(outbox) == 1

        token = client.post(
            "/auth/verify-code", json={"email": EMAIL, "code": code_from(outbox[-1])}
        )
        assert token.status_code == 200

    def test_wrong_password_on_an_unverified_account_is_still_401(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        """403 means 'confirm your email'. It must not become an oracle that
        confirms the password was right for an unverified address."""
        register(client)
        res = client.post("/auth/login", json={"email": EMAIL, "password": "wrong-password"})
        assert res.status_code == 401

    def test_verifying_lets_you_in(self, client: TestClient, outbox: list[SentEmail]) -> None:
        token = sign_up(client, outbox)
        me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["email_verified"] is True

    def test_verify_sets_the_refresh_cookie(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        register(client)
        res = client.post("/auth/verify-code", json={"email": EMAIL, "code": code_from(outbox[-1])})
        assert "frankly_refresh" in res.cookies


class TestCodeLifecycle:
    def test_wrong_code_is_rejected(self, client: TestClient, outbox: list[SentEmail]) -> None:
        register(client)
        wrong = "000000" if code_from(outbox[0]) != "000000" else "111111"
        res = client.post("/auth/verify-code", json={"email": EMAIL, "code": wrong})
        assert res.status_code == 400

    def test_code_is_single_use(self, client: TestClient, outbox: list[SentEmail]) -> None:
        register(client)
        code = code_from(outbox[0])
        assert (
            client.post("/auth/verify-code", json={"email": EMAIL, "code": code}).status_code == 200
        )
        again = client.post("/auth/verify-code", json={"email": EMAIL, "code": code})
        assert again.status_code == 400

    def test_expired_code_is_rejected(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        register(client)
        code = code_from(outbox[0])
        row = db.scalar(select(AuthToken).where(AuthToken.purpose == AuthToken.EMAIL_VERIFY_CODE))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.flush()
        assert (
            client.post("/auth/verify-code", json={"email": EMAIL, "code": code}).status_code == 400
        )

    def test_attempts_are_capped_and_burn_the_code(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        """A million possibilities is only meaningful if guesses are limited."""
        register(client)
        real = code_from(outbox[0])
        wrong = "000000" if real != "000000" else "111111"

        last = None
        for _ in range(get_settings().otp_max_attempts):
            last = client.post("/auth/verify-code", json={"email": EMAIL, "code": wrong})
            assert last.status_code == 400
        # The attempt that exhausts the cap says so, so the person knows to ask
        # for another rather than retyping the same digits.
        assert last is not None and "new code" in last.json()["detail"]

        # And the correct code no longer works: the cap burns it outright rather
        # than merely refusing one more try, so an attacker can't keep grinding.
        # The message is generic from here — "that one was burned" would tell a
        # stranger the address exists.
        res = client.post("/auth/verify-code", json={"email": EMAIL, "code": real})
        assert res.status_code == 400

    def test_a_new_code_retires_the_previous_one(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        register(client)
        first = code_from(outbox[0])
        age_codes(db, AuthToken.EMAIL_VERIFY_CODE)
        client.post("/auth/resend-code", json={"email": EMAIL, "purpose": "verify"})
        second = code_from(outbox[-1])
        assert first != second

        assert (
            client.post("/auth/verify-code", json={"email": EMAIL, "code": first}).status_code
            == 400
        )
        assert (
            client.post("/auth/verify-code", json={"email": EMAIL, "code": second}).status_code
            == 200
        )

    def test_malformed_code_is_rejected_before_costing_an_attempt(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        register(client)
        assert (
            client.post("/auth/verify-code", json={"email": EMAIL, "code": "abc"}).status_code
            == 422
        )
        row = db.scalar(select(AuthToken).where(AuthToken.purpose == AuthToken.EMAIL_VERIFY_CODE))
        assert row is not None and row.attempts == 0

    def test_code_is_never_stored_in_the_clear(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        register(client)
        code = code_from(outbox[0])
        hashes = db.scalars(select(AuthToken.secret_hash)).all()
        assert code not in hashes
        # bcrypt, not SHA-256: a six-digit secret is guessable, so the hash has
        # to be slow. (SHA-256 hex is 64 chars; bcrypt starts with $2.)
        assert all(h.startswith("$2") for h in hashes)


class TestEnumeration:
    def test_resend_says_the_same_thing_for_an_unknown_address(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        """resend-code is unauthenticated by necessity — a gated account has no
        token — so it must not become a way to test which addresses exist."""
        register(client, email="known@b.co")
        age_codes(db, AuthToken.EMAIL_VERIFY_CODE)
        outbox.clear()

        known = client.post("/auth/resend-code", json={"email": "known@b.co"})
        unknown = client.post("/auth/resend-code", json={"email": "nobody@b.co"})

        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json()
        assert [e.to for e in outbox] == ["known@b.co"]

    def test_verify_code_does_not_reveal_whether_the_address_exists(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        register(client, email="known2@b.co")
        real = client.post("/auth/verify-code", json={"email": "known2@b.co", "code": "000000"})
        fake = client.post("/auth/verify-code", json={"email": "nobody2@b.co", "code": "000000"})
        assert real.status_code == fake.status_code == 400
        assert real.json() == fake.json()

    def test_forgot_password_is_identical_either_way(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        sign_up(client, outbox, email="known3@b.co")
        outbox.clear()
        known = client.post("/auth/forgot-password", json={"email": "known3@b.co"})
        unknown = client.post("/auth/forgot-password", json={"email": "nobody3@b.co"})
        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json()
        assert [e.to for e in outbox] == ["known3@b.co"]


class TestPasswordReset:
    def _request_code(self, client: TestClient, outbox: list[SentEmail]) -> str:
        sign_up(client, outbox)
        outbox.clear()
        client.post("/auth/forgot-password", json={"email": EMAIL})
        return code_from(outbox[-1])

    def test_two_steps_code_then_password(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        """The code is checked before a new password is typed, so a wrong one
        doesn't waste the attempt."""
        code = self._request_code(client, outbox)
        step1 = client.post("/auth/verify-reset-code", json={"email": EMAIL, "code": code})
        assert step1.status_code == 200
        ticket = step1.json()["ticket"]

        step2 = client.post(
            "/auth/reset-password", json={"ticket": ticket, "password": "brand-new-pw"}
        )
        assert step2.status_code == 200
        assert "access_token" not in step2.json()

        assert (
            client.post(
                "/auth/login", json={"email": EMAIL, "password": "brand-new-pw"}
            ).status_code
            == 200
        )
        assert client.post("/auth/login", json={"email": EMAIL, "password": PW}).status_code == 401

    def test_ticket_is_single_use(self, client: TestClient, outbox: list[SentEmail]) -> None:
        code = self._request_code(client, outbox)
        ticket = client.post("/auth/verify-reset-code", json={"email": EMAIL, "code": code}).json()[
            "ticket"
        ]
        assert (
            client.post(
                "/auth/reset-password", json={"ticket": ticket, "password": "pw-one-1111"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/auth/reset-password", json={"ticket": ticket, "password": "pw-two-2222"}
            ).status_code
            == 400
        )

    def test_reset_code_cannot_be_replayed_after_the_ticket_is_issued(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        code = self._request_code(client, outbox)
        client.post("/auth/verify-reset-code", json={"email": EMAIL, "code": code})
        again = client.post("/auth/verify-reset-code", json={"email": EMAIL, "code": code})
        assert again.status_code == 400

    def test_a_forged_ticket_is_rejected(self, client: TestClient, outbox: list[SentEmail]) -> None:
        sign_up(client, outbox)
        res = client.post(
            "/auth/reset-password", json={"ticket": "made-up", "password": "brand-new-pw"}
        )
        assert res.status_code == 400

    def test_reset_revokes_every_session(self, client: TestClient, outbox: list[SentEmail]) -> None:
        sign_up(client, outbox)
        laptop = client.post("/auth/login", json={"email": EMAIL, "password": PW}).cookies[
            "frankly_refresh"
        ]
        outbox.clear()

        client.post("/auth/forgot-password", json={"email": EMAIL})
        ticket = client.post(
            "/auth/verify-reset-code", json={"email": EMAIL, "code": code_from(outbox[-1])}
        ).json()["ticket"]
        client.post("/auth/reset-password", json={"ticket": ticket, "password": "brand-new-pw"})

        assert client.post("/auth/refresh", cookies={"frankly_refresh": laptop}).status_code == 401

    def test_reset_also_confirms_an_unverified_address(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        """Otherwise an account could be reset but never entered — the reset
        proves the inbox just as the signup code does."""
        register(client)
        age_codes(db, AuthToken.PASSWORD_RESET_CODE)
        outbox.clear()

        client.post("/auth/forgot-password", json={"email": EMAIL})
        ticket = client.post(
            "/auth/verify-reset-code", json={"email": EMAIL, "code": code_from(outbox[-1])}
        ).json()["ticket"]
        client.post("/auth/reset-password", json={"ticket": ticket, "password": "brand-new-pw"})

        res = client.post("/auth/login", json={"email": EMAIL, "password": "brand-new-pw"})
        assert res.status_code == 200

    def test_reset_attempts_are_capped_too(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        code = self._request_code(client, outbox)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(get_settings().otp_max_attempts):
            client.post("/auth/verify-reset-code", json={"email": EMAIL, "code": wrong})
        assert (
            client.post("/auth/verify-reset-code", json={"email": EMAIL, "code": code}).status_code
            == 400
        )


class TestCooldown:
    def test_resend_is_throttled_per_user(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        register(client)
        outbox.clear()
        res = client.post("/auth/resend-code", json={"email": EMAIL})
        assert res.status_code == 200
        assert res.json()["retry_after_seconds"] > 0
        assert outbox == [], "registration already sent one; this must not send another"

    def test_no_secrets_reach_the_log(
        self,
        client: TestClient,
        outbox: list[SentEmail],
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import logging

        monkeypatch.setattr(logging.getLogger("frankly"), "propagate", True)
        with caplog.at_level("INFO", logger="frankly"):
            register(client, email="secret@b.co")

        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "secret@b.co" not in logged
        assert code_from(outbox[-1]) not in logged
        assert "registered" in logged


class TestGoogleOnlyAccounts:
    def test_an_account_with_no_password_cannot_be_signed_into(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        """A Google-only account has a null hash. Login must treat that as an
        ordinary failure, not announce that the address uses Google."""
        db.add(User(email="google-only@b.co", password_hash=None))
        db.flush()
        res = client.post("/auth/login", json={"email": "google-only@b.co", "password": PW})
        assert res.status_code == 401
        assert res.json()["detail"] == "Invalid email or password"
