"""Add title_generated_at column for AI-generated conversation titles.

Tracks whether the AI title-generation service has already processed a
conversation.  When set, the title field contains the generated title
(replacing the truncated first-prompt fallback).

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "ai_conversations",
        sa.Column(
            "title_generated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the AI title was generated; NULL means not yet generated",
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_conversations", "title_generated_at")
