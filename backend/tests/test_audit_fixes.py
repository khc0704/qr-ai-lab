"""Regression tests for the self-audit fixes (security, lifecycle, scheduler, API hygiene)."""

from __future__ import annotations

import os
import time
from datetime import timedelta
from pathlib import Path

import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError
from sqlalchemy import select

from app.core import security
from app.core.config import Settings, get_settings
from app.core.security import create_job_token
from app.db.base import utcnow
from app.db.session import get_sessionmaker
from app.events.bus import _after
from app.models import Job, Upload
from app.routers import auth as auth_router
from app.scheduler.loop import Scheduler
from app.scheduler.runner import ENV_PASSTHROUGH, LaunchSpec, job_env, passthrough_env
from app.services import gpu as gpu_svc
from app.services import jobs as jobs_svc
from app.services import users as users_svc
from app.storage.local import get_storage
from tests.conftest import make_data_source, make_project
from tests.test_scheduler import FakeRunner
from tests.test_uploads_internal import _upload_and_job

GOOD = {
    "app_env": "prod",
    "database_url": "mariadb+asyncmy://qr:pw@127.0.0.1:3306/qr",
    "redis_url": "redis://127.0.0.1:6379/0",
    "auth_secret": "a" * 40,
    "job_token_secret": "b" * 40,
    "dataset_secret_key": Fernet.generate_key().decode(),
    "auth_mode": "keycloak",
    "keycloak_issuer": "https://sso/realms/x",
    "keycloak_client_id": "qr-ai-lab",
}


def test_prod_settings_refuse_development_defaults():
    with pytest.raises(ValidationError) as e:
        Settings(
            _env_file=None,
            app_env="prod",
            auth_mode="keycloak",
            keycloak_issuer="https://sso/realms/x",
            keycloak_client_id="qr-ai-lab",
            auth_secret="dev-secret-change-me",
            job_token_secret="change-me-too",
            dataset_secret_key=None,
            redis_url=None,
            scheduler_embedded=False,
        )
    msg = str(e.value)
    assert "AUTH_SECRET" in msg and "JOB_TOKEN_SECRET" in msg and "DATASET_SECRET_KEY" in msg and "REDIS_URL" in msg
    with pytest.raises(ValidationError, match="Fernet"):
        Settings(_env_file=None, **{**GOOD, "dataset_secret_key": "not-a-key"})
    with pytest.raises(ValidationError, match="SEED_SUPERADMIN_PASSWORD"):
        Settings(_env_file=None, **{**GOOD, "auth_mode": "local"})
    ok = Settings(_env_file=None, **GOOD)
    assert ok.app_env == "prod"
    dev = Settings(_env_file=None, app_env="dev", auth_secret="dev-secret-change-me", dataset_secret_key=None)
    assert dev.auth_secret == "dev-secret-change-me"  # dev stays convenient


def test_keycloak_token_must_be_issued_for_this_client(monkeypatch):
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = rsa_key.public_key()
    pem = rsa_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )

    class FakeJwks:
        def get_signing_key_from_jwt(self, _token):
            class K:
                key = public  # a class body cannot see the enclosing function's locals

            return K()

    monkeypatch.setattr(security, "_jwks_client", lambda _issuer: FakeJwks())
    s = get_settings()
    monkeypatch.setattr(s, "keycloak_issuer", "https://sso/realms/x")
    monkeypatch.setattr(s, "keycloak_client_id", "qr-ai-lab")
    monkeypatch.setattr(s, "keycloak_audience", None)
    now = int(time.time())
    base = {"iss": "https://sso/realms/x", "sub": "u1", "iat": now, "exp": now + 60, "aud": "account"}
    ours = jwt.encode({**base, "azp": "qr-ai-lab"}, pem, algorithm="RS256")
    other = jwt.encode({**base, "azp": "some-other-client"}, pem, algorithm="RS256")
    assert security.decode_keycloak_token(ours, s)["azp"] == "qr-ai-lab"
    with pytest.raises(Exception, match="client"):
        security.decode_keycloak_token(other, s)


