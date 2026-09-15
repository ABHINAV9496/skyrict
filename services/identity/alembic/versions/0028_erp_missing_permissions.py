"""Register ERP permission keys missing from identity's catalog.

Core enforces several ``erp.*`` keys at API endpoints (approval router,
inventory adjust/cost/suppliers, reports, HR AI eval/management, AI
coaching/guardian agents) that identity's catalog never contained, so they
could never be granted to a role - features were locked out for all roles
except the ``*`` wildcard owner. This migration registers the keys and grants
them to system roles per the RBAC design:

- ``organization_admin`` -> all fourteen new keys
- ``department_manager`` -> ``erp.reports.read``
- ``auditor`` -> ``erp.reports.read``
- ``standard_user`` / ``tenant_owner`` / ``employee_self_service`` -> unchanged

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-15
"""

from __future__ import annotations

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("erp.finance.approve", "Approve, reject, or cancel journal-entry-level payment item requests"),
    ("erp.inventory.adjust", "Create and edit inventory adjustments"),
    ("erp.inventory.adjust.approve", "Approve above-threshold inventory adjustments"),
    ("erp.inventory.cost", "View and manage inventory costing data"),
    ("erp.inventory.suppliers.read", "View supplier records in inventory"),
    ("erp.inventory.suppliers.write", "Create and edit supplier records in inventory"),
    ("erp.reports.create", "Create and export reports"),
    ("erp.reports.read", "View reports"),
    ("erp.hr.ai.eval", "Run and view HR AI performance evaluations"),
    ("erp.hr.ai.management", "Manage HR AI configuration and approvals"),
    ("erp.ai.coaching.read", "View AI coaching agent outputs"),
    ("erp.ai.coaching.review", "Review and act on AI coaching agent outputs"),
    ("erp.ai.guardian.read", "View AI guardian agent outputs"),
    ("erp.ai.guardian.review", "Review and act on AI guardian agent outputs"),
)

_ALL = tuple(key for key, _ in _PERMISSIONS)


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

    _append_permissions(("organization_admin",), _ALL)
    _append_permissions(("department_manager", "auditor"), ("erp.reports.read",))


def downgrade() -> None:
    for key in _ALL:
        op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{key}')")
        op.execute(f"DELETE FROM permissions WHERE key = '{key}'")
