from __future__ import annotations

from tests.conftest import make_data_source, make_project


async def test_queue_create_order_cancel(client, admin, user, other):
    project = await make_project(client, admin, user)
    ds = await make_data_source(client, user, project["slug"])
    base = {
        "kind": "train",
        "input": {"kind": "data_source", "data_source_id": ds["id"], "spec": {"target": "yield_pct"}},
        "requested_gpu": 0,
        "requested_cpu": 2,
        "requested_memory_mb": 4096,
    }

    r = await client.post(f"/api/v1/projects/{project['slug']}/jobs", json={**base, "name": "automl-1"}, headers=user)
    assert r.status_code == 202, r.text
    j1 = r.json()
    assert j1["status"] == "queued" and j1["queue_position"] == 1 and j1["mode"] == "auto"
    assert j1["config"]["search"]["candidates"][0] in ("tabular.xgboost", "tabular.random_forest")
    assert j1["input"]["spec"]["target"] == "yield_pct" and j1["input"]["data_source_name"] == "mes-export"
    assert j1["wait_reason"] is None or "等待" in j1["wait_reason"] or "上限" in j1["wait_reason"]

    j2 = (
        await client.post(
            f"/api/v1/projects/{project['slug']}/jobs",
            json={
                **base,
                "name": "manual-xgb",
                "mode": "manual",
                "model_family": "tabular.xgboost",
                "config": {"max_depth": 4},
            },
            headers=other,
        )
    ).json()
    assert j2["queue_position"] == 2 and j2["queue_rank"] == j1["queue_rank"] + 1000
    assert j2["wait_reason"] is None  # nothing is running yet, so the pool and the project quota both fit

    # validation
    bad = await client.post(
        f"/api/v1/projects/{project['slug']}/jobs",
        json={**base, "name": "x", "mode": "manual", "model_family": "vision.yolo"},
        headers=user,
    )
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "MODEL_NOT_SUPPORTED"
    bad = await client.post(
        f"/api/v1/projects/{project['slug']}/jobs", json={**base, "name": "x", "requested_gpu": 3}, headers=user
    )
    assert bad.json()["detail"]["code"] == "QUOTA_EXCEEDED"
    bad = await client.post(
        f"/api/v1/projects/{project['slug']}/jobs", json={**base, "name": "x", "mode": "manual"}, headers=user
    )
    assert bad.json()["detail"]["code"] == "MODEL_FAMILY_REQUIRED"

    # admin queue + reorder; users cannot
    assert (await client.get("/api/v1/admin/queue", headers=user)).status_code == 403
    q = (await client.get("/api/v1/admin/queue", headers=admin)).json()
    assert [j["id"] for j in q["queued"]] == [j1["id"], j2["id"]] and q["running"] == []
    moved = (await client.post(f"/api/v1/admin/queue/{j2['id']}/move", json={"position": "top"}, headers=admin)).json()
    assert [j["id"] for j in moved] == [j2["id"], j1["id"]]
    ordered = (
        await client.put("/api/v1/admin/queue/order", json={"job_ids": [j1["id"], j2["id"]]}, headers=admin)
    ).json()
    assert [j["queue_position"] for j in ordered] == [1, 2]

    # member can cancel own queued job only
    assert (
        await client.post(f"/api/v1/jobs/{j2['id']}/cancel", headers=user)
    ).status_code == 200  # user is owner → allowed
    r = await client.post(f"/api/v1/jobs/{j1['id']}/cancel", headers=other)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "JOB_NOT_OWNER"
    assert (await client.get(f"/api/v1/jobs/{j2['id']}", headers=other)).json()["status"] == "cancelled"

    # admin force stop needs a reason
    assert (
        await client.post(f"/api/v1/admin/jobs/{j1['id']}/stop", json={"reason": "x"}, headers=admin)
    ).status_code == 422
    r = await client.post(f"/api/v1/admin/jobs/{j1['id']}/stop", json={"reason": "讓位給上線訓練"}, headers=admin)
    assert (
        r.json()["status"] == "cancelled"
        and r.json()["cancel_reason"] == "讓位給上線訓練"
        and r.json()["cancel_requested_by"]["username"] == "admin"
    )
    audit = (await client.get("/api/v1/admin/audit", headers=admin)).json()["items"]
    assert {a["action"] for a in audit} >= {"job.stop", "job.cancel", "queue.reorder", "job.cancelled"}

    # logs & events on a finished job
    assert (await client.get(f"/api/v1/jobs/{j1['id']}/logs", headers=user)).json()["total"] == 0
    r = await client.get(f"/api/v1/jobs/{j1['id']}/events", headers=user)
    assert r.status_code == 200 and "event: end" in r.text


async def test_viewer_cannot_create_jobs_and_members_api(client, admin, user, other):
    project = await make_project(client, admin, user)
    # downgrade other to viewer
    other_id = next(m["user"]["id"] for m in project["members"] if m["user"]["username"] == "other")
    r = await client.patch(
        f"/api/v1/projects/{project['slug']}/members/{other_id}", json={"role": "viewer"}, headers=user
    )
    assert r.status_code == 200
    ds = await make_data_source(client, user, project["slug"])
    r = await client.post(
        f"/api/v1/projects/{project['slug']}/jobs",
        json={"kind": "train", "name": "x", "input": {"kind": "data_source", "data_source_id": ds["id"]}},
        headers=other,
    )
    assert r.status_code == 403
    assert (await client.get(f"/api/v1/projects/{project['slug']}/jobs", headers=other)).status_code == 200
    # owner cannot be removed; viewer cannot manage members
    owner_id = project["owner"]["id"]
    assert (
        await client.delete(f"/api/v1/projects/{project['slug']}/members/{owner_id}", headers=user)
    ).status_code == 400
    assert (
        await client.delete(f"/api/v1/projects/{project['slug']}/members/{other_id}", headers=other)
    ).status_code == 403
    assert (
        await client.delete(f"/api/v1/projects/{project['slug']}/members/{other_id}", headers=user)
    ).status_code == 200
    assert (await client.get(f"/api/v1/projects/{project['slug']}", headers=other)).status_code == 404


