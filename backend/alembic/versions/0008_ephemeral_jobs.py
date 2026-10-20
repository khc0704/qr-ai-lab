"""jobs.ephemeral: one-off inference runs (shown once, no artifacts, hidden from lists, expire with their outputs)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-20
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":  # dev / test databases are created from the models
        return
    op.add_column("jobs", sa.Column("ephemeral", sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    op.drop_column("jobs", "ephemeral")
