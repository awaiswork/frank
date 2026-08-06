"""The AI feature gate — the billable routes must not reach the model while off.

Everything here runs in the shipped state (the ``_ai_off`` autouse fixture) except
where a test explicitly asks for ``ai_on``.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.features import AiDisabledError, ai_enabled
from app.models import User
from app.services import llm
from tests.conftest import create_account

PASSWORD = "supersecret"


def _register(client: TestClient, email: str) -> str:
    """Verified account + token. Registration alone no longer grants either."""
    return create_account(client, email, PASSWORD)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _explode(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Patch every model entry point to fail loudly if anything calls it."""
    calls = {"n": 0}

    async def boom(*_args: Any, **_kwargs: Any) -> Any:
        calls["n"] += 1
        raise AssertionError("the model must not be called while AI features are off")

    monkeypatch.setattr("app.services.llm.call_tool", boom)
    monkeypatch.setattr("app.services.advisor.stream_verdict", boom)
    monkeypatch.setattr("app.services.daily.generate", boom)
    return calls


def test_features_endpoint_reports_off(client: TestClient) -> None:
    body = client.get("/features").json()
    assert body == {
        "ai_enabled": False,
        "nl_capture": False,
        "advisor": False,
        "ai_daily_note": False,
    }


def test_features_endpoint_reports_on(client: TestClient, ai_on: None) -> None:
    body = client.get("/features").json()
    assert body["ai_enabled"] is True
    assert body["nl_capture"] and body["advisor"] and body["ai_daily_note"]


def test_flag_without_key_stays_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """A flag flipped on without a key must not count as enabled."""
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    assert ai_enabled() is False


def test_nl_parse_is_coming_soon(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _explode(monkeypatch)
    token = _register(client, "gate-nl@example.com")
    resp = client.post("/nl/parse", headers=_h(token), json={"text": "8,40 coffee"})
    assert resp.status_code == 503
    assert "coming soon" in resp.json()["detail"]
    assert calls["n"] == 0


def test_advisor_ask_is_coming_soon(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _explode(monkeypatch)
    token = _register(client, "gate-ask@example.com")
    resp = client.post("/advisor/ask", headers=_h(token), json={"question": "buy headphones?"})
    assert resp.status_code == 503
    assert "coming soon" in resp.json()["detail"]
    assert calls["n"] == 0
    # nothing was persisted, so history stays empty
    assert client.get("/advisor/history", headers=_h(token)).json() == []


def test_gated_routes_still_answer_401_first(client: TestClient) -> None:
    """Auth is checked before the feature gate — an anonymous call is a 401."""
    assert client.post("/nl/parse", json={"text": "hi"}).status_code == 401
    assert client.post("/advisor/ask", json={"question": "hi"}).status_code == 401


def test_daily_note_falls_back_without_calling_model(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The home screen keeps working: the deterministic note, at zero cost."""
    from app.services import daily

    calls = _explode(monkeypatch)
    token = _register(client, "gate-daily@example.com")
    user = db.scalar(select(User).where(User.email == "gate-daily@example.com"))
    assert user is not None
    user.monthly_income_cents = 320_000  # otherwise the mood is (correctly) 'unknown'
    db.flush()

    resp = client.get("/advisor/daily", headers=_h(token))
    assert resp.status_code == 200
    body = resp.json()
    assert calls["n"] == 0
    assert body["mood"] == "go"
    assert (body["headline"], body["note"]) == daily.fallback("go")
    assert body["streak"] == 1


def test_free_routes_are_untouched(client: TestClient) -> None:
    """Nothing that costs nothing got gated by accident."""
    token = _register(client, "gate-free@example.com")
    for path in ("/categories", "/transactions", "/budgets", "/goals", "/insights/summary"):
        assert client.get(path, headers=_h(token)).status_code == 200, path


def test_client_refuses_to_build_while_off() -> None:
    """The last line of defence: no Anthropic client exists at all."""
    llm._client = None
    with pytest.raises(AiDisabledError):
        llm.get_client()
