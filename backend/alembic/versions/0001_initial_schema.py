"""initial schema — all 12 tables from docs/DATABASE.md

Revision ID: 0001
Revises:
Create Date: 2026-10-15
"""

from __future__ import annotations

import app.models  # noqa: F401
from alembic import op
from app.db.base import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial revision materializes the ORM metadata directly; later revisions use autogenerate diffs.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
