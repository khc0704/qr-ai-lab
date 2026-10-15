"""Operational commands: uv run python -m app.cli <command>

init-db                 create all tables (dev/SQLite; production uses `alembic upgrade head`)
seed                    seed `superadmin` / `admin` / `user` accounts and default settings (idempotent)
create-user             --username --password --email [--role superadmin|admin|user] [--name ...]
set-role                --username --role superadmin|admin|user   (bootstrap the first superadmin)
set-password            --username --password
model-zoo               list required pretrained weights and whether they are present
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.config import get_settings


async def _init_db() -> None:
    import app.models  # noqa: F401
    from app.db.base import Base
    from app.db.session import get_engine

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("tables created")


async def _seed() -> None:
    from app.db.session import get_sessionmaker
    from app.services import settings as settings_svc
    from app.services import users as users_svc

    s = get_settings()
    async with get_sessionmaker()() as session:
        created = await users_svc.seed_users(
            session, s.seed_admin_password, s.seed_user_password, s.seed_superadmin_password
        )
        pool = await settings_svc.get_resource_pool(session)
        await settings_svc.get_job_defaults(session)
    print(f"created users: {created or 'none (already present)'}; resource pool: {pool.model_dump()}")


async def _create_user(a: argparse.Namespace) -> None:
    from app.db.session import get_sessionmaker
    from app.services import users as users_svc

    async with get_sessionmaker()() as session:
        if await users_svc.get_by_username(session, a.username):
            print("user exists", file=sys.stderr)
            sys.exit(1)
        u = await users_svc.create_local_user(
            session, username=a.username, password=a.password, email=a.email, display_name=a.name, role=a.role
        )
        print(f"created user id={u.id} username={u.username} role={u.role}")


async def _set_role(a: argparse.Namespace) -> None:
    from app.db.session import get_sessionmaker
    from app.services import users as users_svc

    async with get_sessionmaker()() as session:
        u = await users_svc.get_by_username(session, a.username)
        if u is None:
            print("no such user (Keycloak users exist after their first login)", file=sys.stderr)
            sys.exit(1)
        u.role = a.role
        await session.commit()
        print(f"{u.username}: role={u.role}")


async def _set_password(a: argparse.Namespace) -> None:
    from app.core.security import hash_password
    from app.db.session import get_sessionmaker
    from app.services import users as users_svc

    async with get_sessionmaker()() as session:
        u = await users_svc.get_by_username(session, a.username)
        if u is None:
            print("no such user", file=sys.stderr)
            sys.exit(1)
        u.password_hash = hash_password(a.password)
        await session.commit()
        print("password updated")


def _model_zoo(verify: bool) -> None:
    from app.services.node import model_zoo_status

    root = get_settings().zoo_root
    print(f"MODEL_ZOO_ROOT = {root}")
    for e in model_zoo_status(verify=verify):
        state = "present" if e.present else "MISSING"
        extra = f" sha256={e.sha256_actual[:12]}…" if e.sha256_actual else ""
        print(f"  [{state:7}] {e.id:20} {e.file:34} family={e.family} license={e.license}{extra}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="app.cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    sub.add_parser("seed")
    cu = sub.add_parser("create-user")
    cu.add_argument("--username", required=True)
    cu.add_argument("--password", required=True)
    cu.add_argument("--email", required=True)
    cu.add_argument("--role", default="user", choices=["superadmin", "admin", "user"])
    cu.add_argument("--name", default=None)
    sr = sub.add_parser("set-role")
    sr.add_argument("--username", required=True)
    sr.add_argument("--role", required=True, choices=["superadmin", "admin", "user"])
    sp = sub.add_parser("set-password")
    sp.add_argument("--username", required=True)
    sp.add_argument("--password", required=True)
    mz = sub.add_parser("model-zoo")
    mz.add_argument("--verify", action="store_true", help="compute sha256 of present files")
    a = p.parse_args(argv)
    if a.cmd == "init-db":
        asyncio.run(_init_db())
    elif a.cmd == "seed":
        asyncio.run(_seed())
    elif a.cmd == "create-user":
        asyncio.run(_create_user(a))
    elif a.cmd == "set-password":
        asyncio.run(_set_password(a))
    elif a.cmd == "set-role":
        asyncio.run(_set_role(a))
    elif a.cmd == "model-zoo":
        _model_zoo(a.verify)


if __name__ == "__main__":
    main()