async def test_login_is_rate_limited(client):
    auth_router.reset_rate_limits()
    try:
        for _ in range(auth_router.LOGIN_MAX_FAILURES):
            r = await client.post("/api/v1/auth/login", json={"username": "user", "password": "wrong"})
            assert r.status_code == 401
        r = await client.post("/api/v1/auth/login", json={"username": "user", "password": "wrong"})
        assert r.status_code == 429 and r.json()["detail"]["code"] == "LOGIN_RATE_LIMITED"
        # the lockout is per account: another user still logs in
        assert (
            await client.post("/api/v1/auth/login", json={"username": "admin", "password": "adminpw"})
        ).status_code == 200
    finally:
        auth_router.reset_rate_limits()


def test_job_processes_only_inherit_an_allow_list(tmp_path):
    spec = LaunchSpec(
        job_id=1,
        kind="train",
        gpus=[],
        cpus=[0],
        cpu=1,
        memory_mb=512,
        gpu_memory_mb=None,
        input_dir=tmp_path,
        output_dir=tmp_path,
        log_path=tmp_path / "job.log",
        model_dir=None,
        zoo_dir=None,
        env={"JOB_TOKEN": "t"},
    )
    source = {
        "PATH": "/usr/bin",
        "HOME": "/home/qrlab",
        "CUDA_VISIBLE_DEVICES": "0",
        "DATABASE_URL": "mariadb://secret",
        "AUTH_SECRET": "s",
        "JOB_TOKEN_SECRET": "s",
        "DATASET_SECRET_KEY": "s",
        "REDIS_URL": "r",
        "KEYCLOAK_ISSUER": "k",
    }
    env = job_env(spec, passthrough_env(source))
    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/home/qrlab" and env["JOB_TOKEN"] == "t"
    for secret in (
        "DATABASE_URL",
        "AUTH_SECRET",
        "JOB_TOKEN_SECRET",
        "DATASET_SECRET_KEY",
        "REDIS_URL",
        "KEYCLOAK_ISSUER",
    ):
        assert secret not in env
    assert "PATH" in ENV_PASSTHROUGH


async def test_deleting_a_job_created_from_an_upload(client, admin, user, superadmin):
    """uploads.claimed_by_job_id is ON DELETE SET NULL; SQLite now enforces FKs like MariaDB."""
    _project, up, job = await _upload_and_job(client, admin, user)
    async with get_sessionmaker()() as session:
        j = await jobs_svc.get(session, job["id"])
        await jobs_svc.finish(session, j, "failed", error="x")
    r = await client.delete(f"/api/v1/admin/jobs/{job['id']}", headers=superadmin)
    assert r.status_code == 200, r.text
    async with get_sessionmaker()() as session:
        row = await session.get(Upload, up["id"])
        assert row is not None and row.claimed_by_job_id is None
        assert await session.get(Job, job["id"]) is None


async def test_deleting_a_data_source_used_by_a_finished_job(client, admin, user):
    project = await make_project(client, admin, user)
    ds = await make_data_source(client, user, project["slug"])
    r = await client.post(
        f"/api/v1/projects/{project['slug']}/jobs",
        json={
            "kind": "train",
            "name": "ds-run",
            "mode": "manual",
            "model_family": "tabular.linear",
            "input": {"kind": "data_source", "data_source_id": ds["id"], "spec": {"target": "yield_pct"}},
        },
        headers=user,
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]
    assert (
        await client.delete(f"/api/v1/projects/{project['slug']}/data-sources/{ds['id']}", headers=user)
    ).status_code == 409
    async with get_sessionmaker()() as session:
        await jobs_svc.finish(session, await jobs_svc.get(session, job_id), "succeeded")
    r = await client.delete(f"/api/v1/projects/{project['slug']}/data-sources/{ds['id']}", headers=user)
    assert r.status_code == 200, r.text
    job = (await client.get(f"/api/v1/jobs/{job_id}", headers=user)).json()
    assert job["data_source_id"] is None and job["input"]["data_source_name"]


async def test_tool_pool_cannot_be_archived_but_projects_can_be_unarchived(client, admin, user):
    pool = (await client.get("/api/v1/tools/pool", headers=user)).json()
    r = await client.post(f"/api/v1/projects/{pool['slug']}/archive", headers=admin)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TOOL_POOL"
    project = await make_project(client, admin, user)
    assert (await client.post(f"/api/v1/projects/{project['slug']}/archive", headers=user)).json()[
        "status"
    ] == "archived"
    r = await client.post(f"/api/v1/projects/{project['slug']}/unarchive", headers=user)
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["archived_at"] is None


