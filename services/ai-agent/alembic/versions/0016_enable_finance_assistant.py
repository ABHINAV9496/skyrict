"""Enable the finance_assistant agent in agent_registry (SKY-63).

The Finance Assistant backend (``features/finance``) now reads live, permission
scoped finance data through core's ``/api/v1/finance`` endpoints. Flipping the
registry row to ``enabled`` unlocks streaming responses for the leave in the
supervisor shell chat.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-03
"""

from __future__ import annotations

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None

_AGENT_NAME = "finance_assistant"


def upgrade() -> None:
    op.execute(f"UPDATE agent_registry SET enabled = true WHERE name = '{_AGENT_NAME}'")


def downgrade() -> None:
    op.execute(f"UPDATE agent_registry SET enabled = false WHERE name = '{_AGENT_NAME}'")
