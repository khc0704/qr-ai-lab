from __future__ import annotations

from tests.conftest import APPROVE, REQUEST, make_project


async def test_application_lifecycle_on_the_project(client, admin, user, other):
    r = await client.post("/api/v1/projects", json=REQUEST, headers=user)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["status"] == "pending" and p["slug"] == "yield-forecast" and p["owner"]["username"] == "user"
    assert p["application"]["purpose"] == REQUEST["purpose"] and p["application"]["requested_cpu"] == 4
    assert p["gpu_limit"] == 0 and [m["role"] for m in p["members"]] == ["owner"]

    # visibility: the applicant sees it in the list, strangers do not, admins filter by status
    assert [x["slug"] for x in (await client.get("/api/v1/projects", headers=user)).json()] == ["yield-forecast"]
    assert (await client.get("/api/v1/projects", headers=other)).json() == []
    assert (await client.get("/api/v1/projects/yield-forecast", headers=other)).status_code == 404
    assert len((await client.get("/api/v1/projects?status=pending", headers=admin)).json()) == 1
    assert (await client.get("/api/v1/projects?status=nope", headers=admin)).status_code == 400

    # nothing runs before approval
    r = await client.post(
        "/api/v1/projects/yield-forecast/data-sources",
        json={"kind": "url", "name": "x", "url": "https://example.com/a.csv", "format": "csv"},
        headers=user,
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PROJECT_NOT_ACTIVE"

    # review round trip with comments on the application
    r = await client.post("/api/v1/projects/yield-forecast/review", headers=admin)
    assert r.json()["status"] == "in_review" and r.json()["application"]["reviewer"]["username"] == "admin"
    await client.post(
        "/api/v1/projects/yield-forecast/application/comments", json={"body": "請補充目標欄位"}, headers=admin
    )
    await client.post("/api/v1/projects/yield-forecast/application/comments", json={"body": "已補上"}, headers=user)
    comments = (await client.get("/api/v1/projects/yield-forecast/application/comments", headers=user)).json()
    assert [c["kind"] for c in comments] == ["system", "system", "comment", "comment"]
    assert (await client.get("/api/v1/projects/yield-forecast", headers=user)).json()["application"][
        "comment_count"
    ] == 2

    # non-admin cannot approve
    assert (await client.post("/api/v1/projects/yield-forecast/approve", json=APPROVE, headers=user)).status_code == 403

    # approve: quota, members from the application, applicant stays owner
    r = await client.post("/api/v1/projects/yield-forecast/approve", json=APPROVE, headers=admin)
    assert r.status_code == 200, r.text
    project = r.json()
    assert project["status"] == "active" and project["gpu_limit"] == 1 and project["approved_at"]
    roles = {m["user"]["username"]: m["role"] for m in project["members"]}
    assert roles == {"user": "owner", "other": "member"}
    assert project["application"]["reviewed_at"]

    # both members see the project; the audit trail has the approval
    assert [x["slug"] for x in (await client.get("/api/v1/projects", headers=other)).json()] == ["yield-forecast"]
    assert (await client.get("/api/v1/projects/yield-forecast", headers=user)).json()["usage"]["running_jobs"] == 0
    audit = (await client.get("/api/v1/admin/audit", headers=admin)).json()["items"]
    assert {"project.apply", "project.approve"} <= {a["action"] for a in audit}

    # the same slug again gets a suffix instead of a collision
    r2 = (await client.post("/api/v1/projects", json=REQUEST, headers=user)).json()
    assert r2["slug"] == "yield-forecast-2" and r2["status"] == "pending"
    # an approved project cannot be re-approved or withdrawn
    assert (
        await client.post("/api/v1/projects/yield-forecast/approve", json=APPROVE, headers=admin)
    ).status_code == 409
    assert (await client.post("/api/v1/projects/yield-forecast/withdraw", headers=user)).status_code == 409


async def test_reject_then_resubmit_and_withdraw(client, admin, user):
    p = (await client.post("/api/v1/projects", json=REQUEST, headers=user)).json()
    slug = p["slug"]
    r = await client.post(f"/api/v1/projects/{slug}/reject", json={"review_note": "資料尚未標註"}, headers=admin)
    assert r.json()["status"] == "rejected" and r.json()["application"]["review_note"] == "資料尚未標註"
    assert (await client.get("/api/v1/projects?status=rejected", headers=user)).json()[0]["slug"] == slug
    r = await client.patch(
        f"/api/v1/projects/{slug}/application",
        json={"data_description": "已標註 3k 筆", "title": "良率預測 v2"},
        headers=user,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending" and r.json()["application"]["review_note"] is None
    assert r.json()["name"] == "良率預測 v2" and r.json()["application"]["data_description"] == "已標註 3k 筆"
    assert (await client.post(f"/api/v1/projects/{slug}/withdraw", headers=user)).status_code == 200
    assert (await client.get(f"/api/v1/projects/{slug}", headers=user)).status_code == 404
    assert (await client.get("/api/v1/projects", headers=admin)).json() == []


async def test_complete_and_reopen(client, admin, user):
    project = await make_project(client, admin, user)
    slug = project["slug"]
    r = await client.post(f"/api/v1/projects/{slug}/complete", headers=user)
    assert r.status_code == 200 and r.json()["status"] == "completed" and r.json()["completed_at"]
    r = await client.post(
        f"/api/v1/projects/{slug}/data-sources",
        json={"kind": "url", "name": "x", "url": "https://example.com/a.csv", "format": "csv"},
        headers=user,
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PROJECT_NOT_ACTIVE"
    assert (await client.get(f"/api/v1/projects/{slug}", headers=user)).status_code == 200  # still readable
    assert [x["slug"] for x in (await client.get("/api/v1/projects?status=completed", headers=user)).json()] == [slug]
    r = await client.post(f"/api/v1/projects/{slug}/reopen", headers=admin)
    assert r.json()["status"] == "active" and r.json()["completed_at"] is None


async def test_gpu_request_over_pool_rejected(client, user):
    r = await client.post("/api/v1/projects", json={**REQUEST, "requested_gpu": 9}, headers=user)
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


async def test_issue_and_comment_editing(client, admin, user, other):
    issue = (
        await client.post(
            "/api/v1/issues", json={"type": "question", "title": "原標題", "body": "原內文"}, headers=user
        )
    ).json()
    iid = issue["id"]
    assert issue["updated_at"] == issue["created_at"]  # fresh thread: nothing edited yet

    # bookkeeping (a new comment bumps comment_count) is not an edit
    c = (await client.post(f"/api/v1/issues/{iid}/comments", json={"body": "第一版"}, headers=user)).json()
    assert c["updated_at"] == c["created_at"]
    got = (await client.get(f"/api/v1/issues/{iid}", headers=user)).json()
    assert got["comment_count"] == 1 and got["updated_at"] == got["created_at"]

    # thread: author or admin, never a bystander
    assert (await client.patch(f"/api/v1/issues/{iid}", json={"title": "改"}, headers=other)).status_code == 403
    r = await client.patch(
        f"/api/v1/issues/{iid}", json={"type": "bug", "title": "新標題", "body": "## 新內文\n\n- 一"}, headers=user
    )
    assert r.status_code == 200, r.text
    edited = r.json()
    assert (edited["type"], edited["title"], edited["body"]) == ("bug", "新標題", "## 新內文\n\n- 一")
    assert edited["updated_at"] > edited["created_at"]
    r = await client.patch(f"/api/v1/issues/{iid}", json={"body": "管理員補充"}, headers=admin)
    assert r.status_code == 200 and r.json()["body"] == "管理員補充"
    last_edit = r.json()["updated_at"]

    # comment: author or admin, never a bystander; empty bodies are rejected
    url = f"/api/v1/issues/{iid}/comments/{c['id']}"
    assert (await client.patch(url, json={"body": "x"}, headers=other)).status_code == 403
    r = await client.patch(url, json={"body": "第二版"}, headers=user)
    assert r.status_code == 200 and r.json()["body"] == "第二版" and r.json()["updated_at"] > r.json()["created_at"]
    assert (await client.patch(url, json={"body": "管理員改"}, headers=admin)).json()["body"] == "管理員改"
    assert (await client.patch(url, json={"body": ""}, headers=user)).status_code == 422
    listed = (await client.get(f"/api/v1/issues/{iid}/comments", headers=user)).json()
    assert [x["body"] for x in listed] == ["管理員改"]

    # a comment is addressed through its own thread only
    other_issue = (
        await client.post("/api/v1/issues", json={"type": "bug", "title": "另一串", "body": "b"}, headers=user)
    ).json()
    r = await client.patch(f"/api/v1/issues/{other_issue['id']}/comments/{c['id']}", json={"body": "x"}, headers=user)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "COMMENT_NOT_FOUND"

    # closing is a status change, not an edit; its system event is immutable even for admins
    closed = (await client.post(f"/api/v1/issues/{iid}/close", json={"resolution_note": "done"}, headers=admin)).json()
    assert closed["status"] == "closed" and closed["updated_at"] == last_edit
    system = next(
        x for x in (await client.get(f"/api/v1/issues/{iid}/comments", headers=user)).json() if x["kind"] == "system"
    )
    r = await client.patch(f"/api/v1/issues/{iid}/comments/{system['id']}", json={"body": "x"}, headers=admin)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "COMMENT_NOT_EDITABLE"
