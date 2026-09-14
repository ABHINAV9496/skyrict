"""Seed the HR-AI-004 workforce cost planning permission (SKY-93).

The L4 planning surface (``POST /api/v1/ai/hr/l4/*`` proxied to ai-agent plus
the core ``/api/v1/ai/hr/l4/payroll-base`` source endpoint) enforces
``erp.ai.invoke`` AND ``erp.hr.ai.planning``, mirroring the L2/L3 posture. This
key lets role grants distinguish who may run/share cost what-if scenarios
without granting the whole HR AI surface. Owner-only by design: owners pass via
the ``*`` wildcard grant and no org role is granted here.

This migration only seeds the key into ``core_permissions`` (same
``ON CONFLICT DO NOTHING`` pattern as 0049/0044/0030) - no schema, no extra
data beyond the catalog row.

Revision ID: 0052
Revises: 0051
Create Date: 2026-09-13
"""

from __future__ import annotations

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

# (key, description) pairs - order matters for a deterministic diff.
_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("erp.hr.ai.planning", "Plan workforce cost what-if scenarios"),
)


def upgrade() -> None:
    for key, description in _PERMISSIONS:
        op.execute(
            "INSERT INTO core_permissions (key, description) VALUES "
            f"('{key}', '{description}') "  # nosec B608
            "ON CONFLICT (key) DO NOTHING"
        )


def downgrade() -> None:
    for key, _ in _PERMISSIONS:
        op.execute(f"DELETE FROM core_permissions WHERE key = '{key}'")  # nosec B608
