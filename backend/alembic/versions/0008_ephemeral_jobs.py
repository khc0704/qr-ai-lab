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


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # 0001 is create_all from the current models: a database created today already has this column (MariaDB
    # included), only one created before this revision needs it added.
    if "ephemeral" not in _columns("jobs"):
        op.add_column("jobs", sa.Column("ephemeral", sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    if "ephemeral" in _columns("jobs"):
        op.drop_column("jobs", "ephemeral")
