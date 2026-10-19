from __future__ import annotations

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import forbidden, not_found
from app.db.base import utcnow
from app.models import Comment, Issue, Project, User
from app.schemas.issue import IssueCreate, IssueUpdate
from app.services import audit, comments


async def _project_id(session: AsyncSession, slug: str | None) -> int | None:
    if not slug:
        return None
    p = (await session.execute(select(Project).where(Project.slug == slug))).scalar_one_or_none()
    if p is None:
        raise not_found("PROJECT_NOT_FOUND", f"找不到專案 {slug}")
    return p.id


async def slug_map(session: AsyncSession, issues: list[Issue]) -> dict[int, str]:
    ids = {i.project_id for i in issues if i.project_id}
    if not ids:
        return {}
    rows = (await session.execute(select(Project.id, Project.slug).where(Project.id.in_(ids)))).all()
    return {pid: slug for pid, slug in rows}


async def list_issues(
    session: AsyncSession,
    *,
    status: str | None,
    type_: str | None,
    author_id: int | None,
    q: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Issue], int]:
    stmt = select(Issue)
    if status:
        stmt = stmt.where(Issue.status == status)
    if type_:
        stmt = stmt.where(Issue.type == type_)
    if author_id:
        stmt = stmt.where(Issue.author_id == author_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Issue.title.like(like), Issue.body.like(like)))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(Issue.created_at.desc(), Issue.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total


async def get(session: AsyncSession, issue_id: int) -> Issue:
    issue = await session.get(Issue, issue_id)
    if issue is None:
        raise not_found("ISSUE_NOT_FOUND", "找不到問題")
    return issue


async def create(session: AsyncSession, user: User, body: IssueCreate) -> Issue:
    # created_at == updated_at on a fresh thread: the UI shows 「已編輯」 only once they differ.
    now = utcnow()
    issue = Issue(
        type=body.type,
        title=body.title,
        body=body.body,
        author_id=user.id,
        project_id=await _project_id(session, body.project_slug),
        created_at=now,
        updated_at=now,
    )
    session.add(issue)
    await session.commit()
    return await get(session, issue.id)


async def update(session: AsyncSession, user: User, issue: Issue, body: IssueUpdate) -> Issue:
    if not (user.is_admin or issue.author_id == user.id):
        raise forbidden("ISSUE_EDIT", "只有作者或管理員可以編輯")
    if body.type is not None:
        issue.type = body.type
    if body.title is not None:
        issue.title = body.title
    if body.body is not None:
        issue.body = body.body
    if body.project_slug is not None:
        issue.project_id = await _project_id(session, body.project_slug or None)
    if body.assignee_id is not None:
        if not user.is_admin:
            raise forbidden("ISSUE_ASSIGN", "只有管理員可以指派")
        assignee = await session.get(User, body.assignee_id)
        if assignee is None:
            raise not_found("USER_NOT_FOUND", "找不到使用者")
        issue.assignee_id = assignee.id
        await comments.add(
            session,
            "issue",
            issue.id,
            None,
            f"{user.display_name or user.username} 將此問題指派給 {assignee.display_name or assignee.username}",
            kind="system",
        )
    await session.commit()
    return await get(session, issue.id)


async def close(session: AsyncSession, admin: User, issue: Issue, note: str) -> Issue:
    issue.status = "closed"
    issue.resolution_note = note
    issue.closed_by_id = admin.id
    issue.closed_at = utcnow()
    comments.keep_updated_at(issue)  # a status change is not a content edit
    await comments.add(
        session, "issue", issue.id, None, f"{admin.display_name or admin.username} 關閉了此問題：{note}", kind="system"
    )
    await session.commit()
    return await get(session, issue.id)


async def reopen(session: AsyncSession, actor: User, issue: Issue) -> Issue:
    if not (actor.is_admin or issue.author_id == actor.id):
        raise forbidden("ISSUE_REOPEN", "只有作者或管理員可以重開")
    issue.status = "open"
    issue.closed_at = None
    issue.closed_by_id = None
    comments.keep_updated_at(issue)
    await comments.add(
        session, "issue", issue.id, None, f"{actor.display_name or actor.username} 重開了此問題", kind="system"
    )
    await session.commit()
    return await get(session, issue.id)


async def delete(session: AsyncSession, actor: User, issue: Issue) -> None:
    """Moderators remove a thread together with its comments (polymorphic comments have no FK)."""
    await session.execute(sql_delete(Comment).where(Comment.target_type == "issue", Comment.target_id == issue.id))
    await audit.record(
        session, actor.id, "issue.delete", "issue", issue.id, {"title": issue.title, "author_id": issue.author_id}
    )
    await session.delete(issue)
    await session.commit()
