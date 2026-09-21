"""Conversation message attachments - metadata column for chat file persistence.

Adds a JSONB ``attachments`` column to ``ai_conversation_messages`` so file
metadata survives page reloads and conversation revisits (SKY-60 attachment
durability).  The column holds a list of per-attachment metadata dicts
``{id, name, type, size, storage_key}``; the raw bytes live in the attachment
storage backend (local/S3), never in Postgres - same storage-port pattern as
documents and avatars.

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "ai_conversation_messages",
        sa.Column(
            "attachments",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment=(
                "Metadata for files attached to this message "
                "(blobs in attachment object storage); never base64 content"
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_conversation_messages", "attachments")
