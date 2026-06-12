from __future__ import annotations

from fastapi.testclient import TestClient

PASSWORD = "supersecret"


def _register(client: TestClient, email: str) -> str:
    resp = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201
    return str(resp.json()["access_token"])


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_create_list_update_delete(client: TestClient) -> None:
    h = _h(_register(client, "tx@example.com"))

    created = client.post(
        "/transactions",
        headers=h,
        json={
            "amount_cents": 1250,
            "description": "Lunch at Hesburger",
            "merchant": "Hesburger",
            "occurred_on": "2026-06-10",
        },
    )
    assert created.status_code == 201
    tx = created.json()
    assert tx["amount_cents"] == 1250
    assert tx["source"] == "manual"
    tx_id = tx["id"]

    listed = client.get("/transactions?month=2026-06", headers=h)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    assert client.get("/transactions?month=2026-05", headers=h).json() == []

    patched = client.patch(f"/transactions/{tx_id}", headers=h, json={"amount_cents": 1300})
    assert patched.status_code == 200
    assert patched.json()["amount_cents"] == 1300

    assert client.delete(f"/transactions/{tx_id}", headers=h).status_code == 204
    assert client.get("/transactions?month=2026-06", headers=h).json() == []


def test_amount_must_be_positive(client: TestClient) -> None:
    resp = client.post(
        "/transactions",
        headers=_h(_register(client, "neg@example.com")),
        json={"amount_cents": 0, "description": "bad", "occurred_on": "2026-06-10"},
    )
    assert resp.status_code == 422


def test_search_filters_by_description_and_merchant(client: TestClient) -> None:
    h = _h(_register(client, "search@example.com"))
    client.post(
        "/transactions",
        headers=h,
        json={
            "amount_cents": 500,
            "description": "Coffee",
            "merchant": "Cafe",
            "occurred_on": "2026-06-01",
        },
    )
    client.post(
        "/transactions",
        headers=h,
        json={
            "amount_cents": 900,
            "description": "Train",
            "merchant": "VR",
            "occurred_on": "2026-06-02",
        },
    )
    res = client.get("/transactions?q=coffee", headers=h)
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["description"] == "Coffee"


def test_unknown_category_rejected(client: TestClient) -> None:
    resp = client.post(
        "/transactions",
        headers=_h(_register(client, "cat@example.com")),
        json={
            "amount_cents": 500,
            "description": "x",
            "occurred_on": "2026-06-01",
            "category_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert resp.status_code == 422
