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

from app.services import daily

PASSWORD = "supersecret"


def _register(client: TestClient, email: str) -> str:
    resp = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201
    return str(resp.json()["access_token"])


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_compute_mood() -> None:
    today = dt.date(2026, 6, 15)  # June has 30 days -> 15 days left
    # no income yet -> calm by default
    assert daily.compute_mood({"safe_to_spend_eur": None}, today) == "go"
    # already past safe-to-spend
    assert daily.compute_mood({"safe_to_spend_eur": -10.0}, today) == "over"
    # a budget running ahead of pace -> ease off
    hot: dict[str, Any] = {
        "safe_to_spend_eur": 500.0,
        "daily_burn_eur": 0,
        "budgets": [{"on_track": False}],
    }
    assert daily.compute_mood(hot, today) == "wait"
    # current burn would blow the remaining days -> ease off
    burn_hot: dict[str, Any] = {"safe_to_spend_eur": 100.0, "daily_burn_eur": 50, "budgets": []}
    assert daily.compute_mood(burn_hot, today) == "wait"
    # comfortably on track
    calm: dict[str, Any] = {
        "safe_to_spend_eur": 1000.0,
        "daily_burn_eur": 5,
        "budgets": [{"on_track": True}],
    }
    assert daily.compute_mood(calm, today) == "go"


def test_daily_generates_once_then_caches_with_streak(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = _register(client, "daily@example.com")
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
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = _register(client, "dailyfail@example.com")

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
