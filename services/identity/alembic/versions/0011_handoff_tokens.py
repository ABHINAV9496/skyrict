"""Handoff tokens — single-use onboarding state carriers.

Adds the ``handoff_tokens`` table: only the SHA-256 hash of each token is
stored (raw value returned once at issue), redemption is atomic via
``consumed_at``, and the payload lets the wizard and BFF resume the exact
in-flight step.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the handoff_tokens table."""
    op.create_table(
        "handoff_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column(
            "token_hash", sa.String(length=64), nullable=False
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_handoff_tokens_token_hash", "handoff_tokens", ["token_hash"], unique=True)
    op.create_index("ix_handoff_tokens_purpose", "handoff_tokens", ["purpose"])
    op.create_index("ix_handoff_tokens_tenant_id", "handoff_tokens", ["tenant_id"])


def downgrade() -> None:
    """Drop the handoff_tokens table."""
    op.drop_index("ix_handoff_tokens_tenant_id", table_name="handoff_tokens")
    op.drop_index("ix_handoff_tokens_purpose", table_name="handoff_tokens")
    op.drop_index("ix_handoff_tokens_token_hash", table_name="handoff_tokens")
    op.drop_table("handoff_tokens")
