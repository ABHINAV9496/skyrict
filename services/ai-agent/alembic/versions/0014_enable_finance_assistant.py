"""Enable the finance_assistant supervisor leaf (FIN-AI-001).

The Finance Assistant backend now exists (FinanceAssistantDelegator +
HttpFinanceGateway), so this migration flips the ``enabled`` flag seeded
disabled in 0009.
"""

from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE agent_registry SET enabled = true WHERE name = 'finance_assistant'")


def downgrade() -> None:
    op.execute("UPDATE agent_registry SET enabled = false WHERE name = 'finance_assistant'")
