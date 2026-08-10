"""The weekly digest, and the two surfaces it opens.

Most of this is about those surfaces rather than the email. Until now every route was
either public and read-only or behind a bearer token belonging to a signed-in person.
This phase adds one route callable with a shared secret that emails every user, and one
callable with no session at all — and because the digest defaults to *on*, the
unsubscribe path is load-bearing rather than a courtesy.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.signing import sign, verify
from app.models import NotificationSetting, Transaction, User
from app.services import digest
from tests.conftest import SENT
from tests.conftest import create_account as register

KIND = NotificationSetting.WEEKLY_DIGEST
# A Monday, 09:00 UTC — past the local send hour for someone in UTC.
MONDAY = dt.datetime(2026, 8, 3, 9, 0, tzinfo=dt.UTC)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _user(db: Session, *, timezone: str | None = None, verified: bool = True) -> User:
    user = User(
        email=f"{uuid.uuid4().hex}@ex.com",
        password_hash="x",
        currency="EUR",
        timezone=timezone,
        email_verified_at=dt.datetime.now(dt.UTC) if verified else None,
    )
    db.add(user)
    db.flush()
    return user


# --- the signed capability ---------------------------------------------------


def test_a_token_names_one_user_and_one_kind() -> None:
    user_id = uuid.uuid4()
    token = sign(user_id, KIND)
    assert verify(token, KIND) == user_id
    # Scoped: a digest link must not work for some other kind of message.
    assert verify(token, "something_else") is None


@pytest.mark.parametrize(
    "tampered",
    [
        "",
        "not-a-token",
        "a.b.c",
        f"{uuid.uuid4()}.{KIND}.wrongsignature",
    ],
)
def test_a_tampered_token_speaks_for_nobody(tampered: str) -> None:
    assert verify(tampered, KIND) is None


def test_swapping_the_user_id_invalidates_the_signature() -> None:
    """The id is signed, not merely carried alongside a signature."""
    token = sign(uuid.uuid4(), KIND)
    _, kind, signature = token.split(".")
    assert verify(f"{uuid.uuid4()}.{kind}.{signature}", KIND) is None


def test_rotating_the_secret_key_invalidates_outstanding_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = sign(uuid.uuid4(), KIND)
    monkeypatch.setattr(get_settings(), "secret_key", "a-completely-different-secret")
    assert verify(token, KIND) is None


# --- the cron endpoint -------------------------------------------------------


def test_the_runner_fails_closed_with_no_secret_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unconfigured must not mean unguarded.

    Email degrades to the console sender when it has no key, which is graceful. A route
    that mails every user must not degrade the same way.
    """
    monkeypatch.setattr(get_settings(), "cron_secret", "")
    res = client.post("/internal/digest/run", headers={"Authorization": "Bearer anything"})
    assert res.status_code == 503


@pytest.mark.parametrize("header", ["", "Bearer wrong", "the-right-one-without-bearer"])
def test_the_runner_refuses_a_bad_secret(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, header: str
) -> None:
    monkeypatch.setattr(get_settings(), "cron_secret", "the-right-one")
    res = client.post("/internal/digest/run", headers={"Authorization": header})
    assert res.status_code == 401


def test_the_runner_accepts_the_right_secret(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "cron_secret", "the-right-one")
    res = client.post("/internal/digest/run", headers={"Authorization": "Bearer the-right-one"})
    assert res.status_code == 200
    # Reports a count and nothing about who — a shared secret should not hand back a
    # list of the service's users.
    assert "queued" in res.json()["detail"].lower()


