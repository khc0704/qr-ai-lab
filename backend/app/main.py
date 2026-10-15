"""FastAPI app factory. Run: uv run uvicorn app.main:app --reload"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.session import get_engine, get_sessionmaker
from app.routers import (
    admin,
    artifacts,
    auth,
    catalog,
    health,
    internal,
    issues,
    jobs,
    project_requests,
    projects,
    users,
)

log = get_logger("app")


async def init_dev_schema() -> None:
    """Dev/test convenience: create tables and seed accounts/settings. Production uses Alembic + the CLI."""
    import app.models  # noqa: F401 - populate metadata
    from app.db.base import Base
    from app.services import settings as settings_svc
    from app.services import users as users_svc

    s = get_settings()
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with get_sessionmaker()() as session:
        created = await users_svc.seed_users(session, s.seed_admin_password, s.seed_user_password)
        await settings_svc.get_resource_pool(session)
        await settings_svc.get_job_defaults(session)
    if created:
        log.warning("seeded local accounts", users=created, note="change the passwords via SEED_*_PASSWORD or the CLI")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging(s.log_level)
    s.data_root.mkdir(parents=True, exist_ok=True)
    if s.app_env != "prod" and s.is_sqlite:
        await init_dev_schema()
    log.info(
        "backend ready", env=s.app_env, auth_mode=s.auth_mode, db=s.database_url.split("://")[0], runner=s.job_runner
    )
    yield
    await get_engine().dispose()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="QR AI Lab API", version="0.1.0", lifespan=lifespan, docs_url="/docs", openapi_url="/openapi.json"
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
    )
    prefix = "/api/v1"
    for r in (auth, users, catalog, issues, project_requests, projects, jobs, artifacts, admin, internal):
        app.include_router(r.router, prefix=prefix)
    app.include_router(health.router)
    return app


app = create_app()
