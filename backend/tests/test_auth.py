from __future__ import annotations

from tests.conftest import login


async def test_login_and_me(client, admin, user):
    r = await client.get("/api/v1/me", headers=admin)
    assert r.status_code == 200 and r.json()["role"] == "admin" and r.json()["username"] == "admin"
    r = await client.get("/api/v1/me", headers=user)
    assert r.json()["role"] == "user"


async def test_bad_password(client, db):
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "BAD_CREDENTIALS"


async def test_missing_token(client, db):
    r = await client.get("/api/v1/me")
    assert r.status_code == 401


async def test_user_cannot_use_admin_api(client, user):
    r = await client.get("/api/v1/admin/overview", headers=user)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ADMIN_ONLY"


async def test_disabled_user_rejected(client, admin, user, superadmin):
    me = (await client.get("/api/v1/me", headers=user)).json()
    r = await client.patch(f"/api/v1/users/{me['id']}", json={"is_active": False}, headers=superadmin)
    assert r.status_code == 200 and r.json()["is_active"] is False
    r = await client.get("/api/v1/me", headers=user)
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/login", json={"username": "user", "password": "userpw"})
    assert r.status_code == 401


async def test_catalog_requires_auth(client, user):
    assert (await client.get("/api/v1/catalog")).status_code == 401
    cat = (await client.get("/api/v1/catalog", headers=user)).json()
    assert "tabular.xgboost" in cat["families"] and "source" not in str(cat["families"]["vision.yolo"]["weights"])


async def test_other_user_login_helper(client, other):
    assert (await client.get("/api/v1/me", headers=other)).json()["username"] == "other"
    assert await login(client, "other", "otherpw")
