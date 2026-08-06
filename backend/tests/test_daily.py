"""Daily-note tests — the pure mood logic and the cache / streak / fallback endpoint flow.

The model is mocked (no key/network): we patch ``daily.generate`` to return a canned
note, and assert the note is generated once then served from cache, that the streak
counts, and that a model failure falls back instead of breaking the home screen.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyNote, Transaction, User
from app.services import daily
from tests.conftest import create_account

PASSWORD = "supersecret"


def _register(client: TestClient, email: str) -> str:
    """Verified account + token. Registration alone no longer grants either."""
    return create_account(client, email, PASSWORD)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _set_income(db: Session, email: str, cents: int = 320_000) -> User:
    """Give a test user a stated income so the mood is a verdict, not 'unknown'."""
    user = db.scalar(select(User).where(User.email == email))
    assert user is not None
    user.monthly_income_cents = cents
    db.flush()
    return user


def test_compute_mood() -> None:
    today = dt.date(2026, 6, 15)  # June has 30 days -> 15 days left
    known = {"income_known": True}
    # already past safe-to-spend
    assert daily.compute_mood({**known, "safe_to_spend_eur": -10.0}, today) == "over"
    # a budget running ahead of pace -> ease off
    hot: dict[str, Any] = {
        **known,
        "safe_to_spend_eur": 500.0,
        "daily_burn_eur": 0,
        "budgets": [{"on_track": False}],
    }
    assert daily.compute_mood(hot, today) == "wait"
    # current burn would blow the remaining days -> ease off
    burn_hot: dict[str, Any] = {
        **known,
        "safe_to_spend_eur": 100.0,
        "daily_burn_eur": 50,
        "budgets": [],
    }
    assert daily.compute_mood(burn_hot, today) == "wait"
    # comfortably on track
    calm: dict[str, Any] = {
        **known,
        "safe_to_spend_eur": 1000.0,
        "daily_burn_eur": 5,
        "budgets": [{"on_track": True}],
    }
    assert daily.compute_mood(calm, today) == "go"


def test_mood_is_unknown_without_income() -> None:
    """No income on file -> refuse to judge, however the numbers happen to land.

    This is the bug that let a brand-new user be told they were "spending within
    their means" when safe-to-spend was really just 0 minus whatever they'd logged.
    """
    today = dt.date(2026, 6, 15)
    # 0 income makes safe-to-spend read 0 (looks calm) or negative (looks alarming);
    # neither is a real verdict, so both must come back 'unknown'.
    assert daily.compute_mood({"income_known": False, "safe_to_spend_eur": 0.0}, today) == "unknown"
    assert (
        daily.compute_mood({"income_known": False, "safe_to_spend_eur": -8.4}, today) == "unknown"
    )
    # absent flag is treated as unknown too — fail closed, never invent confidence
    assert daily.compute_mood({"safe_to_spend_eur": 0.0}, today) == "unknown"
    # and the note we serve asks for the missing number instead of passing judgement
    headline, note = daily.fallback("unknown")
    assert "income" in note.lower()
    for claim in ("within your means", "on track", "over"):
        assert claim not in note.lower()
        assert claim not in headline.lower()


def test_daily_generates_once_then_caches_with_streak(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch, ai_on: None
) -> None:
    token = _register(client, "daily@example.com")
    _set_income(db, "daily@example.com")  # a real budget, so the mood is a real 'go'
    calls = {"n": 0}

    async def gen(_context: dict[str, Any], _mood: str) -> tuple[str, str, dict[str, Any]]:
        calls["n"] += 1
        return ("On track", "Looking good today.", {"input_tokens": 1, "output_tokens": 1})

    monkeypatch.setattr("app.services.daily.generate", gen)

    first = client.get("/advisor/daily", headers=_h(token))
    assert first.status_code == 200
    body = first.json()
    assert body["mood"] == "go"
    assert body["headline"] == "On track"
    assert body["note"] == "Looking good today."
    assert body["streak"] == 1
    assert body["date"] == dt.date.today().isoformat()

    # a second load the same day is served from the stored row — the model isn't called again
    second = client.get("/advisor/daily", headers=_h(token))
    assert second.status_code == 200
    assert second.json()["note"] == "Looking good today."
    assert calls["n"] == 1


def test_daily_falls_back_on_model_failure(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch, ai_on: None
) -> None:
    token = _register(client, "dailyfail@example.com")
    _set_income(db, "dailyfail@example.com")

    async def boom(_context: dict[str, Any], _mood: str) -> tuple[str, str, dict[str, Any]]:
        raise daily.DailyError("nope")

    monkeypatch.setattr("app.services.daily.generate", boom)

    resp = client.get("/advisor/daily", headers=_h(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["headline"] == daily.fallback("go")[0]
    assert body["note"] == daily.fallback("go")[1]
    assert body["streak"] == 1


def test_daily_requires_auth(client: TestClient) -> None:
    assert client.get("/advisor/daily").status_code == 401


def test_new_user_gets_no_verdict(client: TestClient, db: Session) -> None:
    """A fresh account has no income, so the note must not read as a green light."""
    token = _register(client, "noincome@example.com")
    body = client.get("/advisor/daily", headers=_h(token)).json()
    assert body["mood"] == "unknown"
    assert body["note"] == daily.fallback("unknown")[1]


def test_note_is_rewritten_when_the_day_turns(client: TestClient, db: Session) -> None:
    """The regression: a note written this morning must not contradict the hero.

    Previously the row was cached for the whole day, so "you're spending within your
    means" stayed on screen after the user had gone past their safe-to-spend.
    """
    token = _register(client, "turns@example.com")
    user = db.scalar(select(User).where(User.email == "turns@example.com"))
    assert user is not None
    user.monthly_income_cents = 100_000  # 1000,00 € -> a real budget to reason from
    db.flush()

    first = client.get("/advisor/daily", headers=_h(token)).json()
    assert first["mood"] == "go"

    # Spend past the whole month's income, the way a user would mid-morning.
    db.add(
        Transaction(
            user_id=user.id,
            kind="expense",
            amount_cents=150_000,
            description="rent",
            occurred_on=dt.date.today(),
        )
    )
    db.flush()

    second = client.get("/advisor/daily", headers=_h(token)).json()
    assert second["mood"] == "over"
    assert second["note"] == daily.fallback("over")[1]
    assert second["note"] != first["note"]
    # still one row for today, so the streak doesn't double-count the rewrite
    assert second["streak"] == 1
    rows = db.scalars(select(DailyNote).where(DailyNote.user_id == user.id)).all()
    assert len(rows) == 1


def test_note_is_not_rewritten_while_the_mood_holds(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch, ai_on: None
) -> None:
    """Within a mood the text stays cached — that's what bounds the model spend."""
    token = _register(client, "stable@example.com")
    user = db.scalar(select(User).where(User.email == "stable@example.com"))
    assert user is not None
    user.monthly_income_cents = 500_000
    db.flush()

    calls = {"n": 0}

    async def gen(_context: dict[str, Any], _mood: str) -> tuple[str, str, dict[str, Any]]:
        calls["n"] += 1
        return ("Plenty of room", "You're well inside it.", {})

    monkeypatch.setattr("app.services.daily.generate", gen)

    client.get("/advisor/daily", headers=_h(token))
    # a small spend that doesn't change the mood must not buy a second note
    db.add(
        Transaction(
            user_id=user.id,
            kind="expense",
            amount_cents=500,
            description="coffee",
            occurred_on=dt.date.today(),
        )
    )
    db.flush()
    again = client.get("/advisor/daily", headers=_h(token)).json()
    assert again["note"] == "You're well inside it."
    assert calls["n"] == 1
