"""0029_finance_ai_extensions — add lines_json + explanation to ai_finance_suggestions.

Stores multi-line draft entries and the LLM's relationship explanation,
so every AI-generated draft can be audited and reviewed later (FIN-AI-001).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0029"
down_revision = "0028"


def upgrade() -> None:
    op.add_column(
        "ai_finance_suggestions",
        sa.Column("lines_json", JSONB(), nullable=True),
    )
    op.add_column(
        "ai_finance_suggestions",
        sa.Column("explanation", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_finance_suggestions", "explanation")
    op.drop_column("ai_finance_suggestions", "lines_json")