async def test_data_source_credentials_hidden_and_quota(client, admin, user, superadmin):
    project = await make_project(client, admin, user)
    ds = await make_data_source(client, user, project["slug"])
    assert ds["has_credentials"] is True and "Authorization" not in str(ds)
    r = await client.patch(
        f"/api/v1/projects/{project['slug']}/quota", json={"gpu_limit": 0, "cpu_limit": 1}, headers=superadmin
    )
    assert r.json()["gpu_limit"] == 0
    assert (
        await client.patch(f"/api/v1/projects/{project['slug']}/quota", json={"gpu_limit": 1}, headers=user)
    ).status_code == 403
    r = await client.put(
        "/api/v1/admin/settings/resource-pool",
        json={"gpu_indices": [0], "cpu_cores": 4, "memory_mb": 8192, "max_running_jobs": 1, "allow_backfill": False},
        headers=superadmin,
    )
    assert r.status_code == 200 and r.json()["max_running_jobs"] == 1
    assert (await client.get("/api/v1/admin/overview", headers=superadmin)).json()["pool_gpu_total"] == 1


def test_chosen_weight_must_be_in_the_zoo(monkeypatch):
    """A family counts as ready when any alternative weight is present; the backbone / model a config picks
    must itself be there (else the job would only fail inside the trainer)."""
    import pytest
    from fastapi import HTTPException

    from app.services import jobs as jobs_svc

    monkeypatch.setattr(jobs_svc.zoo_svc, "weight_present", lambda wid: wid in {"dinov2-small", "yolov8n-seg"})
    check = jobs_svc._check_chosen_weight
    check("vision.dino", "classification", {})
    check("vision.dino", "classification", {"backbone": "dinov2-small"})
    check("vision.yolo", "segmentation", {"model": "yolov8n"})
    check("vision.yolo", "segmentation", {"model": "yolov8m", "pretrained": False})  # from scratch: no weight
    check("tabular.xgboost", "regression", {"max_depth": 4})
    with pytest.raises(HTTPException) as e:
        check("vision.dino", "classification", {"backbone": "dinov3-vits16"})
    assert e.value.detail["code"] == "WEIGHTS_MISSING" and "dinov3-vits16" in e.value.detail["message"]
    with pytest.raises(HTTPException) as e:
        check("vision.yolo", "detection", {"model": "yolov8n"})  # only the -seg file is present
    assert e.value.detail["code"] == "WEIGHTS_MISSING"
    with pytest.raises(HTTPException) as e:
        check("vision.dino", "classification", {"backbone": "resnet50"})
    assert e.value.detail["code"] == "WEIGHT_UNKNOWN"


def test_deprecated_families_cannot_be_trained_but_still_load():
    import pytest
    from fastapi import HTTPException

    from app.catalog import loader
    from app.services import jobs as jobs_svc

    jobs_svc._check_not_deprecated("vision.dino")
    jobs_svc._check_not_deprecated("tabular.linear")
    with pytest.raises(HTTPException) as e:
        jobs_svc._check_not_deprecated("vision.dino_fewshot")
    assert e.value.detail["code"] == "MODEL_DEPRECATED"
    # the legacy ids stay in the catalog (old artifacts, job rows) but the public listing marks them
    assert loader.public_catalog()["families"]["vision.dino_finetune"]["deprecated"] is True
    assert "deprecated" not in loader.public_catalog()["families"]["vision.dino"]


def test_auto_mode_pins_the_dino_backbone_and_finetune(monkeypatch):
    """The wizard decides backbone / finetune on its 骨幹 step before the mode; auto mode sends them pinned in the
    config, and they are validated at creation (not in the fifth trial)."""
    import pytest
    from fastapi import HTTPException

    from app.services import jobs as jobs_svc

    monkeypatch.setattr(jobs_svc.zoo_svc, "weight_present", lambda wid: wid == "dinov2-small")
    check = jobs_svc._check_pinned_dino
    check("classification", {}, ["vision.dino", "vision.yolo"])
    check("classification", {"backbone": "dinov2-small", "finetune": "lora"}, ["vision.dino"])
    check("classification", {"backbone": "resnet50", "finetune": "bad"}, ["vision.yolo"])  # DINO not a candidate
    with pytest.raises(HTTPException) as e:
        check("classification", {"finetune": "bad"}, ["vision.dino"])
    assert e.value.detail["code"] == "BAD_FINETUNE"
    with pytest.raises(HTTPException) as e:
        check("classification", {"backbone": "dinov3-vitb16", "finetune": "none"}, ["vision.dino"])
    assert e.value.detail["code"] == "WEIGHTS_MISSING"
    with pytest.raises(HTTPException) as e:
        check("classification", {"backbone": "resnet50"}, ["vision.dino"])
    assert e.value.detail["code"] == "WEIGHT_UNKNOWN"
    # the search space no longer carries what the wizard pins; the fine-tune knobs are gated on it
    from app.catalog import loader

    space = loader.family("vision.dino")["search_space"]
    assert "backbone" not in space and "finetune" not in space
    assert space["lr"]["when"] == {"finetune": ["lora", "full"]} and space["rank"]["when"] == {"finetune": ["lora"]}
