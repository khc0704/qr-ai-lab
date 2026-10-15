"""jobs.requested_gpu_memory_mb (share a GPU by VRAM) + resource_samples (usage history)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 runs create_all from the current models, so a fresh database already has both.
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("jobs")}
    if "requested_gpu_memory_mb" not in cols:
        op.add_column("jobs", sa.Column("requested_gpu_memory_mb", sa.Integer(), nullable=True))
    if "resource_samples" in insp.get_table_names():
        return
    op.create_table(
        "resource_samples",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("sampled_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_resource_samples_sampled_at", "resource_samples", ["sampled_at"])


def downgrade() -> None:
    op.drop_index("ix_resource_samples_sampled_at", table_name="resource_samples")
    op.drop_table("resource_samples")
    op.drop_column("jobs", "requested_gpu_memory_mb")
