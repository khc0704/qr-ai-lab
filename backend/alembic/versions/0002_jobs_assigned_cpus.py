"""add jobs.assigned_cpus (logical CPUs granted to a job)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 runs create_all from the current models, so a fresh database already has this column.
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("jobs")}
    if "assigned_cpus" not in cols:
        op.add_column("jobs", sa.Column("assigned_cpus", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "assigned_cpus")
