"""uploads.claimed_by_job_id → ON DELETE SET NULL (deleting a job must not fail on its claimed upload row)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

FK_NAME = "fk_uploads_claimed_by_job_id_jobs"


def _current_fk(bind: sa.engine.Connection) -> dict | None:
    for fk in sa.inspect(bind).get_foreign_keys("uploads"):
        if fk["referred_table"] == "jobs" and fk["constrained_columns"] == ["claimed_by_job_id"]:
            return fk
    return None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":  # dev / test databases are created from the models (0001 = create_all)
        return
    fk = _current_fk(bind)
    if fk is not None:
        if (fk.get("options") or {}).get("ondelete", "").upper() == "SET NULL":
            return
        op.drop_constraint(fk["name"], "uploads", type_="foreignkey")
    op.create_foreign_key(FK_NAME, "uploads", "jobs", ["claimed_by_job_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    fk = _current_fk(bind)
    if fk is not None:
        op.drop_constraint(fk["name"], "uploads", type_="foreignkey")
    op.create_foreign_key(FK_NAME, "uploads", "jobs", ["claimed_by_job_id"], ["id"])
