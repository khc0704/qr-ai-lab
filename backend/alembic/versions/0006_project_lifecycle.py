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


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":  # dev / test databases are created from the models
        return
    op.add_column("projects", sa.Column("completed_at", sa.DateTime(timezone=False), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    op.drop_column("projects", "completed_at")
