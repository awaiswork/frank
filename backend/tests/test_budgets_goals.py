"""API-level tests for categories, budgets, and goals (HTTP through TestClient)."""

from __future__ import annotations

from fastapi.testclient import TestClient

PASSWORD = "supersecret"


def _register(client: TestClient, email: str) -> str:
    resp = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201
    return str(resp.json()["access_token"])


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _expense_category_id(client: TestClient, token: str) -> str:
    cats = client.get("/categories", headers=_h(token)).json()
    return str(next(c["id"] for c in cats if c["kind"] == "expense"))


def test_categories_seeded_and_listed(client: TestClient) -> None:
    token = _register(client, "cats@example.com")
    cats = client.get("/categories", headers=_h(token)).json()
    assert len(cats) == 7
    names = {c["name"] for c in cats}
    assert "Groceries" in names and "Income" in names


def test_budget_upsert_and_pace(client: TestClient) -> None:
    token = _register(client, "budget@example.com")
    cat_id = _expense_category_id(client, token)

    created = client.put(
        f"/budgets/{cat_id}",
        headers=_h(token),
        params={"month": "2026-06"},
        json={"limit_cents": 20000},
    )
    assert created.status_code == 200
    assert created.json()["limit_cents"] == 20000
    assert created.json()["spent_cents"] == 0

    # upsert again -> updates, not duplicates
    updated = client.put(
        f"/budgets/{cat_id}",
        headers=_h(token),
        params={"month": "2026-06"},
        json={"limit_cents": 30000},
    )
    assert updated.json()["limit_cents"] == 30000

    listed = client.get("/budgets", headers=_h(token), params={"month": "2026-06"}).json()
    assert len(listed) == 1
    assert listed[0]["limit_cents"] == 30000


def test_budget_reflects_spending(client: TestClient) -> None:
    token = _register(client, "budget2@example.com")
    cat_id = _expense_category_id(client, token)
    client.put(
        f"/budgets/{cat_id}",
        headers=_h(token),
        params={"month": "2026-06"},
        json={"limit_cents": 10000},
    )
    client.post(
        "/transactions",
        headers=_h(token),
        json={
            "amount_cents": 2500,
            "description": "lunch",
            "occurred_on": "2026-06-09",
            "category_id": cat_id,
        },
    )
    row = client.get("/budgets", headers=_h(token), params={"month": "2026-06"}).json()[0]
    assert row["spent_cents"] == 2500
    assert row["spent_fraction"] == 0.25


def test_budget_unknown_category_404(client: TestClient) -> None:
    token = _register(client, "budget3@example.com")
    missing = "00000000-0000-0000-0000-000000000000"
    resp = client.put(f"/budgets/{missing}", headers=_h(token), json={"limit_cents": 1000})
    assert resp.status_code == 404


def test_goal_lifecycle_and_progress(client: TestClient) -> None:
    token = _register(client, "goal@example.com")
    created = client.post(
        "/goals", headers=_h(token), json={"name": "New laptop", "target_cents": 100000}
    )
    assert created.status_code == 201
    goal_id = created.json()["id"]
    assert created.json()["contributed_cents"] == 0
    assert created.json()["progress_fraction"] == 0.0

    contrib = client.post(
        f"/goals/{goal_id}/contributions", headers=_h(token), json={"amount_cents": 25000}
    )
    assert contrib.status_code == 201

    goals = client.get("/goals", headers=_h(token)).json()
    assert len(goals) == 1
    assert goals[0]["contributed_cents"] == 25000
    assert goals[0]["progress_fraction"] == 0.25

    # archive hides it from the default list
    patched = client.patch(f"/goals/{goal_id}", headers=_h(token), json={"archived": True})
    assert patched.json()["archived_at"] is not None
    assert client.get("/goals", headers=_h(token)).json() == []
    assert (
        len(client.get("/goals", headers=_h(token), params={"include_archived": True}).json()) == 1
    )


def test_goal_isolation(client: TestClient) -> None:
    token_a = _register(client, "ga@example.com")
    goal_id = client.post(
        "/goals", headers=_h(token_a), json={"name": "A", "target_cents": 100000}
    ).json()["id"]

    token_b = _register(client, "gb@example.com")
    assert (
        client.patch(f"/goals/{goal_id}", headers=_h(token_b), json={"name": "hax"}).status_code
        == 404
    )
    assert (
        client.post(
            f"/goals/{goal_id}/contributions", headers=_h(token_b), json={"amount_cents": 1}
        ).status_code
        == 404
    )


def test_insights_summary_shape(client: TestClient) -> None:
    token = _register(client, "insights@example.com")
    client.patch("/me", headers=_h(token), json={"monthly_income_cents": 300000})
    cat_id = _expense_category_id(client, token)
    client.post(
        "/transactions",
        headers=_h(token),
        json={
            "amount_cents": 4000,
            "description": "groceries",
            "occurred_on": "2026-06-07",
            "category_id": cat_id,
        },
    )
    summary = client.get("/insights/summary", headers=_h(token), params={"month": "2026-06"})
    assert summary.status_code == 200
    body = summary.json()
    assert body["month"] == "2026-06"
    assert body["safe_to_spend"]["income_cents"] == 300000
    assert body["safe_to_spend"]["spent_cents"] == 4000
    assert any(c["spent_cents"] == 4000 for c in body["spend_by_category"])
    assert "daily_burn" in body and "month_over_month" in body
