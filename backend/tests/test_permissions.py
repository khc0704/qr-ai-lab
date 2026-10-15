"""Three system roles: superadmin / admin / user. The backend decides, /me only reports."""

from __future__ import annotations

from app.core.config import get_settings
from app.core.permissions import PERMISSIONS, permissions_for
from app.db.session import get_sessionmaker
from app.services import users as users_svc
from tests.conftest import make_data_source, make_project


async def test_me_reports_permissions(client, superadmin, admin, user):
    sa = (await client.get("/api/v1/me", headers=superadmin)).json()
    ad = (await client.get("/api/v1/me", headers=admin)).json()
    us = (await client.get("/api/v1/me", headers=user)).json()
    assert sa["role"] == "superadmin" and set(sa["permissions"]) == set(PERMISSIONS)
    assert ad["role"] == "admin" and "jobs.control" in ad["permissions"] and "pool.manage" not in ad["permissions"]
    assert us["role"] == "user" and us["permissions"] == []
    assert sa["auth_mode"] == "local"
    assert permissions_for("nobody") == []
    assert (await client.get("/api/v1/auth/config")).json()["mode"] == "local"


async def test_admin_cannot_touch_resources_or_roles(client, admin, user):
    project = await make_project(client, admin, user)
    r = await client.patch(f"/api/v1/projects/{project['slug']}/quota", json={"gpu_limit": 0}, headers=admin)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "PERMISSION_DENIED"
    pool = (await client.get("/api/v1/admin/settings/resource-pool", headers=admin)).json()  # reading is fine
    r = await client.put("/api/v1/admin/settings/resource-pool", json=pool, headers=admin)
    assert r.status_code == 403
    me = (await client.get("/api/v1/me", headers=user)).json()
    r = await client.patch(f"/api/v1/users/{me['id']}", json={"role": "admin"}, headers=admin)
    assert r.status_code == 403
    r = await client.delete(f"/api/v1/projects/{project['slug']}", headers=admin)
    assert r.status_code == 403
    r = await client.post("/api/v1/admin/model-zoo/yolo11n/import", json={"source": "path", "path": "x"}, headers=admin)
    assert r.status_code == 403
    # but the day-to-day operations work
    assert (await client.get("/api/v1/users", headers=admin)).status_code == 200
    assert (await client.get("/api/v1/admin/queue", headers=admin)).status_code == 200


async def test_user_has_no_admin_operation(client, admin, user):
    r = await client.post("/api/v1/issues", json={"type": "question", "title": "Q", "body": "b"}, headers=user)
    issue_id = r.json()["id"]
    assert (await client.delete(f"/api/v1/issues/{issue_id}", headers=user)).status_code == 403
    assert (
        await client.post(f"/api/v1/issues/{issue_id}/close", json={"resolution_note": "x"}, headers=user)
    ).status_code == 403
    assert (await client.get("/api/v1/users", headers=user)).status_code == 403
    assert (await client.post("/api/v1/admin/jobs/1/restart", headers=user)).status_code == 403


async def test_admin_moderates_discussions(client, admin, user):
    r = await client.post("/api/v1/issues", json={"type": "bug", "title": "crash", "body": "boom"}, headers=user)
    issue_id = r.json()["id"]
    await client.post(f"/api/v1/issues/{issue_id}/comments", json={"body": "me too"}, headers=user)
    r = await client.delete(f"/api/v1/issues/{issue_id}", headers=admin)
    assert r.status_code == 200
    assert (await client.get(f"/api/v1/issues/{issue_id}", headers=user)).status_code == 404
    audit = (await client.get("/api/v1/admin/audit", headers=admin)).json()["items"]
    assert audit[0]["action"] == "issue.delete" and audit[0]["payload"]["title"] == "crash"


async def test_superadmin_role_changes_and_guards(client, superadmin, admin, user):
    users = {u["username"]: u for u in (await client.get("/api/v1/users", headers=superadmin)).json()["items"]}
    r = await client.patch(f"/api/v1/users/{users['user']['id']}", json={"role": "admin"}, headers=superadmin)
    assert r.status_code == 200 and r.json()["role"] == "admin"
    assert "jobs.control" in (await client.get("/api/v1/me", headers=user)).json()["permissions"]
    r = await client.patch(f"/api/v1/users/{users['admin']['id']}", json={"role": "superadmin"}, headers=superadmin)
    assert r.status_code == 200 and r.json()["role"] == "superadmin"
    # cannot demote / deactivate yourself
    r = await client.patch(f"/api/v1/users/{users['superadmin']['id']}", json={"role": "user"}, headers=superadmin)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "SELF_DEMOTE"
    r = await client.patch(f"/api/v1/users/{users['superadmin']['id']}", json={"is_active": False}, headers=superadmin)
    assert r.status_code == 400
    # the (now) second superadmin may demote the first one, but never the last one
    r = await client.patch(f"/api/v1/users/{users['superadmin']['id']}", json={"role": "admin"}, headers=admin)
    assert r.status_code == 200
    r = await client.patch(f"/api/v1/users/{users['admin']['id']}", json={"role": "user"}, headers=admin)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "SELF_DEMOTE"
    # a demoted token keeps working but with the new role (role is read from the users table on every request)
    assert (await client.get("/api/v1/me", headers=superadmin)).json()["role"] == "admin"
    r = await client.patch(f"/api/v1/users/{users['user']['id']}", json={"role": "user"}, headers=superadmin)
    assert r.status_code == 403


