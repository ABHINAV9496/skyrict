"""Add erp.hr.ai.planning permission key (HR-AI-004 workforce cost planning).

Ticket SKY-93 (docs/modules/skyrict-ai/hr-ai-l4-planning.md): the L4 what-if
planning surface - payroll-base reads, scenario run/share/compare, and the
finance budget-draft export - is gated by ``erp.hr.ai.planning``. Core's
``core_permissions`` catalog carries the same key (migration 0052); this
migration mirrors it into identity's ``permissions`` table so role grants stay
portable across the platform (same precedent as 0020 for ``erp.hr.ai.*`` and
0023 for ``erp.payroll.ai.*``).

Grant matrix:
  - owner only. No org role is granted the key here; tenant owners pass via
    the ``*`` wildcard grant, so planning stays a platform-level capability
    until a tenant explicitly grants it to a role.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-13
"""

from __future__ import annotations

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

# (key, description) - mirrors identity.core.permissions catalog entries.
_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("erp.hr.ai.planning", "Plan workforce cost what-if scenarios"),
)


def upgrade() -> None:
    for key, description in _PERMISSIONS:
        op.execute(
            "INSERT INTO permissions (key, description) VALUES "
            f"('{key}', '{description}') ON CONFLICT (key) DO NOTHING"
        )


def downgrade() -> None:
    for key, _ in _PERMISSIONS:
        op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{key}')")
        op.execute(f"DELETE FROM permissions WHERE key = '{key}'")
