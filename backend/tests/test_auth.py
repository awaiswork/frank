from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category, User

PASSWORD = "supersecret"


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_register_returns_token_and_seeds_categories(client: TestClient, db: Session) -> None:
    resp = client.post("/auth/register", json={"email": "Aino@Example.fi", "password": PASSWORD})
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    assert token

    # email is CITEXT: stored case-insensitively
    user = db.scalar(select(User).where(User.email == "aino@example.fi"))
    assert user is not None
    count = db.scalar(select(func.count()).select_from(Category).where(Category.user_id == user.id))
    assert count == 7  # 6 expense + 1 income

    me = client.get("/me", headers=_h(token))
    assert me.status_code == 200
    # EmailStr lowercases the domain but keeps the local part: "Aino@example.fi"
    assert me.json()["email"].lower() == "aino@example.fi"
    assert me.json()["currency"] == "EUR"


def test_duplicate_email_conflicts(client: TestClient) -> None:
    client.post("/auth/register", json={"email": "dup@example.com", "password": PASSWORD})
    again = client.post("/auth/register", json={"email": "DUP@example.com", "password": PASSWORD})
    assert again.status_code == 409


def test_login_and_wrong_password(client: TestClient) -> None:
    client.post("/auth/register", json={"email": "x@example.com", "password": PASSWORD})
    ok = client.post("/auth/login", json={"email": "x@example.com", "password": PASSWORD})
    assert ok.status_code == 200
    assert ok.json()["access_token"]
    bad = client.post("/auth/login", json={"email": "x@example.com", "password": "wrongpass1"})
    assert bad.status_code == 401


def test_me_requires_valid_token(client: TestClient) -> None:
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers=_h("not-a-jwt")).status_code == 401


def test_refresh_issues_new_access_token(client: TestClient) -> None:
    reg = client.post("/auth/register", json={"email": "r@example.com", "password": PASSWORD})
    assert reg.status_code == 201
    refreshed = client.post("/auth/refresh")  # refresh cookie is in the client jar
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]


def test_patch_me_updates_income(client: TestClient) -> None:
    token = client.post(
        "/auth/register", json={"email": "p@example.com", "password": PASSWORD}
    ).json()["access_token"]
    patched = client.patch("/me", headers=_h(token), json={"monthly_income_cents": 290000})
    assert patched.status_code == 200
    assert patched.json()["monthly_income_cents"] == 290000
