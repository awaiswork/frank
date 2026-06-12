"""NL parser tests with the Anthropic client mocked (technical-plan.md §11).

We patch ``app.services.llm.call_tool`` so no network/key is needed; the parser's
own validation + corrective-retry logic is what's under test.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

PASSWORD = "supersecret"


def _register(client: TestClient, email: str) -> str:
    resp = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201
    return str(resp.json()["access_token"])


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _fake_message(transactions: list[dict[str, Any]]) -> SimpleNamespace:
    """Mimic an Anthropic Message carrying a forced tool_use block."""
    block = SimpleNamespace(
        type="tool_use", name="record_transactions", input={"transactions": transactions}
    )
    return SimpleNamespace(
        content=[block],
        usage=SimpleNamespace(input_tokens=5, output_tokens=10),
        stop_reason="tool_use",
    )


def _patch_calls(monkeypatch: pytest.MonkeyPatch, *messages: Any) -> dict[str, int]:
    """Patch call_tool to return the given fake messages in order; count calls."""
    counter = {"n": 0}
    queue = list(messages)

    async def fake_call_tool(**_kwargs: Any) -> Any:
        counter["n"] += 1
        return queue.pop(0)

    monkeypatch.setattr("app.services.llm.call_tool", fake_call_tool)
    return counter


def test_parse_single(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    token = _register(client, "nl1@example.com")
    _patch_calls(
        monkeypatch,
        _fake_message(
            [
                {
                    "kind": "expense",
                    "amount_cents": 840,
                    "description": "coffee and croissant",
                    "merchant": "Cafe",
                    "category_name": "Eating out",
                    "occurred_on": "2026-06-09",
                    "confidence": 0.92,
                }
            ]
        ),
    )
    resp = client.post("/nl/parse", headers=_h(token), json={"text": "8,40 coffee and croissant"})
    assert resp.status_code == 200
    drafts = resp.json()
    assert len(drafts) == 1
    d = drafts[0]
    assert d["amount_cents"] == 840
    assert d["occurred_on"] == "2026-06-09"
    # "Eating out" is a seeded category -> resolved to a real category_id
    assert d["category_id"] is not None
    assert d["category_name"] == "Eating out"


def test_parse_multi(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    token = _register(client, "nl2@example.com")
    _patch_calls(
        monkeypatch,
        _fake_message(
            [
                {
                    "kind": "expense",
                    "amount_cents": 1250,
                    "description": "lunch",
                    "confidence": 0.9,
                },
                {"kind": "expense", "amount_cents": 300, "description": "bus", "confidence": 0.8},
            ]
        ),
    )
    resp = client.post("/nl/parse", headers=_h(token), json={"text": "lunch 12,50 and 3e bus"})
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_parse_defaults_date_to_today(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    token = _register(client, "nl3@example.com")
    _patch_calls(
        monkeypatch,
        _fake_message(
            [{"kind": "expense", "amount_cents": 500, "description": "x", "confidence": 0.7}]
        ),
    )
    resp = client.post("/nl/parse", headers=_h(token), json={"text": "5e snack"})
    assert resp.status_code == 200
    assert resp.json()[0]["occurred_on"]  # filled with today, never null


def test_parse_unknown_category_left_unresolved(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = _register(client, "nl4@example.com")
    _patch_calls(
        monkeypatch,
        _fake_message(
            [
                {
                    "kind": "expense",
                    "amount_cents": 999,
                    "description": "mystery",
                    "category_name": "Spaceship",
                    "confidence": 0.3,
                }
            ]
        ),
    )
    resp = client.post("/nl/parse", headers=_h(token), json={"text": "spent 9,99 on a spaceship"})
    assert resp.status_code == 200
    d = resp.json()[0]
    assert d["category_id"] is None
    assert d["category_name"] == "Spaceship"  # echoed back, not resolved


def test_malformed_then_retry(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    token = _register(client, "nl5@example.com")
    # first response has an invalid amount (0, fails gt=0) -> corrective retry -> valid
    counter = _patch_calls(
        monkeypatch,
        _fake_message(
            [{"kind": "expense", "amount_cents": 0, "description": "x", "confidence": 1}]
        ),
        _fake_message(
            [{"kind": "expense", "amount_cents": 1250, "description": "lunch", "confidence": 0.9}]
        ),
    )
    resp = client.post("/nl/parse", headers=_h(token), json={"text": "lunch 12,50"})
    assert resp.status_code == 200
    assert resp.json()[0]["amount_cents"] == 1250
    assert counter["n"] == 2  # exactly one corrective retry


def test_two_failures_return_422(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    token = _register(client, "nl6@example.com")
    counter = _patch_calls(
        monkeypatch,
        _fake_message([]),  # empty -> ParseError
        _fake_message([]),  # still empty after retry
    )
    resp = client.post("/nl/parse", headers=_h(token), json={"text": "???"})
    assert resp.status_code == 422
    assert counter["n"] == 2


def test_length_limit_rejected_without_calling_model(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = _register(client, "nl7@example.com")
    counter = _patch_calls(monkeypatch)  # no messages queued; must not be called
    resp = client.post("/nl/parse", headers=_h(token), json={"text": "x" * 501})
    assert resp.status_code == 422  # Pydantic max_length=500
    assert counter["n"] == 0  # the model was never called

    # and unauthenticated access is rejected
    assert client.post("/nl/parse", json={"text": "hi"}).status_code == 401
