"""Sessions v2 - status lifecycle, token families, trusted devices.

Replaces the boolean ``is_active`` with a ``status`` state machine
(active -> revoked/expired), adds ``token_family_id`` for rotation/reuse
detection, ``is_trusted`` for recognized devices, and ``expired_at`` for the
materialized expiry transition. Existing rows are backfilled: revoked where
``is_active`` was false, expired where ``expires_at`` has passed.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the sessions v2 columns, backfill status, and drop is_active."""
    op.add_column(
        "sessions",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
    )
    op.add_column(
        "sessions",
        sa.Column("token_family_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("is_trusted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "sessions",
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        """
        UPDATE sessions
        SET status = 'expired', expired_at = expires_at
        WHERE expires_at < now() AND status = 'active'
        """
    )
    op.execute(
        """
        UPDATE sessions
        SET status = 'revoked'
        WHERE is_active = false AND status = 'active'
        """
    )

    op.drop_column("sessions", "is_active")

    op.create_index("ix_sessions_status", "sessions", ["status"])
    op.create_index("ix_sessions_token_family_id", "sessions", ["token_family_id"])


def downgrade() -> None:
    """Restore is_active from status and drop the v2 columns."""
    op.add_column(
        "sessions",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.execute("UPDATE sessions SET is_active = (status = 'active') WHERE status <> 'active'")
    op.drop_index("ix_sessions_token_family_id", table_name="sessions")
    op.drop_index("ix_sessions_status", table_name="sessions")
    op.drop_column("sessions", "expired_at")
    op.drop_column("sessions", "is_trusted")
    op.drop_column("sessions", "token_family_id")
    op.drop_column("sessions", "status")
