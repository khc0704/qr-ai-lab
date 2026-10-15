"""GPU placement by free VRAM, the admin GPU reset, and the usage-history sampler / API."""

from __future__ import annotations

from app.db.session import get_sessionmaker
from app.models import Job
from app.scheduler.loop import Scheduler
from app.scheduler.runner import job_env
from app.schemas.admin import NodeGpu
from app.services import gpu as gpu_svc
from app.services import usage as usage_svc
from tests.conftest import make_data_source, make_project
from tests.test_scheduler import FakeRunner


def _job(id_: int, gpus: int, mem: int | None) -> Job:
    return Job(id=id_, requested_gpu=gpus, requested_gpu_memory_mb=mem, assigned_gpus=[])


def _readings(*used: int, total: int = 24000) -> list[NodeGpu]:
    return [
        NodeGpu(index=i, name="g", memory_total_mb=total, memory_used_mb=u, utilization=0) for i, u in enumerate(used)
    ]


def test_plan_exclusive_skips_busy_and_occupied_gpus():
    running = [Job(id=9, requested_gpu=1, requested_gpu_memory_mb=None, assigned_gpus=[0])]
    slots = gpu_svc.slots_from([0, 1, 2], running, _readings(100, 5000, 200))
    # GPU 0 held exclusively, GPU 1 has 5000/24000 used by someone else (> 10%), GPU 2 is free
    assert gpu_svc.plan(_job(1, 1, None), slots, share=True, busy_threshold=0.1, reserve_mb=512) == [2]
    assert gpu_svc.plan(_job(1, 2, None), slots, share=True, busy_threshold=0.1, reserve_mb=512) == []


def test_plan_uses_measured_vram_with_a_warm_up_for_fresh_jobs():
    from datetime import timedelta

    from app.db.base import utcnow

    now = utcnow()
    fresh = Job(id=9, requested_gpu=1, requested_gpu_memory_mb=8000, assigned_gpus=[0], started_at=now)
    # GPU 0: driver sees 3000 MB (someone else + the fresh job's first allocations); the fresh job measured 1000 MB
    slots = gpu_svc.slots_from([0, 1], [fresh], _readings(3000, 0), measured={9: 1000}, now=now, warmup_s=120)
    s0 = slots[0]
    assert s0.measured_mb == 1000 and s0.pending_mb == 7000 and s0.reserved_mb == 8000
    # free on GPU 0 = 24000 − 3000 − 7000 − 512 = 13488 → a 10000 MB job fits there (best fit), 20000 goes to GPU 1
    assert gpu_svc.plan(_job(1, 1, 10000), slots, share=True, busy_threshold=0.1, reserve_mb=512) == [0]
    assert gpu_svc.plan(_job(2, 1, 20000), slots, share=True, busy_threshold=0.1, reserve_mb=512) == [1]
    # after the warm-up only the driver reading counts: the job settled at 2500 MB, so GPU 0 has 20488 MB free
    old = Job(
        id=9, requested_gpu=1, requested_gpu_memory_mb=8000, assigned_gpus=[0], started_at=now - timedelta(minutes=10)
    )
    slots = gpu_svc.slots_from([0, 1], [old], _readings(3000, 0), measured={9: 2500}, now=now)
    assert slots[0].pending_mb == 0 and slots[0].free_mb(512) == 20488
    assert gpu_svc.plan(_job(2, 1, 20000), slots, share=True, busy_threshold=0.1, reserve_mb=512) == [0]
    # an exclusive job cannot take GPU 0 (a job is there) but GPU 1 is empty
    assert gpu_svc.plan(_job(3, 1, None), slots, share=True, busy_threshold=0.1, reserve_mb=512) == [1]
    # sharing disabled → a sharing request behaves like exclusive
    assert gpu_svc.plan(_job(4, 1, 1000), slots, share=False, busy_threshold=0.1, reserve_mb=512) == [1]
    # placing in this tick counts the whole request as pending until it is measured
    gpu_svc.place(_job(2, 1, 20000), [1], slots)
    assert slots[1].pending_mb == 20000 and slots[1].jobs == [2]
    assert gpu_svc.plan(_job(5, 1, 5000), slots, share=True, busy_threshold=0.1, reserve_mb=512) == [0]


