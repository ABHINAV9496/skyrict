"""Register Phase-1 ERP permissions and grant them to system roles.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-13
"""

from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("erp.crm.read", "View CRM leads, opportunities, and customers"),
    ("erp.crm.write", "Create and update CRM leads, opportunities, and customers"),
    ("erp.sales.read", "View sales orders"),
    ("erp.sales.write", "Create and update sales orders"),
    ("erp.sales.approve", "Approve sales orders"),
    ("erp.inventory.read", "View inventory and stock levels"),
    ("erp.inventory.write", "Create and update inventory records"),
    ("erp.inventory.approve", "Approve inventory adjustments and transfers"),
    ("erp.finance.read", "View finance and accounting records"),
    ("erp.finance.write", "Create and update finance and accounting records"),
    ("erp.hr.read", "View HR and payroll records"),
    ("erp.hr.write", "Create and update HR and payroll records"),
)

_ALL = tuple(key for key, _ in _PERMISSIONS)
_MANAGER = tuple(key for key in _ALL if not key.endswith(".approve"))
_READ_ONLY = tuple(key for key in _ALL if key.endswith(".read"))


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
    _append_permissions(("department_manager",), _MANAGER)
    _append_permissions(("standard_user", "auditor"), _READ_ONLY)
    op.execute(
        "UPDATE roles SET permissions = array_remove(permissions, 'erp.purchase.approve') "
        "WHERE name = 'department_manager'"
    )


def downgrade() -> None:
    for key in _ALL:
        op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{key}')")
        op.execute(f"DELETE FROM permissions WHERE key = '{key}'")
    op.execute(
        "UPDATE roles SET permissions = array_append(permissions, 'erp.purchase.approve') "
        "WHERE name = 'department_manager' "
        "AND NOT ('erp.purchase.approve' = ANY(permissions))"
    )
