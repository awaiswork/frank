"""Cross-user isolation — technical-plan.md §10 requires a test proving one user
cannot reach another user's rows. Foreign rows must look non-existent (404), never
forbidden (403)."""

from __future__ import annotations

from fastapi.testclient import TestClient

PASSWORD = "supersecret"


def _register(client: TestClient, email: str) -> str:
    resp = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201
    return str(resp.json()["access_token"])


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_user_cannot_reach_another_users_transaction(client: TestClient) -> None:
    alice = _register(client, "alice@example.com")
    bob = _register(client, "bob@example.com")

    created = client.post(
        "/transactions",
        headers=_h(alice),
        json={"amount_cents": 4200, "description": "Alice only", "occurred_on": "2026-06-05"},
    )
    assert created.status_code == 201
    tx_id = created.json()["id"]

    # Bob's list never includes Alice's rows
    assert client.get("/transactions", headers=_h(bob)).json() == []

    # Bob is told it does not exist (404), not that it's forbidden (403)
    assert (
        client.patch(
            f"/transactions/{tx_id}", headers=_h(bob), json={"amount_cents": 1}
        ).status_code
        == 404
    )
    assert client.delete(f"/transactions/{tx_id}", headers=_h(bob)).status_code == 404

    # Alice still owns it, unmodified
    alice_list = client.get("/transactions", headers=_h(alice)).json()
    assert len(alice_list) == 1
    assert alice_list[0]["amount_cents"] == 4200
