"""Three system roles: superadmin / admin / user. The backend decides, /me only reports."""

from __future__ import annotations

import pytest

from app.core.config import Settings, get_settings
from app.core.permissions import PERMISSIONS, permissions_for
from app.db.session import get_sessionmaker
from app.services import users as users_svc
from tests.conftest import login, make_data_source, make_project


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
    r = await client.post("/api/v1/admin/model-zoo/yolov8n/import", json={"source": "path", "path": "x"}, headers=admin)
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


async def test_closed_discussion_only_takes_admin_replies(client, admin, user):
    r = await client.post("/api/v1/issues", json={"type": "question", "title": "how", "body": "?"}, headers=user)
    issue_id = r.json()["id"]
    assert (
        await client.post(f"/api/v1/issues/{issue_id}/comments", json={"body": "bump"}, headers=user)
    ).status_code == 201
    await client.post(f"/api/v1/issues/{issue_id}/close", json={"resolution_note": "answered"}, headers=admin)
    r = await client.post(f"/api/v1/issues/{issue_id}/comments", json={"body": "one more"}, headers=user)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ISSUE_CLOSED"
    assert (
        await client.post(f"/api/v1/issues/{issue_id}/comments", json={"body": "follow-up"}, headers=admin)
    ).status_code == 201
    await client.post(f"/api/v1/issues/{issue_id}/reopen", headers=admin)
    assert (
        await client.post(f"/api/v1/issues/{issue_id}/comments", json={"body": "thanks"}, headers=user)
    ).status_code == 201


async def test_superadmin_role_changes_and_guards(client, superadmin, admin, user):
    users = {u["username"]: u for u in (await client.get("/api/v1/users", headers=superadmin)).json()["items"]}
    r = await client.patch(f"/api/v1/users/{users['user']['id']}", json={"role": "admin"}, headers=superadmin)
    assert r.status_code == 200 and r.json()["role"] == "admin"
    assert "jobs.control" in (await client.get("/api/v1/me", headers=user)).json()["permissions"]
    # superadmin is exactly one account fixed by SUPERADMIN_USERNAME: the UI grants at most admin …
    r = await client.patch(f"/api/v1/users/{users['admin']['id']}", json={"role": "superadmin"}, headers=superadmin)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "SUPERADMIN_FIXED"
    assert "SUPERADMIN_USERNAME" in r.json()["detail"]["message"]
    assert (await client.get("/api/v1/me", headers=admin)).json()["role"] == "admin"
    # … and that account can neither be demoted nor deactivated (not even by itself)
    r = await client.patch(f"/api/v1/users/{users['superadmin']['id']}", json={"role": "admin"}, headers=superadmin)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "SUPERADMIN_FIXED"
    r = await client.patch(f"/api/v1/users/{users['superadmin']['id']}", json={"is_active": False}, headers=superadmin)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "SUPERADMIN_FIXED"
    assert (await client.get("/api/v1/me", headers=superadmin)).json()["role"] == "superadmin"
    # the display name is still editable; activation of everyone else too
    r = await client.patch(
        f"/api/v1/users/{users['superadmin']['id']}", json={"display_name": "Boss"}, headers=superadmin
    )
    assert r.status_code == 200 and r.json()["display_name"] == "Boss" and r.json()["role"] == "superadmin"
    # a demoted token keeps working but with the new role (role is read from the users table on every request)
    r = await client.patch(f"/api/v1/users/{users['user']['id']}", json={"role": "user"}, headers=superadmin)
    assert r.status_code == 200 and r.json()["role"] == "user"
    assert (await client.get("/api/v1/me", headers=user)).json()["permissions"] == []
    r = await client.patch(f"/api/v1/users/{users['admin']['id']}", json={"role": "user"}, headers=user)
    assert r.status_code == 403


async def test_stray_superadmin_row_is_demoted_on_login(client, db):
    """A row that carries role superadmin without being SUPERADMIN_USERNAME (hand-edited DB, old bootstrap list)
    becomes admin the moment it logs in."""
    async with get_sessionmaker()() as session:
        await users_svc.create_local_user(
            session, username="impostor", password="impostorpw", email="i@x", display_name=None, role="superadmin"
        )
    headers = await login(client, "impostor", "impostorpw")
    me = (await client.get("/api/v1/me", headers=headers)).json()
    assert me["role"] == "admin" and "users.manage" not in me["permissions"]
    boss = await login(client, "superadmin", "superpw")
    assert (await client.get("/api/v1/me", headers=boss)).json()["role"] == "superadmin"


async def test_ensure_single_superadmin_follows_the_configured_name(db, monkeypatch):
    s = get_settings()
    async with get_sessionmaker()() as session:
        await users_svc.create_local_user(
            session, username="stray", password="straypw", email="s@x", display_name=None, role="superadmin"
        )
    monkeypatch.setattr(s, "superadmin_username", "admin")  # SUPERADMIN_USERNAME changed between restarts
    async with get_sessionmaker()() as session:
        assert await users_svc.ensure_single_superadmin(session) == {
            "promoted": ["admin"],
            "demoted": ["superadmin", "stray"],
        }
        assert await users_svc.ensure_single_superadmin(session) == {"promoted": [], "demoted": []}  # idempotent
        roles = {u.username: u.role for u in (await users_svc.list_users(session))[0]}
        assert roles == {"superadmin": "admin", "admin": "superadmin", "user": "user", "stray": "admin"}
    monkeypatch.setattr(s, "superadmin_username", "")  # nobody
    async with get_sessionmaker()() as session:
        assert await users_svc.ensure_single_superadmin(session) == {"promoted": [], "demoted": ["admin"]}


