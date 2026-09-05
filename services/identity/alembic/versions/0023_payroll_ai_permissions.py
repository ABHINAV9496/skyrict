"""Add erp.payroll.ai.* permission keys (HR-AUT-001 payroll automation).

Ticket HR-AUT-001 (docs/modules/skyrict-ai/hr-payroll-ai-features.md §15):
the four ``erp.payroll.ai.*`` keys gate the payroll automation surface
(batch runs, schedules, notifications, tick) at the core edge. Core's
``core_permissions`` catalog already carries these keys (migration 0026);
this migration mirrors them into identity's ``permissions`` table so role
grants stay portable across the platform (same precedent as 0020 for
``erp.hr.ai.*``).

Grant matrix:
  - ``erp.payroll.ai.read``    -> organization_admin, auditor (read-only ops view)
  - ``erp.payroll.ai.run``     -> organization_admin
  - ``erp.payroll.ai.notify``  -> organization_admin
  - ``erp.payroll.ai.approve`` -> organization_admin

Tenant owners pass via the ``*`` wildcard grant (mirroring 0020 / 0022).

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-31
"""

from __future__ import annotations

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

# (key, description) - mirrors identity.core.permissions catalog entries.
_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("erp.payroll.ai.read", "View payroll automation batch runs and progress"),
    ("erp.payroll.ai.run", "Start, poll, and resume payroll automation batch runs"),
    ("erp.payroll.ai.notify", "Manage payroll automation notifications"),
    ("erp.payroll.ai.approve", "Approve payroll automation outcomes"),
)

# Roles granted each key when migrating (owner is covered by its "*" grant).
_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("erp.payroll.ai.read", ("organization_admin", "auditor")),
    ("erp.payroll.ai.run", ("organization_admin",)),
    ("erp.payroll.ai.notify", ("organization_admin",)),
    ("erp.payroll.ai.approve", ("organization_admin",)),
)


def _append_permissions(role_names: tuple[str, ...], permission_keys: tuple[str, ...]) -> None:
    """Append missing keys without disturbing tenant-specific role grants."""
    for key in permission_keys:
        op.execute(
            "UPDATE roles SET permissions = array_append(permissions, "
            f"'{key}') WHERE name IN ({', '.join(repr(name) for name in role_names)}) "
            f"AND NOT ('{key}' = ANY(permissions))"
        )


def upgrade() -> None:
    for key, description in _PERMISSIONS:
        op.execute(
            "INSERT INTO permissions (key, description) VALUES "
            f"('{key}', '{description}') ON CONFLICT (key) DO NOTHING"
        )

    for key, role_names in _GRANTS:
        _append_permissions(role_names, (key,))


def downgrade() -> None:
    all_keys = tuple(key for key, _ in _PERMISSIONS)
    for key in all_keys:
        op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{key}')")
        op.execute(f"DELETE FROM permissions WHERE key = '{key}'")
