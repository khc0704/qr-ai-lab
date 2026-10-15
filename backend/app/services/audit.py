from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record(
    session: AsyncSession,
    actor_id: int | None,
    action: str,
    target_type: str,
    target_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    row = AuditLog(actor_id=actor_id, action=action, target_type=target_type, target_id=target_id, payload=payload)
    session.add(row)
    await session.flush()
    return row


async def list_recent(session: AsyncSession, limit: int = 50, offset: int = 0) -> tuple[list[AuditLog], int]:
    from sqlalchemy import func

    total = (await session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    rows = (
        (
            await session.execute(
                select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total
