"""projects.completed_at: projects now carry the application lifecycle (pending → in_review → active | rejected,
active → completed → archived); the kind `shared` tool pool replaces per-user personal workspaces

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # 0001 is create_all from the current models: a database created today already has this column (MariaDB
    # included), only one created before this revision needs it added.
    if "completed_at" not in _columns("projects"):
        op.add_column("projects", sa.Column("completed_at", sa.DateTime(timezone=False), nullable=True))


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    if "completed_at" in _columns("projects"):
        op.drop_column("projects", "completed_at")
