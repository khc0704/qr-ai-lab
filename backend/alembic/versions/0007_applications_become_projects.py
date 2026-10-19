"""Data: every open application (project_requests without a project) becomes a pending project; legacy personal
workspaces (kind=personal) are archived (the shared tool pool replaces them)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-20
"""

from __future__ import annotations

import re

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

STATUS = {"submitted": "pending", "in_review": "in_review", "rejected": "rejected"}


def _slug(title: str, proposed: str | None, taken: set[str], request_id: int) -> str:
    base = proposed or re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-")
    if len(base) < 2:
        base = f"req-{request_id}"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    taken.add(slug)
    return slug


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    taken = set(bind.execute(sa.text("SELECT slug FROM projects")).scalars())
    rows = bind.execute(
        sa.text(
            "SELECT id, applicant_id, title, purpose, data_type, task_type, requested_cpu, requested_memory_mb, "
            "requested_storage_mb, proposed_slug, status FROM project_requests "
            "WHERE project_id IS NULL AND status IN ('submitted', 'in_review', 'rejected')"
        )
    ).mappings()
    for r in rows:
        slug = _slug(r["title"], r["proposed_slug"], taken, r["id"])
        bind.execute(
            sa.text(
                "INSERT INTO projects (slug, name, description, data_type, task_type, status, kind, owner_id, "
                "request_id, gpu_limit, cpu_limit, memory_limit_mb, storage_quota_mb, storage_used_bytes, "
                "max_concurrent_jobs, created_at, updated_at) VALUES (:slug, :name, :description, :data_type, "
                ":task_type, :status, 'standard', :owner_id, :request_id, 0, :cpu, :mem, :storage, 0, 1, "
                "CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6))"
            ),
            {
                "slug": slug,
                "name": r["title"][:120],
                "description": r["purpose"],
                "data_type": r["data_type"],
                "task_type": r["task_type"],
                "status": STATUS[r["status"]],
                "owner_id": r["applicant_id"],
                "request_id": r["id"],
                "cpu": r["requested_cpu"],
                "mem": r["requested_memory_mb"],
                "storage": r["requested_storage_mb"],
            },
        )
        pid = bind.execute(sa.text("SELECT id FROM projects WHERE slug = :slug"), {"slug": slug}).scalar_one()
        bind.execute(
            sa.text("UPDATE project_requests SET project_id = :pid, proposed_slug = :slug WHERE id = :rid"),
            {"pid": pid, "slug": slug, "rid": r["id"]},
        )
        bind.execute(
            sa.text(
                "INSERT INTO project_members (project_id, user_id, role, added_by_id, created_at) "
                "VALUES (:pid, :uid, 'owner', :uid, CURRENT_TIMESTAMP(6))"
            ),
            {"pid": pid, "uid": r["applicant_id"]},
        )
    bind.execute(
        sa.text(
            "UPDATE projects SET status = 'archived', archived_at = CURRENT_TIMESTAMP(6) "
            "WHERE kind = 'personal' AND status <> 'archived'"
        )
    )


def downgrade() -> None:
    # The pending projects stay; nothing to undo safely.
    pass