async def test_superadmin_deletes_project_with_history(client, superadmin, admin, user):
    project = await make_project(client, admin, user)
    slug = project["slug"]
    ds = await make_data_source(client, user, slug)
    r = await client.post(
        f"/api/v1/projects/{slug}/jobs",
        json={
            "kind": "train",
            "mode": "manual",
            "model_family": "tabular.linear",
            "name": "j",
            "input": {"kind": "data_source", "data_source_id": ds["id"], "spec": {"target": "yield_pct"}},
            "requested_cpu": 1,
        },
        headers=user,
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]
    r = await client.delete(f"/api/v1/projects/{slug}", headers=superadmin)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PROJECT_HAS_ACTIVE_JOBS"
    await client.post(f"/api/v1/jobs/{job_id}/cancel", headers=user)
    issue = (
        await client.post(
            "/api/v1/issues",
            json={"type": "question", "title": "about it", "body": "?", "project_slug": slug},
            headers=user,
        )
    ).json()
    r = await client.delete(f"/api/v1/projects/{slug}", headers=superadmin)
    assert r.status_code == 200, r.text
    assert (await client.get(f"/api/v1/projects/{slug}", headers=superadmin)).status_code == 404
    assert (await client.get(f"/api/v1/jobs/{job_id}", headers=superadmin)).status_code == 404
    got = (await client.get(f"/api/v1/issues/{issue['id']}", headers=user)).json()
    assert got["project_slug"] is None  # the thread survives, unlinked
    audit = (await client.get("/api/v1/admin/audit", headers=superadmin)).json()["items"]
    assert audit[0]["action"] == "project.delete" and audit[0]["payload"]["jobs"] == 1


async def test_admin_restarts_a_finished_job(client, admin, user):
    project = await make_project(client, admin, user)
    slug = project["slug"]
    ds = await make_data_source(client, user, slug)
    body = {
        "kind": "train",
        "mode": "auto",
        "name": "automl",
        "input": {"kind": "data_source", "data_source_id": ds["id"], "spec": {"target": "yield_pct"}},
        "requested_cpu": 1,
        "config": {"search": {"max_trials": 3}},
    }
    job = (await client.post(f"/api/v1/projects/{slug}/jobs", json=body, headers=user)).json()
    r = await client.post(f"/api/v1/admin/jobs/{job['id']}/restart", headers=admin)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_ACTIVE"
    await client.post(f"/api/v1/admin/jobs/{job['id']}/stop", json={"reason": "test stop"}, headers=admin)
    r = await client.post(f"/api/v1/admin/jobs/{job['id']}/restart", headers=admin)
    assert r.status_code == 202, r.text
    new = r.json()
    assert new["id"] != job["id"] and new["status"] == "queued" and new["mode"] == "auto"
    assert new["config"]["restarted_from"] == job["id"] and new["config"]["search"]["max_trials"] == 3
    assert new["config"]["search"]["candidates"]  # recomputed
    assert new["input"]["kind"] == "data_source" and new["data_source_id"] == ds["id"]


async def test_keycloak_role_mapping(db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "keycloak_role_map", ["qr-superadmin:superadmin", "qr-admin:admin"])
    monkeypatch.setattr(s, "keycloak_client_id", "qr-ai-lab")
    monkeypatch.setattr(s, "superadmin_usernames", ["boss"])
    base = {"sub": "11111111-2222-3333-4444-555555555555", "preferred_username": "alice", "email": "a@x", "name": "A"}
    async with get_sessionmaker()() as session:
        u = await users_svc.upsert_keycloak_user(session, {**base, "realm_access": {"roles": ["offline_access"]}})
        assert u.role == "user" and u.auth_provider == "keycloak" and u.username == "alice"
        # the UI promotes alice; a later login without a mapped role keeps that
        u.role = "admin"
        await session.commit()
        u = await users_svc.upsert_keycloak_user(session, {**base, "realm_access": {"roles": []}})
        assert u.role == "admin"
        # a mapped client role wins (most privileged match)
        u = await users_svc.upsert_keycloak_user(
            session,
            {**base, "resource_access": {"qr-ai-lab": {"roles": ["qr-admin", "qr-superadmin"]}}},
        )
        assert u.role == "superadmin"
        u = await users_svc.upsert_keycloak_user(session, {**base, "realm_access": {"roles": ["qr-admin"]}})
        assert u.role == "admin"
        # bootstrap username → superadmin regardless of roles
        b = await users_svc.upsert_keycloak_user(session, {"sub": "boss-sub", "preferred_username": "boss"})
        assert b.role == "superadmin"
        # an existing local account with the same username is adopted (not duplicated)
        a = await users_svc.upsert_keycloak_user(session, {"sub": "admin-sub", "preferred_username": "admin"})
        assert a.username == "admin" and a.auth_provider == "keycloak" and a.role == "admin" and a.password_hash is None
