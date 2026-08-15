"""Add the users.avatar_url column.

Stores a tenant-scoped relative path (``{user_id}/{filename}``) pointing at a
normalized WebP avatar in avatar storage. ``NULL`` means the user has no photo
and clients fall back to initials.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the nullable users.avatar_url column."""
    op.add_column("users", sa.Column("avatar_url", sa.String(length=512), nullable=True))


def downgrade() -> None:
    """Drop the users.avatar_url column."""
    op.drop_column("users", "avatar_url")
