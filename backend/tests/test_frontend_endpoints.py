"""Endpoints added for the web frontend: cross-project recent jobs and capacity for non-admins."""

from __future__ import annotations

from tests.conftest import make_data_source, make_project


async def test_recent_jobs_scoped_to_membership_and_capacity(client, admin, user, other):
    project = await make_project(client, admin, user)
    ds = await make_data_source(client, user, project["slug"])
    body = {
        "kind": "train",
        "name": "j",
        "mode": "manual",
        "model_family": "tabular.linear",
        "input": {"kind": "data_source", "data_source_id": ds["id"], "spec": {"target": "yield_pct"}},
        "requested_gpu": 0,
        "requested_cpu": 1,
        "requested_memory_mb": 1024,
    }
    assert (await client.post(f"/api/v1/projects/{project['slug']}/jobs", json=body, headers=user)).status_code == 202
    mine = (await client.get("/api/v1/jobs?limit=5", headers=user)).json()
    assert [j["name"] for j in mine] == ["j"] and mine[0]["project_slug"] == project["slug"]
    assert (await client.get("/api/v1/jobs", headers=admin)).json()[0]["id"] == mine[0]["id"]
    # 'other' is a member too (make_project adds them) → sees it; a non-member would see nothing
    assert len((await client.get("/api/v1/jobs", headers=other)).json()) == 1
    assert (await client.get("/api/v1/jobs?status=succeeded", headers=user)).json() == []

    cap = (await client.get("/api/v1/capacity", headers=user)).json()
    assert cap["pool"]["gpu_indices"] == [0, 1] and cap["allocated"]["running_jobs"] == 0
    assert (await client.get("/api/v1/admin/settings/resource-pool", headers=user)).status_code == 403