def test_nothing_is_sent_outside_production(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard that exists because I set this off against real credentials.

    This route's whole job is to email everyone who is due one, so pointed at a machine
    that happens to hold a live mail key it emails real people. A note saying "check
    first" does not prevent that; refusing to send unless ENV is prod does.
    """
    _user(db)
    monkeypatch.setattr(get_settings(), "cron_secret", "s3cret")
    monkeypatch.setattr(get_settings(), "env", "dev")
    monkeypatch.setattr(digest, "SEND_WEEKDAY", dt.datetime.now(dt.UTC).weekday())
    monkeypatch.setattr(digest, "SEND_HOUR", 0)

    before = len(SENT)
    res = client.post("/internal/digest/run", headers={"Authorization": "Bearer s3cret"})
    assert res.status_code == 200
    assert "not sending" in res.json()["detail"]
    assert len(SENT) == before


def test_a_run_that_sends_nothing_takes_nobodys_week(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """So a local run stays repeatable and cannot silently burn the real send."""
    user = _user(db)
    monkeypatch.setattr(get_settings(), "cron_secret", "s3cret")
    monkeypatch.setattr(get_settings(), "env", "dev")
    monkeypatch.setattr(digest, "SEND_WEEKDAY", dt.datetime.now(dt.UTC).weekday())
    monkeypatch.setattr(digest, "SEND_HOUR", 0)

    client.post("/internal/digest/run", headers={"Authorization": "Bearer s3cret"})
    setting = db.scalar(select(NotificationSetting).where(NotificationSetting.user_id == user.id))
    assert setting is None or setting.last_sent_at is None


def test_a_dry_run_in_production_sends_nothing_either(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user(db)
    monkeypatch.setattr(get_settings(), "cron_secret", "s3cret")
    monkeypatch.setattr(get_settings(), "env", "prod")
    monkeypatch.setattr(digest, "SEND_WEEKDAY", dt.datetime.now(dt.UTC).weekday())
    monkeypatch.setattr(digest, "SEND_HOUR", 0)

    before = len(SENT)
    res = client.post("/internal/digest/run?dry=true", headers={"Authorization": "Bearer s3cret"})
    assert "not sending" in res.json()["detail"]
    assert len(SENT) == before


# --- who is due, and exactly once --------------------------------------------


def test_only_on_the_local_monday_morning(db: Session) -> None:
    """Enabling on a Wednesday must not fire immediately because 8am has passed."""
    _user(db)
    assert digest.due_now(db, dt.datetime(2026, 8, 5, 9, 0, tzinfo=dt.UTC)) == []  # Wednesday
    assert digest.due_now(db, dt.datetime(2026, 8, 3, 6, 0, tzinfo=dt.UTC)) == []  # too early
    assert len(digest.due_now(db, MONDAY)) == 1


def test_monday_means_the_readers_monday(db: Session) -> None:
    """23:00 UTC Sunday is already Monday morning in Auckland."""
    _user(db, timezone="Pacific/Auckland")
    sunday_late = dt.datetime(2026, 8, 2, 21, 0, tzinfo=dt.UTC)
    assert len(digest.due_now(db, sunday_late)) == 1


def test_a_second_run_the_same_week_sends_to_nobody(db: Session) -> None:
    """The claim, not a read — two overlapping runs cannot both pick the same person."""
    _user(db)
    assert len(digest.due_now(db, MONDAY)) == 1
    assert digest.due_now(db, MONDAY + dt.timedelta(hours=1)) == []
    # Next week is a different week.
    assert len(digest.due_now(db, MONDAY + dt.timedelta(days=7))) == 1


def test_turning_it_off_stops_it(db: Session) -> None:
    user = _user(db)
    db.add(NotificationSetting(user_id=user.id, kind=KIND, enabled=False))
    db.flush()
    assert digest.due_now(db, MONDAY) == []


def test_unverified_addresses_are_never_emailed(db: Session) -> None:
    """Nothing goes to an address nobody has proven they can read."""
    _user(db, verified=False)
    assert digest.due_now(db, MONDAY) == []


# --- what it is allowed to say -----------------------------------------------


def test_no_income_means_no_safe_to_spend_line(db: Session) -> None:
    """The daily note's rule, on the one surface nobody is watching as it is written."""
    user = _user(db)
    content = digest.build(db, user, dt.date(2026, 8, 10))
    assert content.safe_to_spend_cents is None

    user.monthly_income_cents = 300_000
    db.flush()
    assert digest.build(db, user, dt.date(2026, 8, 10)).safe_to_spend_cents is not None


def test_the_week_is_measured_against_the_one_before(db: Session) -> None:
    user = _user(db)
    today = dt.date(2026, 8, 10)
    for days_ago, cents in ((3, 40_00), (10, 25_00)):
        db.add(
            Transaction(
                user_id=user.id,
                kind="expense",
                amount_cents=cents,
                description="x",
                occurred_on=today - dt.timedelta(days=days_ago),
            )
        )
    db.flush()

    content = digest.build(db, user, today)
    assert content.spent_cents == 40_00
    assert content.previous_spent_cents == 25_00


def test_the_email_omits_the_line_it_cannot_support(db: Session) -> None:
    from app.email.templates import weekly_digest_email

    common = dict(
        spent_cents=40_00,
        previous_spent_cents=25_00,
        top_categories=[],
        upcoming_cents=0,
        upcoming_count=0,
        streak=0,
        unsubscribe_url="https://example.test/unsubscribe?token=x",
    )
    without = weekly_digest_email(**common, safe_to_spend_cents=None)  # type: ignore[arg-type]
    with_it = weekly_digest_email(**common, safe_to_spend_cents=100_00)  # type: ignore[arg-type]

    assert "safe to spend" not in without.text.lower()
    assert "safe to spend" in with_it.text.lower()
    # And the link out is in both, in text as well as HTML — some clients render only
    # the plain part, and an unsubscribe that only exists in HTML is not an unsubscribe.
    for message in (without, with_it):
        assert "unsubscribe?token=x" in message.text
        assert "unsubscribe?token=x" in message.html


# --- unsubscribing without a session -----------------------------------------


def test_unsubscribing_from_a_link_turns_it_off(client: TestClient, db: Session) -> None:
    token = register(client, "unsub@example.com")
    user = db.scalar(select(User).where(User.email == "unsub@example.com"))
    assert user is not None
    assert client.get("/notifications", headers=_h(token)).json()["weekly_digest"] is True

    res = client.post("/notifications/unsubscribe", json={"token": sign(user.id, KIND)})
    assert res.status_code == 200
    assert client.get("/notifications", headers=_h(token)).json()["weekly_digest"] is False


def test_unsubscribing_twice_says_the_same_thing(client: TestClient, db: Session) -> None:
    token = register(client, "twice-unsub@example.com")
    user = db.scalar(select(User).where(User.email == "twice-unsub@example.com"))
    assert user is not None
    signed = sign(user.id, KIND)

    first = client.post("/notifications/unsubscribe", json={"token": signed})
    second = client.post("/notifications/unsubscribe", json={"token": signed})
    assert first.json() == second.json()
    assert client.get("/notifications", headers=_h(token)).json()["weekly_digest"] is False


def test_a_useless_token_is_answered_identically(client: TestClient) -> None:
    """No oracle: the reply must not reveal whether the token names anyone."""
    real_but_unknown = sign(uuid.uuid4(), KIND)
    answers = {
        client.post("/notifications/unsubscribe", json={"token": t}).json()["detail"]
        for t in (real_but_unknown, "garbage", f"{uuid.uuid4()}.{KIND}.bad")
    }
    assert len(answers) == 1


def test_an_unsubscribe_token_is_not_a_way_in(client: TestClient, db: Session) -> None:
    """It stops email. It is not a session and must not be mistaken for one."""
    register(client, "notauth@example.com")
    user = db.scalar(select(User).where(User.email == "notauth@example.com"))
    assert user is not None
    signed = sign(user.id, KIND)

    assert client.get("/me", headers={"Authorization": f"Bearer {signed}"}).status_code == 401
    assert (
        client.get("/transactions", headers={"Authorization": f"Bearer {signed}"}).status_code
        == 401
    )


def test_preferences_round_trip_for_a_signed_in_user(client: TestClient) -> None:
    token = register(client, "prefs@example.com")
    assert client.get("/notifications", headers=_h(token)).json() == {"weekly_digest": True}

    off = client.patch("/notifications", headers=_h(token), json={"weekly_digest": False})
    assert off.json() == {"weekly_digest": False}
    on = client.patch("/notifications", headers=_h(token), json={"weekly_digest": True})
    assert on.json() == {"weekly_digest": True}


def test_a_run_emails_the_people_it_claimed(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client, "gets-one@example.com")
    user = db.scalar(select(User).where(User.email == "gets-one@example.com"))
    assert user is not None
    user.timezone = None
    db.flush()

    monkeypatch.setattr(get_settings(), "cron_secret", "s3cret")
    # Explicit: this is the one test exercising real delivery, so it has to say so.
    monkeypatch.setattr(get_settings(), "env", "prod")
    monkeypatch.setattr(digest, "SEND_WEEKDAY", dt.datetime.now(dt.UTC).weekday())
    monkeypatch.setattr(digest, "SEND_HOUR", 0)

    before = len(SENT)
    res = client.post("/internal/digest/run", headers={"Authorization": "Bearer s3cret"})
    assert res.status_code == 200
    assert len(SENT) > before
    assert "unsubscribe?token=" in SENT[-1].text
