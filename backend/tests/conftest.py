"""Test env: SQLite file, in-process event bus, temp DATA_ROOT, seeded admin/user. Set before app imports."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="qr-ai-lab-test-"))
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite+aiosqlite:///{_TMP}/test.db",
        "REDIS_URL": "",
        "DATA_ROOT": str(_TMP / "data"),
        "AUTH_SECRET": "test-secret-0123456789abcdef0123456789abcdef",
        "JOB_TOKEN_SECRET": "test-job-secret-0123456789abcdef0123456789abcdef",
        "SEED_SUPERADMIN_PASSWORD": "superpw",
        "SEED_ADMIN_PASSWORD": "adminpw",
        "SEED_USER_PASSWORD": "userpw",
        "JOB_RUNNER": "subprocess",
        "TRAINER_DIR": str(Path(__file__).resolve().parents[2] / "trainer"),
        "INTERNAL_BACKEND_URL": "http://test",
    }
)

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app.models  # noqa: E402, F401
from app.db.base import Base  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.events.bus import reset_bus  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import settings as settings_svc  # noqa: E402
from app.services import users as users_svc  # noqa: E402
from app.storage.local import reset_storage  # noqa: E402


@pytest.fixture(autouse=True)
def no_real_gpus(monkeypatch):
    """Tests must not depend on the machine they run on: a dev laptop with an NVIDIA GPU would otherwise feed real
    pynvml readings (busy GPU 0, a single physical GPU) into the scheduler and change placements."""
    from app.services import gpu as gpu_svc
    from app.services import node as node_svc

    monkeypatch.setattr(node_svc, "detect_gpus", lambda: [])
    monkeypatch.setattr(gpu_svc, "gpu_processes", lambda index: [])


@pytest.fixture
async def db():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))  # jobs ↔ artifacts reference each other
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("PRAGMA foreign_keys=ON"))
    settings_svc.invalidate()
    reset_bus()
    shutil.rmtree(_TMP / "data", ignore_errors=True)  # job ids restart from 1: never reuse an old job dir
    reset_storage()
    async with get_sessionmaker()() as session:
        await users_svc.seed_users(session, "adminpw", "userpw", "superpw")
        await settings_svc.set_resource_pool(
            session,
            settings_svc.ResourcePool(
                gpu_indices=[0, 1], cpu_cores=8, memory_mb=32768, max_running_jobs=2, allow_backfill=True
            ),
            None,
        )  # type: ignore[arg-type]
        await settings_svc.get_job_defaults(session)
    yield


@pytest.fixture
async def client(db):
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def login(client: AsyncClient, username: str, password: str) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def superadmin(client):
    return await login(client, "superadmin", "superpw")


@pytest.fixture
async def admin(client):
    return await login(client, "admin", "adminpw")


@pytest.fixture
async def user(client):
    return await login(client, "user", "userpw")


@pytest.fixture
async def other(client, db):
    async with get_sessionmaker()() as session:
        await users_svc.create_local_user(
            session, username="other", password="otherpw", email="other@example.com", display_name="其他人"
        )
    return await login(client, "other", "otherpw")


REQUEST = {
    "title": "良率預測",
    "purpose": "用製程參數預測批次良率，提前調整參數。",
    "data_type": "TABULAR",
    "task_type": "regression",
    "data_scale": "medium",
    "requested_gpu": 0,
    "requested_cpu": 4,
    "requested_memory_mb": 8192,
    "requested_storage_mb": 10240,
    "proposed_slug": "yield-forecast",
    "members": [{"email": "other@example.com", "role": "member"}],
}
APPROVE = {
    "slug": "yield-forecast",
    "gpu_limit": 1,
    "cpu_limit": 4,
    "memory_limit_mb": 8192,
    "storage_quota_mb": 10240,
    "max_concurrent_jobs": 1,
}


async def make_project(client: AsyncClient, admin: dict, user: dict, slug: str = "yield-forecast", **overrides) -> dict:
    r = await client.post("/api/v1/project-requests", json={**REQUEST, "proposed_slug": slug}, headers=user)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    r = await client.post(
        f"/api/v1/project-requests/{rid}/approve", json={**APPROVE, "slug": slug, **overrides}, headers=admin
    )
    assert r.status_code == 201, r.text
    return r.json()


async def make_data_source(client: AsyncClient, user: dict, slug: str) -> dict:
    r = await client.post(
        f"/api/v1/projects/{slug}/data-sources",
        json={
            "name": "mes-export",
            "kind": "url",
            "url": "https://example.com/yield.csv",
            "headers": {"Authorization": "Bearer x"},
            "format": "csv",
            "default_spec": {"target": "yield_pct", "row_count": 5000},
        },
        headers=user,
    )
    assert r.status_code == 201, r.text
    return r.json()
