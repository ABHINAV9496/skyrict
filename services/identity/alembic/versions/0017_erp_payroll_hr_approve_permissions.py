"""Register ERP Payroll permissions and HR approve; grant per design doc.

Mirrors core's ``core_permissions`` catalog (the platform-fixed set that
core migration 0006 seeds with all six ``erp.hr.*`` / ``erp.payroll.*`` keys)
into identity's ``permissions`` table and grants the new keys to system roles
per the HR & Payroll design doc (``docs/design/hr-payroll.md``) section 2.4:

- ``organization_admin`` -> all four new keys
- ``department_manager`` -> ``erp.payroll.read`` (already has erp.hr.read/write;
  explicitly NOT granted approve / payroll.write)
- ``auditor`` -> ``erp.payroll.read`` (already has erp.hr.read)
- ``standard_user`` / ``tenant_owner`` -> unchanged

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-13
"""

from __future__ import annotations

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("erp.hr.approve", "Approve, reject, or cancel leave requests"),
    (
        "erp.payroll.read",
        "View compensation records, payroll runs, entries, and payroll settings",
    ),
    (
        "erp.payroll.write",
        "Create payroll runs, compute payroll, edit draft entries, and update settings",
    ),
    ("erp.payroll.approve", "Approve, void, or mark a payroll run as paid"),
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
    _append_permissions(("department_manager",), ("erp.payroll.read",))
    _append_permissions(("auditor",), ("erp.payroll.read",))


def downgrade() -> None:
    for key in _ALL:
        op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{key}')")
        op.execute(f"DELETE FROM permissions WHERE key = '{key}'")
