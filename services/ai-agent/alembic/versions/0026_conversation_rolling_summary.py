"""Add rolling summary columns for long conversation compaction (SKY-100).

Long conversations can exceed the supervisor's bounded context window even
after the 20-message history cap. These columns store a compact rolling
summary of the conversation *before* the recent window so the supervisor
prompt can inject key older context within budget:

- ``summary_text`` - the LLM-generated summary of pre-window messages;
- ``summary_updated_at`` - when the summary was last regenerated, used to
  detect staleness (regeneration is triggered in the background).

The columns are deliberately EXCLUDED from ``_conversation_to_dict``: the
summary is an internal context-compaction detail and must never surface to
the conversation UI/API.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "ai_conversations",
        sa.Column(
            "summary_text",
            sa.Text(),
            nullable=True,
            comment="Rolling summary of pre-window conversation messages; NULL until first regeneration",
        ),
    )
    op.add_column(
        "ai_conversations",
        sa.Column(
            "summary_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When summary_text was last regenerated; NULL means never",
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_conversations", "summary_updated_at")
    op.drop_column("ai_conversations", "summary_text")