def test_measured_by_job_maps_driver_processes_to_jobs(monkeypatch):
    monkeypatch.setattr(
        gpu_svc, "gpu_processes", lambda index: [(100, 1500), (200, 300), (999, 7000)] if index == 0 else [(100, 50)]
    )
    out = gpu_svc.measured_by_job([0, 1], {1: {100, 101}, 2: {200}})
    assert out == {1: 1550, 2: 300}  # pid 999 belongs to someone else
    assert gpu_svc.measured_by_job([0], {}) == {}


def test_plan_without_readings_spreads_sharing_jobs():
    running = [Job(id=9, requested_gpu=1, requested_gpu_memory_mb=4000, assigned_gpus=[0])]
    slots = gpu_svc.slots_from([0, 1], running, [])
    assert gpu_svc.plan(_job(1, 1, 4000), slots, share=True, busy_threshold=0.1, reserve_mb=512) == [1]
    assert gpu_svc.plan(_job(2, 2, 4000), slots, share=True, busy_threshold=0.1, reserve_mb=512) == [1, 0]


async def test_scheduler_places_two_sharing_jobs_on_one_gpu(client, admin, user, superadmin):
    project = await make_project(client, admin, user)
    slug = project["slug"]
    await client.patch(
        f"/api/v1/projects/{slug}/quota",
        json={"gpu_limit": 4, "cpu_limit": 8, "memory_limit_mb": 16384, "max_concurrent_jobs": 4},
        headers=superadmin,
    )
    pool = (await client.get("/api/v1/admin/settings/resource-pool", headers=admin)).json()
    r = await client.put(
        "/api/v1/admin/settings/resource-pool",
        json={**pool, "gpu_indices": [0], "max_running_jobs": 4},
        headers=superadmin,
    )
    assert r.status_code == 200 and r.json()["gpu_share"] is True
    ds = await make_data_source(client, user, slug)
    base = {
        "kind": "train",
        "mode": "manual",
        "model_family": "tabular.linear",
        "input": {"kind": "data_source", "data_source_id": ds["id"], "spec": {"target": "yield_pct"}},
        "requested_gpu": 1,
        "requested_gpu_memory_mb": 4000,
        "requested_cpu": 1,
        "requested_memory_mb": 1024,
    }
    ids = []
    for name in ("a", "b", "c"):
        r = await client.post(f"/api/v1/projects/{slug}/jobs", json={**base, "name": name}, headers=user)
        assert r.status_code == 202, r.text
        ids.append(r.json()["id"])
    runner = FakeRunner()
    sched = Scheduler(runner=runner)
    sched.sampling = False
    for _ in range(3):
        await sched.tick()  # one launch per project per tick
    started = {s.job_id: s for s in runner.started}
    assert set(started) == set(ids)
    assert all(s.gpus == [0] and s.gpu_memory_mb == 4000 for s in started.values())
    env = job_env(started[ids[0]], base={})  # what the child process really gets
    assert env["JOB_GPU_MEMORY_MB"] == "4000" and env["LOKY_MAX_CPU_COUNT"] == "1" and env["OMP_NUM_THREADS"] == "1"
    assert env["CUDA_VISIBLE_DEVICES"] == "0" and env["JOB_CPU_CORES"] == "0"
    node = (await client.get("/api/v1/admin/node", headers=admin)).json()
    assert node["gpus"] == [] or node["gpus"][0]["job_ids"]  # no NVIDIA driver here; placement is in jobs
    q = (await client.get("/api/v1/admin/queue", headers=admin)).json()
    assert [j["assigned_gpus"] for j in q["running"]] == [[0], [0], [0]]
    # an exclusive job now waits with a readable reason in its log
    r = await client.post(
        f"/api/v1/projects/{slug}/jobs", json={**base, "name": "x", "requested_gpu_memory_mb": None}, headers=user
    )
    assert r.status_code == 202, r.text
    await sched.tick()
    j = (await client.get(f"/api/v1/jobs/{r.json()['id']}", headers=user)).json()
    assert j["status"] == "queued" and j["requested_gpu_memory_mb"] is None
    log = (await client.get(f"/api/v1/jobs/{r.json()['id']}/logs", headers=user)).json()["lines"]
    assert any("waiting for 1 GPU (exclusive)" in line for line in log), log


