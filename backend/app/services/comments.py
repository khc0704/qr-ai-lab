from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment, Issue, ProjectRequest


async def list_for(session: AsyncSession, target_type: str, target_id: int) -> list[Comment]:
    rows = await session.execute(
        select(Comment)
        .where(Comment.target_type == target_type, Comment.target_id == target_id)
        .order_by(Comment.created_at, Comment.id)
    )
    return list(rows.scalars().all())


async def add(
    session: AsyncSession, target_type: str, target_id: int, author_id: int | None, body: str, kind: str = "comment"
) -> Comment:
    c = Comment(target_type=target_type, target_id=target_id, author_id=author_id, kind=kind, body=body)
    session.add(c)
    target = await session.get(Issue if target_type == "issue" else ProjectRequest, target_id)
    if target is not None and kind == "comment":
        target.comment_count = (target.comment_count or 0) + 1
    await session.flush()
    return c