async def test_internal_paths_are_confined_and_writes_stop_after_the_end(client, admin, user):
    _project, _up, job = await _upload_and_job(client, admin, user)
    other_project = await make_project(client, admin, user, slug="other")
    token = {"Authorization": f"Bearer {create_job_token(job['id'], 'train', 3600)}"}
    async with get_sessionmaker()() as session:
        j = await jobs_svc.get(session, job["id"])
        await jobs_svc.mark_scheduled(session, j, [], [0])
        await jobs_svc.mark_running(session, j, "pid:1:1")
        output = j.output_path
    storage = get_storage()
    victim = storage.abs(f"projects/{other_project['slug']}/secret.txt")
    victim.parent.mkdir(parents=True, exist_ok=True)
    victim.write_text("x")
    escape = f"../../../{other_project['slug']}/secret.txt"
    r = await client.post(
        f"/api/v1/internal/jobs/{job['id']}/artifacts",
        json={"kind": "model", "path": escape, "name": "m", "framework": "sklearn"},
        headers=token,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_PATH"
    r = await client.post(f"/api/v1/internal/jobs/{job['id']}/result", json={"output_path": escape}, headers=token)
    assert r.status_code == 400
    inside = storage.abs(f"{output}/output/pred.csv")
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_text("a\n")
    r = await client.post(
        f"/api/v1/internal/jobs/{job['id']}/result", json={"output_path": "output/pred.csv"}, headers=token
    )
    assert r.status_code == 200
    async with get_sessionmaker()() as session:
        await jobs_svc.finish(session, await jobs_svc.get(session, job["id"]), "succeeded")
    r = await client.post(f"/api/v1/internal/jobs/{job['id']}/status", json={"status": "running"}, headers=token)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_FINISHED"
    assert (await client.get(f"/api/v1/internal/jobs/{job['id']}/spec", headers=token)).status_code == 200


async def test_deleting_a_project_removes_only_its_own_upload_folders(client, admin, user, superadmin):
    p1 = await make_project(client, admin, user, slug="keep")
    p2 = await make_project(client, admin, user, slug="gone")
    ups = {}
    for p in (p1, p2):
        r = await client.post(
            f"/api/v1/projects/{p['slug']}/uploads", files={"file": ("d.csv", "a,b\n1,2\n", "text/csv")}, headers=user
        )
        assert r.status_code == 201, r.text
        ups[p["slug"]] = r.json()["id"]
    storage = get_storage()
    assert storage.upload_dir(ups["keep"]).exists() and storage.upload_dir(ups["gone"]).exists()
    assert (await client.delete("/api/v1/projects/gone", headers=superadmin)).status_code == 200
    assert storage.upload_dir(ups["keep"]).exists()
    assert not storage.upload_dir(ups["gone"]).exists()


async def test_find_by_username_or_email_handles_duplicate_emails(db):
    async with get_sessionmaker()() as session:
        for name in ("dup-a", "dup-b"):
            await users_svc.create_local_user(
                session, username=name, password="pw123456", email="shared@example.com", display_name=None
            )
        assert (await users_svc.find_by_username_or_email(session, "dup-a")).username == "dup-a"
        with pytest.raises(Exception, match="AMBIGUOUS_USER"):
            await users_svc.find_by_username_or_email(session, "shared@example.com")


def test_gpu_request_stays_reserved_until_the_driver_sees_the_job():
    now = utcnow()
    job = Job(
        id=1, requested_gpu=1, requested_gpu_memory_mb=8000, assigned_gpus=[0], started_at=now - timedelta(minutes=10)
    )
    reading = type("G", (), {"index": 0, "memory_total_mb": 16000, "memory_used_mb": 300})()
    slots = gpu_svc.slots_from([0], [job], [reading], measured={}, now=now, warmup_s=120)  # type: ignore[list-item]
    assert slots[0].pending_mb == 8000  # 10 minutes in, still no CUDA context: the whole request is reserved
    slots = gpu_svc.slots_from([0], [job], [reading], measured={1: 5000}, now=now, warmup_s=120)  # type: ignore[list-item]
    assert slots[0].pending_mb == 0 and slots[0].measured_mb == 5000  # measured after warm-up: only what it uses
    fresh = Job(id=2, requested_gpu=1, requested_gpu_memory_mb=8000, assigned_gpus=[0], started_at=now)
    slots = gpu_svc.slots_from([0], [fresh], [reading], measured={2: 1000}, now=now, warmup_s=120)  # type: ignore[list-item]
    assert slots[0].pending_mb == 7000  # within warm-up: request minus what is already allocated


async def test_cleanup_keeps_the_input_of_a_queued_job(client, admin, user):
    _project, _up, job = await _upload_and_job(client, admin, user)
    storage = get_storage()
    input_dir = storage.job_input_dir(job["id"])
    assert input_dir.exists()
    old = time.time() - 5 * 86400
    os.utime(input_dir, (old, old))
    stale_dir = storage.abs("jobs/999999")
    stale_dir.mkdir(parents=True)
    os.utime(stale_dir, (old, old))
    sched = Scheduler(runner=FakeRunner(), settings=get_settings())
    async with get_sessionmaker()() as session:
        await sched.cleanup(session)
    assert input_dir.exists(), "a queued job's input must survive the stale sweep"
    assert not stale_dir.exists()


def test_log_rotation_keeps_the_tail(tmp_path: Path):
    log = tmp_path / "job.log"
    log.write_bytes(b"".join(f"line {i}\n".encode() for i in range(10000)))
    Scheduler._rotate_log(log, keep=2000)
    text = log.read_text()
    assert text.startswith("[log rotated") and text.endswith("line 9999\n") and "line 0\n" not in text
    assert log.stat().st_size < 2200


def test_event_ids_compare_numerically():
    assert _after("1000-10", "1000-9") and not _after("999-1", "1000-0") and _after("10000-0", "9999-5")


async def test_min_role_is_not_a_query_parameter(client, user):
    spec = (await client.get("/openapi.json")).json()
    params = [
        p["name"]
        for path, ops in spec["paths"].items()
        if path.startswith("/api/v1/jobs/")
        for op in ops.values()
        for p in op.get("parameters", [])
    ]
    assert "min_role" not in params


async def test_cancel_and_launch_do_not_race(client, admin, user):
    _project, _up, job = await _upload_and_job(client, admin, user)
    async with get_sessionmaker()() as session:
        j = await jobs_svc.get(session, job["id"])
        # the API cancels the queued job …
        stmt = select(Job).where(Job.id == job["id"])
        stale = (await session.execute(stmt)).scalar_one()
    async with get_sessionmaker()() as s2:
        j2 = await jobs_svc.get(s2, job["id"])
        actor = await users_svc.get_by_username(s2, "user")
        await jobs_svc.cancel(s2, actor, j2, "changed my mind")
    async with get_sessionmaker()() as s3:
        # … and the scheduler, holding a stale row, must not be able to schedule it
        s3.add(stale)
        with pytest.raises(jobs_svc.JobStateChanged):
            await jobs_svc.mark_scheduled(s3, stale, [], [0])
        assert (await jobs_svc.get(s3, job["id"])).status == "cancelled"
    del j


async def test_parallel_first_use_creates_one_tool_pool(client, user):
    """A page renders several server components at once: /tools/pool and /tools/jobs race on creation."""
    import asyncio

    results = await asyncio.gather(
        client.get("/api/v1/tools/pool", headers=user),
        client.get("/api/v1/tools/jobs", headers=user),
        client.get("/api/v1/tools/pool", headers=user),
    )
    assert [r.status_code for r in results] == [200, 200, 200], [r.text[:200] for r in results]
    assert results[0].json()["slug"] == results[2].json()["slug"] == "tools"
    async with get_sessionmaker()() as session:
        from sqlalchemy import func, select

        from app.models import Project

        stmt = select(func.count()).select_from(Project).where(Project.kind == "shared")
        n = (await session.execute(stmt)).scalar_one()
    assert n == 1
