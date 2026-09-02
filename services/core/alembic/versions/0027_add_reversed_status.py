"""Add 'reversed' to erp_entry_status enum

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-02
"""

from __future__ import annotations

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE erp_entry_status ADD VALUE IF NOT EXISTS 'reversed'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values; rebuild needed.
    pass
