"""Add 'reversed' to erp_entry_status enum

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-02
"""

from __future__ import annotations

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE erp_entry_status ADD VALUE IF NOT EXISTS 'reversed'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values; rebuild needed.
    pass
