"""projects.kind (standard | personal): personal workspaces host the preprocessing / analysis tool jobs

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("projects")}
    if "kind" not in cols:
        op.add_column("projects", sa.Column("kind", sa.String(length=16), nullable=False, server_default="standard"))


def downgrade() -> None:
    op.drop_column("projects", "kind")