async def test_gpu_reset_stops_our_jobs_and_needs_superadmin(client, admin, user, superadmin):
    project = await make_project(client, admin, user)
    slug = project["slug"]
    ds = await make_data_source(client, user, slug)
    r = await client.post(
        f"/api/v1/projects/{slug}/jobs",
        json={
            "kind": "train",
            "mode": "manual",
            "model_family": "tabular.linear",
            "name": "g",
            "input": {"kind": "data_source", "data_source_id": ds["id"], "spec": {"target": "yield_pct"}},
            "requested_gpu": 1,
            "requested_cpu": 1,
            "requested_memory_mb": 1024,
        },
        headers=user,
    )
    job_id = r.json()["id"]
    runner = FakeRunner()
    sched = Scheduler(runner=runner)
    sched.sampling = False
    await sched.tick()
    assert runner.started and runner.started[0].gpus == [0]
    r = await client.post("/api/v1/admin/gpus/0/reset", json={"mode": "jobs", "reason": "stuck"}, headers=admin)
    assert r.status_code == 403
    r = await client.post("/api/v1/admin/gpus/0/reset", json={"mode": "all", "reason": "stuck"}, headers=superadmin)
    assert r.status_code == 200, r.text
    assert r.json()["stopped_jobs"] == [job_id] and r.json()["killed_pids"] == []
    r = await client.post("/api/v1/admin/gpus/0/reset", json={"mode": "device", "reason": "stuck"}, headers=superadmin)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "GPU_RESET_COMMAND_UNSET"
    r = await client.post("/api/v1/admin/gpus/7/reset", json={"mode": "jobs", "reason": "stuck"}, headers=superadmin)
    assert r.status_code == 404
    await sched.tick()  # the scheduler delivers the stop (SIGTERM)
    await sched.tick()  # ... and records the exit
    job = (await client.get(f"/api/v1/jobs/{job_id}", headers=user)).json()
    assert job["status"] == "cancelled" and "GPU 0 reset: stuck" in (job["cancel_reason"] or "")
    audit = (await client.get("/api/v1/admin/audit", headers=admin)).json()["items"]
    assert any(a["action"] == "gpu.reset" and a["target_id"] == 0 for a in audit)


async def test_usage_sampling_and_history(client, admin, user, superadmin):
    project = await make_project(client, admin, user)
    slug = project["slug"]
    ds = await make_data_source(client, user, slug)
    r = await client.post(
        f"/api/v1/projects/{slug}/jobs",
        json={
            "kind": "train",
            "mode": "manual",
            "model_family": "tabular.linear",
            "name": "u",
            "input": {"kind": "data_source", "data_source_id": ds["id"], "spec": {"target": "yield_pct"}},
            "requested_gpu": 0,
            "requested_cpu": 2,
            "requested_memory_mb": 2048,
        },
        headers=user,
    )
    assert r.status_code == 202
    runner = FakeRunner()
    sched = Scheduler(runner=runner)
    await sched.tick()
    async with get_sessionmaker()() as session:
        await sched.maybe_sample(session, force=True)
        await sched.maybe_sample(session, force=True)
        assert await usage_svc.purge(session, retention_days=1) == 0  # nothing older than a day
    assert (await client.get("/api/v1/admin/usage", headers=user)).status_code == 403
    r = await client.get("/api/v1/admin/usage?range=1h", headers=admin)
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["bucket_s"] == 60 and h["points"] and h["totals"]["cpu_cores"] >= 1
    pt = h["points"][-1]
    assert pt["alloc_cpu"] == 2 and pt["running_jobs"] == 1 and str(project["id"]) in pt["projects"]
    share = h["project_share"][str(project["id"])]
    assert share["cpu_of_quota"] >= 0 and share["job_seconds"] >= 0 and h["projects"][0]["slug"] == slug
    assert (await client.get("/api/v1/admin/usage?range=2h", headers=admin)).status_code == 422
