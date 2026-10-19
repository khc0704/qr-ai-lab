from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.errors import conflict
from app.core.permissions import role_has
from app.models import User
from app.routers import _serialize as ser
from app.schemas.common import Ok, Page
from app.schemas.issue import (
    CommentCreate,
    CommentRead,
    CommentUpdate,
    IssueClose,
    IssueCreate,
    IssueRead,
    IssueUpdate,
)
from app.services import comments as comments_svc
from app.services import issues as issues_svc

router = APIRouter(prefix="/issues", tags=["issues"])
Moderator = Annotated[User, Depends(require_perm("issues.moderate"))]


@router.get("", response_model=Page[IssueRead])
async def list_issues(
    session: DbSession,
    user: CurrentUser,
    status: str | None = None,
    type: str | None = None,
    mine: bool = False,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Page[IssueRead]:
    rows, total = await issues_svc.list_issues(
        session, status=status, type_=type, author_id=user.id if mine else None, q=q, page=page, page_size=page_size
    )
    return Page(items=await ser.issues(session, rows), total=total, page=page, page_size=page_size)


@router.post("", response_model=IssueRead, status_code=201)
async def create_issue(body: IssueCreate, session: DbSession, user: CurrentUser) -> IssueRead:
    return (await ser.issues(session, [await issues_svc.create(session, user, body)]))[0]


@router.get("/{issue_id}", response_model=IssueRead)
async def get_issue(issue_id: int, session: DbSession, _: CurrentUser) -> IssueRead:
    return (await ser.issues(session, [await issues_svc.get(session, issue_id)]))[0]


@router.patch("/{issue_id}", response_model=IssueRead)
async def update_issue(issue_id: int, body: IssueUpdate, session: DbSession, user: CurrentUser) -> IssueRead:
    issue = await issues_svc.get(session, issue_id)
    return (await ser.issues(session, [await issues_svc.update(session, user, issue, body)]))[0]


@router.get("/{issue_id}/comments", response_model=list[CommentRead])
async def list_comments(issue_id: int, session: DbSession, _: CurrentUser) -> list[CommentRead]:
    await issues_svc.get(session, issue_id)
    return [CommentRead.model_validate(c) for c in await comments_svc.list_for(session, "issue", issue_id)]


@router.post("/{issue_id}/comments", response_model=CommentRead, status_code=201)
async def add_comment(issue_id: int, body: CommentCreate, session: DbSession, user: CurrentUser) -> CommentRead:
    """Anyone may reply while the thread is open; once an admin closed it, only moderators can add to it."""
    issue = await issues_svc.get(session, issue_id)
    if issue.status == "closed" and not role_has(user.role, "issues.moderate"):
        raise conflict("ISSUE_CLOSED", "討論已關閉，只有管理員可以留言")
    c = await comments_svc.add(session, "issue", issue_id, user.id, body.body)
    await session.commit()
    return CommentRead.model_validate(c)


@router.patch("/{issue_id}/comments/{comment_id}", response_model=CommentRead, summary="編輯留言（作者或 admin）")
async def update_comment(
    issue_id: int, comment_id: int, body: CommentUpdate, session: DbSession, user: CurrentUser
) -> CommentRead:
    """Rewrite a comment's Markdown body. Only its author or an admin may; system events are immutable."""
    await issues_svc.get(session, issue_id)
    c = await comments_svc.get(session, "issue", issue_id, comment_id)
    return CommentRead.model_validate(await comments_svc.update(session, user, c, body.body))


@router.delete("/{issue_id}", response_model=Ok, summary="刪除討論串與留言（admin）")
async def delete_issue(issue_id: int, session: DbSession, admin: Moderator) -> Ok:
    await issues_svc.delete(session, admin, await issues_svc.get(session, issue_id))
    return Ok()


@router.post("/{issue_id}/close", response_model=IssueRead, summary="關閉（admin）")
async def close_issue(issue_id: int, body: IssueClose, session: DbSession, admin: Moderator) -> IssueRead:
    issue = await issues_svc.get(session, issue_id)
    return (await ser.issues(session, [await issues_svc.close(session, admin, issue, body.resolution_note)]))[0]


@router.post("/{issue_id}/reopen", response_model=IssueRead)
async def reopen_issue(issue_id: int, session: DbSession, user: CurrentUser) -> IssueRead:
    issue = await issues_svc.get(session, issue_id)
    return (await ser.issues(session, [await issues_svc.reopen(session, user, issue)]))[0]
