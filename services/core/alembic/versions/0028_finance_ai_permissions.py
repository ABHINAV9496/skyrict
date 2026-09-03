"""Seed the finance AI permission keys (FIN-AI-001 phase 5).

The AI account-suggestion / draft / anomaly-narration / reminder endpoints
are gated by ``erp.finance.ai.read`` (generation) and
``erp.finance.ai.write`` (persisting AI output). This seeds them into the
runtime catalog (``core_permissions``) exactly like the ``erp.hr.ai.*`` keys in
migration 0021/0023. The owner ``*`` wildcard covers them; specific roles
grant them via the platform's role-grant tooling.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_KEYS = (
    ("erp.finance.ai.read", "Generate AI finance suggestions, drafts, and narrations"),
    ("erp.finance.ai.write", "Persist AI finance output (applied drafts, reminders)"),
)


def upgrade() -> None:
    for key, description in _KEYS:
        op.execute(
            "INSERT INTO core_permissions (key, description) VALUES "
            f"('{key}', '{description}') ON CONFLICT (key) DO NOTHING"  # nosec B608
        )


def downgrade() -> None:
    for key, _ in _KEYS:
        op.execute(f"DELETE FROM core_permissions WHERE key = '{key}'")  # nosec B608
