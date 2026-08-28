"""HR Copilot agent registry seed (HR-AI-001, spec §9 feature 5).

The HR Copilot owns no new tables - it grounds answers in core's existing L1
aggregate endpoints and the tenant leave policy, audited via the existing
``ai_audit_log`` (vocabulary: ``ai.hr.copilot.exchange``). This migration only
registers the agent so request-time resolution (``module -> enabled``) can
discover and gate it (``agent_registry`` docstring: rows are operator/
migration-managed, never tenant-owned).

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_AGENT_NAME = "hr_copilot"
_AGENT_MODULE = "ai_agent.features.hr_copilot.engine"


def upgrade() -> None:
    op.execute(
        "INSERT INTO agent_registry (name, module, enabled) VALUES "
        f"('{_AGENT_NAME}', '{_AGENT_MODULE}', true) "
        "ON CONFLICT (name) DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        f"DELETE FROM agent_registry WHERE name = '{_AGENT_NAME}'"
    )
