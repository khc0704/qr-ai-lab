from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import forbidden, not_found
from app.db.base import utcnow
from app.models import Comment, Issue, ProjectRequest, User


async def list_for(session: AsyncSession, target_type: str, target_id: int) -> list[Comment]:
    rows = await session.execute(
        select(Comment)
        .where(Comment.target_type == target_type, Comment.target_id == target_id)
        .order_by(Comment.created_at, Comment.id)
    )
    return list(rows.scalars().all())


async def get(session: AsyncSession, target_type: str, target_id: int, comment_id: int) -> Comment:
    """A comment addressed through its thread; a comment of another thread is a 404, not a leak."""
    c = await session.get(Comment, comment_id)
    if c is None or c.target_type != target_type or c.target_id != target_id:
        raise not_found("COMMENT_NOT_FOUND", "找不到留言")
    return c


def keep_updated_at(row: Issue | ProjectRequest) -> None:
    """Pin `updated_at` to its current value for the next flush.

    `updated_at` on a thread means "content last edited" (the UI shows 「已編輯」 when it is later than
    `created_at`); bookkeeping updates such as the comment counter or a status change must not bump it.
    Listing the column explicitly in the UPDATE keeps SQLAlchemy from applying the `onupdate` default.
    """
    flag_modified(row, "updated_at")


async def add(
    session: AsyncSession, target_type: str, target_id: int, author_id: int | None, body: str, kind: str = "comment"
) -> Comment:
    now = utcnow()
    c = Comment(
        target_type=target_type,
        target_id=target_id,
        author_id=author_id,
        kind=kind,
        body=body,
        created_at=now,
        updated_at=now,
    )
    session.add(c)
    target = await session.get(Issue if target_type == "issue" else ProjectRequest, target_id)
    if target is not None and kind == "comment":
        target.comment_count = (target.comment_count or 0) + 1
        keep_updated_at(target)
    await session.flush()
    return c


async def update(session: AsyncSession, user: User, comment: Comment, body: str) -> Comment:
    """Author or admin rewrites a comment; system events are immutable. Commits."""
    if comment.kind != "comment":
        raise forbidden("COMMENT_NOT_EDITABLE", "系統訊息不能編輯")
    if not (user.is_admin or comment.author_id == user.id):
        raise forbidden("COMMENT_EDIT", "只有作者或管理員可以編輯留言")
    comment.body = body
    comment.updated_at = utcnow()
    await session.commit()
    return comment