def test_superadmin_username_setting_and_legacy_list():
    s = Settings(_env_file=None)
    assert s.superadmin_username == "superadmin" and s.keycloak_role_map == [] and s.role_map == {}
    assert Settings(_env_file=None, superadmin_username=" alice ").superadmin_username == "alice"
    assert Settings(_env_file=None, superadmin_username="").superadmin_username == ""
    with pytest.warns(DeprecationWarning, match="SUPERADMIN_USERNAMES"):
        legacy = Settings(_env_file=None, superadmin_usernames="alice, bob")
    assert legacy.superadmin_username == "alice" and legacy.superadmin_usernames == ["alice", "bob"]
    with pytest.warns(DeprecationWarning):  # the new variable wins when both are set
        both = Settings(_env_file=None, superadmin_username="carol", superadmin_usernames="alice")
    assert both.superadmin_username == "carol"


def test_cli_set_role_refuses_superadmin():
    from app.cli import main

    with pytest.raises(SystemExit) as e:
        main(["set-role", "--username", "admin", "--role", "superadmin"])
    assert e.value.code == 2  # argparse: invalid choice
    with pytest.raises(SystemExit) as e:
        main(["create-user", "--username", "x", "--password", "p", "--email", "e", "--role", "superadmin"])
    assert e.value.code == 2


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


async def test_keycloak_supplies_identity_only(db):
    """Default settings: no role map. Realm / client roles in the token never touch users.role; the first login is a
    plain user, /admin/users decides afterwards, and SUPERADMIN_USERNAME is the only superadmin."""
    s = get_settings()
    assert s.role_map == {} and s.superadmin_username == "superadmin"
    alice = {
        "sub": "11111111-2222-3333-4444-555555555555",
        "preferred_username": "alice",
        "email": "a@x",
        "name": "A",
        "realm_access": {"roles": ["superadmin", "admin"]},
        "resource_access": {"qr-ai-lab": {"roles": ["superadmin"]}},
    }
    async with get_sessionmaker()() as session:
        u = await users_svc.upsert_keycloak_user(session, alice)
        assert u.role == "user" and u.auth_provider == "keycloak" and u.permissions == []
        u.role = "admin"  # the UI's decision sticks across logins whatever the token carries
        await session.commit()
        assert (await users_svc.upsert_keycloak_user(session, alice)).role == "admin"
        u.role = "superadmin"  # a stray superadmin row is demoted at login
        await session.commit()
        assert (await users_svc.upsert_keycloak_user(session, alice)).role == "admin"
        # the configured name is superadmin whatever the token says; the same-named local row is adopted, not copied
        boss = await users_svc.upsert_keycloak_user(session, {"sub": "boss-sub", "preferred_username": "superadmin"})
        assert boss.role == "superadmin" and boss.auth_provider == "keycloak" and boss.password_hash is None
        assert len((await users_svc.list_users(session, q="superadmin"))[0]) == 1


async def test_keycloak_role_map_is_opt_in(db, monkeypatch):
    """KEYCLOAK_ROLE_MAP set explicitly (the future opt-in): mapped roles override users.role, capped at admin."""
    s = get_settings()
    monkeypatch.setattr(s, "keycloak_role_map", ["qr-superadmin:superadmin", "qr-admin:admin"])
    monkeypatch.setattr(s, "keycloak_client_id", "qr-ai-lab")
    monkeypatch.setattr(s, "superadmin_username", "boss")
    base = {"sub": "11111111-2222-3333-4444-555555555555", "preferred_username": "alice", "email": "a@x", "name": "A"}
    async with get_sessionmaker()() as session:
        u = await users_svc.upsert_keycloak_user(session, {**base, "realm_access": {"roles": ["offline_access"]}})
        assert u.role == "user" and u.auth_provider == "keycloak" and u.username == "alice"
        # the UI promotes alice; a later login without a mapped role keeps that
        u.role = "admin"
        await session.commit()
        u = await users_svc.upsert_keycloak_user(session, {**base, "realm_access": {"roles": []}})
        assert u.role == "admin"
        u.role = "user"
        await session.commit()
        # a mapped client role wins (most privileged match) — but superadmin is never granted this way
        u = await users_svc.upsert_keycloak_user(
            session,
            {**base, "resource_access": {"qr-ai-lab": {"roles": ["qr-admin", "qr-superadmin"]}}},
        )
        assert u.role == "admin"
        u = await users_svc.upsert_keycloak_user(session, {**base, "realm_access": {"roles": ["qr-admin"]}})
        assert u.role == "admin"
        # the configured username → superadmin regardless of roles; the seeded local `superadmin` is not it any more
        b = await users_svc.upsert_keycloak_user(session, {"sub": "boss-sub", "preferred_username": "boss"})
        assert b.role == "superadmin"
        old = await users_svc.get_by_username(session, "superadmin")
        assert old is not None and old.role == "superadmin"  # untouched until it logs in or the app restarts
        assert await users_svc.ensure_single_superadmin(session) == {"promoted": [], "demoted": ["superadmin"]}
        # an existing local account with the same username is adopted (not duplicated)
        a = await users_svc.upsert_keycloak_user(session, {"sub": "admin-sub", "preferred_username": "admin"})
        # … but the local row's privileges do not carry over: the name alone proves nothing
        assert a.username == "admin" and a.auth_provider == "keycloak" and a.role == "user" and a.password_hash is None
