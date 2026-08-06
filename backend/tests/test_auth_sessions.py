"""Refresh sessions: rotation, reuse detection, revocation, and remember-me."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.tokens import hash_token
from app.models import RefreshSession
from tests.conftest import SentEmail, create_account

PW = "correct-horse-battery"
COOKIE = "frankly_refresh"


def register(client: TestClient, email: str = "a@b.co") -> None:
    """Create a *verified* account. Signing up alone no longer grants a session."""
    create_account(client, email, PW)


def login(client: TestClient, email: str = "a@b.co", remember: bool = False) -> str:
    res = client.post("/auth/login", json={"email": email, "password": PW, "remember_me": remember})
    assert res.status_code == 200, res.text
    return str(res.cookies[COOKIE])


def live_sessions(
    db: Session,
) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(RefreshSession)
            .where(RefreshSession.revoked_at.is_(None))
        )
        or 0
    )


class TestRotation:
    def test_refresh_issues_a_new_token(self, client: TestClient, outbox: list[SentEmail]) -> None:
        register(client)
        first = login(client)
        res = client.post("/auth/refresh", cookies={COOKIE: first})
        assert res.status_code == 200
        assert res.cookies[COOKIE] != first

    def test_old_token_stops_working_after_the_grace_window(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        register(client)
        first = login(client)
        client.post("/auth/refresh", cookies={COOKIE: first})

        # Age the rotation past the benign-replay window.
        row = db.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == hash_token(first))
        )
        assert row is not None
        row.rotated_at = datetime.now(UTC) - timedelta(minutes=5)
        db.flush()

        assert client.post("/auth/refresh", cookies={COOKIE: first}).status_code == 401

    def test_replay_inside_the_grace_window_is_forgiven(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        """Two tabs boot together and both send the cookie they had. Signing the
        user out for opening a second tab would be a bug, not a defence."""
        register(client)
        first = login(client)
        one = client.post("/auth/refresh", cookies={COOKIE: first})
        two = client.post("/auth/refresh", cookies={COOKIE: first})
        assert one.status_code == 200
        assert two.status_code == 200
        assert one.cookies[COOKIE] != two.cookies[COOKIE]

    def test_session_lifetime_is_not_extended_by_refreshing(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        """Otherwise an active tab refreshes its way to an unbounded session."""
        register(client)
        first = login(client)
        original = db.scalar(
            select(RefreshSession.expires_at).where(RefreshSession.token_hash == hash_token(first))
        )
        res = client.post("/auth/refresh", cookies={COOKIE: first})
        successor = db.scalar(
            select(RefreshSession.expires_at).where(
                RefreshSession.token_hash == hash_token(res.cookies[COOKIE])
            )
        )
        assert original == successor


class TestReuseDetection:
    def test_reuse_kills_the_whole_family(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        register(client)
        stolen = login(client)
        current = client.post("/auth/refresh", cookies={COOKIE: stolen}).cookies[COOKIE]

        # Age the rotation so the replay is unambiguous rather than a second tab.
        row = db.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == hash_token(stolen))
        )
        assert row is not None
        row.rotated_at = datetime.now(UTC) - timedelta(minutes=5)
        db.flush()

        # An attacker replays the copy they captured.
        assert client.post("/auth/refresh", cookies={COOKIE: stolen}).status_code == 401
        # ...which also takes down the legitimate holder's live token.
        assert client.post("/auth/refresh", cookies={COOKIE: current}).status_code == 401

    def test_reuse_does_not_touch_other_logins(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        """One compromised device shouldn't sign you out of the others."""
        register(client)
        laptop = login(client)
        phone = login(client)

        rotated = client.post("/auth/refresh", cookies={COOKIE: laptop}).cookies[COOKIE]
        row = db.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == hash_token(laptop))
        )
        assert row is not None
        row.rotated_at = datetime.now(UTC) - timedelta(minutes=5)
        db.flush()

        client.post("/auth/refresh", cookies={COOKIE: laptop})  # trips detection
        assert client.post("/auth/refresh", cookies={COOKIE: rotated}).status_code == 401
        assert client.post("/auth/refresh", cookies={COOKIE: phone}).status_code == 200

    def test_unknown_token_is_rejected(self, client: TestClient, outbox: list[SentEmail]) -> None:
        assert client.post("/auth/refresh", cookies={COOKIE: "not-a-real-token"}).status_code == 401

    def test_missing_cookie_is_rejected(self, client: TestClient) -> None:
        assert client.post("/auth/refresh").status_code == 401


