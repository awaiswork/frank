"""Advisor tests — context builder (shape + token budget) and the SSE/history flow.

The model is mocked (no key/network): we patch ``advisor.stream_verdict`` to emit a
canned verdict, and assert the SSE output, persistence, history, and follow-up.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Budget, Category, SavingsGoal, Transaction, User
from app.services import advisor

PASSWORD = "supersecret"
TODAY = dt.date(2026, 6, 12)


def _register(client: TestClient, email: str) -> str:
    resp = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201
    return str(resp.json()["access_token"])


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_build_context_shape_and_token_budget(client: TestClient, db: Session) -> None:
    _register(client, "ctx@example.com")
    user = db.scalar(select(User).where(User.email == "ctx@example.com"))
    assert user is not None
    user.monthly_income_cents = 300000
    groceries = db.scalar(
        select(Category).where(Category.user_id == user.id, Category.name == "Groceries")
    )
    assert groceries is not None
    db.add_all(
        [
            Transaction(
                user_id=user.id,
                category_id=groceries.id,
                kind="expense",
                amount_cents=4200,
                description="food",
                occurred_on=TODAY,
            ),
            Budget(
                user_id=user.id,
                category_id=groceries.id,
                month=TODAY.replace(day=1),
                limit_cents=30000,
            ),
            SavingsGoal(user_id=user.id, name="Lisbon", target_cents=100000),
        ]
    )
    db.flush()

    ctx = advisor.build_context(db, user, TODAY)
    assert set(ctx) >= {
        "today",
        "currency",
        "safe_to_spend_eur",
        "budgets",
        "goals",
        "daily_burn_eur",
        "recent_decisions",
    }
    assert ctx["budgets"][0]["category"] == "Groceries"
    assert ctx["goals"][0]["name"] == "Lisbon"
    # token budget: well under ~1500 tokens — use a generous char proxy
    assert len(json.dumps(ctx)) < 4000


def _fake_stream(verdict: advisor.Verdict) -> Any:
    async def gen(
        _question: str, _amount: int | None, _context: dict[str, Any]
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        yield ("delta", {"partial": '{"verdict":"' + verdict.verdict + '",'})
        yield ("delta", {"partial": '"reasoning":"' + verdict.reasoning})
        yield ("final", {"verdict": verdict, "input_tokens": 820, "output_tokens": 95})

    return gen


def test_ask_streams_persists_and_history(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = _register(client, "ask@example.com")
    verdict = advisor.Verdict(
        verdict="go",
        headline="Go for it",
        evidence=[advisor.Evidence(label="Safe to spend", value="120,00 €")],
        reasoning="You have room this month.",
    )
    monkeypatch.setattr("app.services.advisor.stream_verdict", _fake_stream(verdict))

    resp = client.post(
        "/advisor/ask",
        headers=_h(token),
        json={"question": "should I buy 240e headphones?", "amount_cents": 24000},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "event: delta" in body
    assert "event: verdict" in body
    assert "event: done" in body
    assert advisor.DISCLAIMER in body

    hist = client.get("/advisor/history", headers=_h(token)).json()
    assert len(hist) == 1
    assert hist[0]["verdict"] == "go"
    assert hist[0]["evidence"][0]["label"] == "Safe to spend"
    assert hist[0]["user_followed"] is None

    advice_id = hist[0]["id"]
    patched = client.patch(f"/advisor/{advice_id}", headers=_h(token), json={"user_followed": True})
    assert patched.status_code == 200
    assert patched.json()["user_followed"] is True


def test_ask_handles_model_failure(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    token = _register(client, "fail@example.com")

    async def boom(
        _q: str, _a: int | None, _c: dict[str, Any]
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        raise advisor.AdvisorError("nope")
        yield ("final", {})  # pragma: no cover - unreachable, makes this an async generator

    monkeypatch.setattr("app.services.advisor.stream_verdict", boom)
    resp = client.post("/advisor/ask", headers=_h(token), json={"question": "hi"})
    assert resp.status_code == 200
    assert "event: error" in resp.text
    # nothing persisted on failure
    assert client.get("/advisor/history", headers=_h(token)).json() == []


def test_advice_isolation_and_limits(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    verdict = advisor.Verdict(
        verdict="skip", headline="Maybe later", evidence=[], reasoning="Tight."
    )
    monkeypatch.setattr("app.services.advisor.stream_verdict", _fake_stream(verdict))

    token_a = _register(client, "advA@example.com")
    client.post("/advisor/ask", headers=_h(token_a), json={"question": "buy a thing?"})
    advice_id = client.get("/advisor/history", headers=_h(token_a)).json()[0]["id"]

    token_b = _register(client, "advB@example.com")
    assert (
        client.patch(
            f"/advisor/{advice_id}", headers=_h(token_b), json={"user_followed": True}
        ).status_code
        == 404
    )
    assert client.get("/advisor/history", headers=_h(token_b)).json() == []

    # input length limit (§7a) and auth
    too_long = client.post("/advisor/ask", headers=_h(token_a), json={"question": "x" * 301})
    assert too_long.status_code == 422
    assert client.post("/advisor/ask", json={"question": "hi"}).status_code == 401
