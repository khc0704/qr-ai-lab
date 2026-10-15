from __future__ import annotations

from tests.conftest import APPROVE, REQUEST


async def test_request_lifecycle_to_project(client, admin, user, other):
    r = await client.post("/api/v1/project-requests", json=REQUEST, headers=user)
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "submitted" and req["applicant"]["username"] == "user"

    # visibility
    assert len((await client.get("/api/v1/project-requests", headers=user)).json()["items"]) == 1
    assert len((await client.get("/api/v1/project-requests", headers=other)).json()["items"]) == 0
    assert (await client.get(f"/api/v1/project-requests/{req['id']}", headers=other)).status_code == 403
    assert (await client.get("/api/v1/project-requests?status=pending", headers=admin)).json()["total"] == 1

    # review round trip
    r = await client.post(f"/api/v1/project-requests/{req['id']}/review", headers=admin)
    assert r.json()["status"] == "in_review" and r.json()["reviewer"]["username"] == "admin"
    await client.post(f"/api/v1/project-requests/{req['id']}/comments", json={"body": "請補充目標欄位"}, headers=admin)
    await client.post(f"/api/v1/project-requests/{req['id']}/comments", json={"body": "已補上"}, headers=user)
    comments = (await client.get(f"/api/v1/project-requests/{req['id']}/comments", headers=user)).json()
    assert [c["kind"] for c in comments] == ["system", "comment", "comment"]
    assert (await client.get(f"/api/v1/project-requests/{req['id']}", headers=user)).json()["comment_count"] == 2

    # non-admin cannot approve
    assert (
        await client.post(f"/api/v1/project-requests/{req['id']}/approve", json=APPROVE, headers=user)
    ).status_code == 403

    # approve creates the project, adds applicant as owner and the listed member
    r = await client.post(f"/api/v1/project-requests/{req['id']}/approve", json=APPROVE, headers=admin)
    assert r.status_code == 201, r.text
    project = r.json()
    assert project["slug"] == "yield-forecast" and project["owner"]["username"] == "user"
    roles = {m["user"]["username"]: m["role"] for m in project["members"]}
    assert roles == {"user": "owner", "other": "member"}
    assert (await client.get(f"/api/v1/project-requests/{req['id']}", headers=user)).json()["status"] == "approved"
    assert (await client.get(f"/api/v1/project-requests/{req['id']}", headers=user)).json()[
        "project_slug"
    ] == "yield-forecast"

    # both members see the project; nobody else does
    assert [p["slug"] for p in (await client.get("/api/v1/projects", headers=other)).json()] == ["yield-forecast"]
    assert (await client.get("/api/v1/projects/yield-forecast", headers=user)).json()["usage"]["running_jobs"] == 0
    audit = (await client.get("/api/v1/admin/audit", headers=admin)).json()["items"]
    assert any(a["action"] == "project_request.approve" for a in audit)

    # slug collision
    r2 = (await client.post("/api/v1/project-requests", json=REQUEST, headers=user)).json()
    assert (
        await client.post(f"/api/v1/project-requests/{r2['id']}/approve", json=APPROVE, headers=admin)
    ).status_code == 409


async def test_reject_then_resubmit_and_withdraw(client, admin, user):
    req = (await client.post("/api/v1/project-requests", json=REQUEST, headers=user)).json()
    r = await client.post(
        f"/api/v1/project-requests/{req['id']}/reject", json={"review_note": "資料尚未標註"}, headers=admin
    )
    assert r.json()["status"] == "rejected" and r.json()["review_note"] == "資料尚未標註"
    r = await client.patch(
        f"/api/v1/project-requests/{req['id']}", json={"data_description": "已標註 3k 筆"}, headers=user
    )
    assert r.json()["status"] == "submitted" and r.json()["review_note"] is None
    r = await client.post(f"/api/v1/project-requests/{req['id']}/withdraw", headers=user)
    assert r.json()["status"] == "withdrawn"
    assert (await client.post(f"/api/v1/project-requests/{req['id']}/review", headers=admin)).status_code == 409


async def test_gpu_request_over_pool_rejected(client, user):
    r = await client.post("/api/v1/project-requests", json={**REQUEST, "requested_gpu": 9}, headers=user)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "GPU_EXCEEDS_POOL"


async def test_issues_board(client, admin, user):
    r = await client.post(
        "/api/v1/issues", json={"type": "question", "title": "AutoML 預算怎麼估？", "body": "10 萬列夠嗎"}, headers=user
    )
    assert r.status_code == 201
    iid = r.json()["id"]
    await client.post(f"/api/v1/issues/{iid}/comments", json={"body": "先跑 20 分鐘"}, headers=admin)
    assert (await client.get("/api/v1/issues?status=open", headers=user)).json()["items"][0]["comment_count"] == 1
    assert (
        await client.post(f"/api/v1/issues/{iid}/close", json={"resolution_note": "已回答"}, headers=user)
    ).status_code == 403
    r = await client.post(f"/api/v1/issues/{iid}/close", json={"resolution_note": "已回答"}, headers=admin)
    assert r.json()["status"] == "closed"
    assert (await client.post(f"/api/v1/issues/{iid}/reopen", headers=user)).json()["status"] == "open"