class TestLogout:
    def test_logout_kills_this_session_only(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        register(client)
        laptop = login(client)
        phone = login(client)

        assert client.post("/auth/logout", cookies={COOKIE: laptop}).status_code == 200
        assert client.post("/auth/refresh", cookies={COOKIE: laptop}).status_code == 401
        assert client.post("/auth/refresh", cookies={COOKIE: phone}).status_code == 200

    def test_logout_actually_revokes_server_side(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        """The bug this whole table exists to fix: before sessions, signing out
        left a working credential in the cookie jar and a reload signed you
        straight back in."""
        register(client)
        token = login(client)
        client.post("/auth/logout", cookies={COOKIE: token})
        # Present the cookie again exactly as a returning browser would.
        assert client.post("/auth/refresh", cookies={COOKIE: token}).status_code == 401

    def test_logout_without_a_cookie_still_succeeds(self, client: TestClient) -> None:
        assert client.post("/auth/logout").status_code == 200

    def test_logout_all_kills_every_session(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        register(client)
        laptop = login(client)
        phone = login(client)
        access = client.post("/auth/login", json={"email": "a@b.co", "password": PW}).json()[
            "access_token"
        ]

        res = client.post("/auth/logout-all", headers={"Authorization": f"Bearer {access}"})
        assert res.status_code == 200
        assert client.post("/auth/refresh", cookies={COOKIE: laptop}).status_code == 401
        assert client.post("/auth/refresh", cookies={COOKIE: phone}).status_code == 401

    def test_logout_all_requires_authentication(self, client: TestClient) -> None:
        assert client.post("/auth/logout-all").status_code == 401


class TestRememberMe:
    def test_remember_me_lasts_longer(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        settings = get_settings()
        register(client)

        short = login(client, remember=False)
        long = login(client, remember=True)

        def expiry(token: str) -> datetime:
            value = db.scalar(
                select(RefreshSession.expires_at).where(
                    RefreshSession.token_hash == hash_token(token)
                )
            )
            assert value is not None
            return value

        now = datetime.now(UTC)
        short_hours = (expiry(short) - now).total_seconds() / 3600
        long_hours = (expiry(long) - now).total_seconds() / 3600

        assert abs(short_hours - settings.refresh_session_short_hours) < 1
        assert abs(long_hours - settings.refresh_token_expire_days * 24) < 1
        assert long_hours > short_hours

    def test_remember_me_does_not_change_cookie_security(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        """Lifetime is the only thing this flag is allowed to touch."""
        register(client)
        plain = client.post("/auth/login", json={"email": "a@b.co", "password": PW})
        remembered = client.post(
            "/auth/login", json={"email": "a@b.co", "password": PW, "remember_me": True}
        )

        def attributes(response: object) -> set[str]:
            header = response.headers["set-cookie"]  # type: ignore[attr-defined]
            return {
                part.strip().lower()
                for part in header.split(";")
                if not part.strip().lower().startswith(("max-age", "expires", "frankly_refresh"))
            }

        assert attributes(plain) == attributes(remembered)


class TestSessionHygiene:
    def test_token_plaintext_is_never_stored(
        self, client: TestClient, db: Session, outbox: list[SentEmail]
    ) -> None:
        register(client)
        token = login(client)
        stored = db.scalars(select(RefreshSession.token_hash)).all()
        assert token not in stored
        assert hash_token(token) in stored

    def test_no_ip_or_user_agent_columns_exist(self) -> None:
        """Data minimisation, asserted rather than assumed: it is easy to add one
        of these later 'just for debugging' and never take it out again."""
        columns = set(RefreshSession.__table__.columns.keys())
        assert not columns & {"ip", "ip_address", "user_agent", "device", "location"}
        assert columns == {
            "id",
            "user_id",
            "family_id",
            "token_hash",
            "created_at",
            "last_used_at",
            "expires_at",
            "revoked_at",
            "rotated_at",
        }


class TestRejectedRefreshClearsTheCookie:
    def test_401_carries_the_cookie_deletion(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        """Setting a cookie on the injected Response only reaches the client on
        the success path — raising HTTPException throws that response away. The
        deletion has to ride on the exception itself, or the browser keeps
        re-sending a dead credential until it ages out."""
        res = client.post("/auth/refresh", cookies={COOKIE: "not-a-real-token"})
        assert res.status_code == 401
        header = res.headers.get("set-cookie")
        assert header is not None, "the dead cookie was left in the browser"
        assert COOKIE in header
        # An immediate expiry is what actually removes it.
        assert "max-age=0" in header.lower() or "expires=" in header.lower()

    def test_revoked_session_also_clears_it(
        self, client: TestClient, outbox: list[SentEmail]
    ) -> None:
        register(client)
        token = login(client)
        client.post("/auth/logout", cookies={COOKIE: token})
        res = client.post("/auth/refresh", cookies={COOKIE: token})
        assert res.status_code == 401
        assert res.headers.get("set-cookie") is not None
