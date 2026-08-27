"""Register erp.leave.self + seed the employee_self_service system role.

Adds the self-service portal permission to the platform catalog and backfills
the ``employee_self_service`` role for every existing tenant (new tenants get
it automatically via provisioning from ``SYSTEM_ROLE_DEFINITIONS``). The role
deliberately holds ONLY ``erp.leave.self`` — holders get the /leave portal and
nothing else; the login redirect routes sole holders away from /dashboard.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-25
"""

from __future__ import annotations

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

_PERMISSION_KEY = "erp.leave.self"
_PERMISSION_DESCRIPTION = "Employee self-service access to own leave balances and requests"
_ROLE_NAME = "employee_self_service"


def upgrade() -> None:
    op.execute(
        "INSERT INTO permissions (key, description) VALUES "
        f"('{_PERMISSION_KEY}', '{_PERMISSION_DESCRIPTION}') ON CONFLICT (key) DO NOTHING"
    )
    # Backfill the system role for every existing tenant. New tenants receive
    # it from SYSTEM_ROLE_DEFINITIONS at provisioning time.
    op.execute(
        "INSERT INTO roles (tenant_id, name, permissions, is_system_role) "
        f"SELECT t.id, '{_ROLE_NAME}', ARRAY['{_PERMISSION_KEY}']::varchar[], true "
        "FROM tenants t "
        f"WHERE NOT EXISTS (SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND r.name = '{_ROLE_NAME}')"
    )


def downgrade() -> None:
    op.execute(
        f"DELETE FROM user_roles WHERE role_id IN (SELECT id FROM roles WHERE name = '{_ROLE_NAME}')"
    )
    op.execute(f"DELETE FROM roles WHERE name = '{_ROLE_NAME}'")
    op.execute(f"DELETE FROM permissions WHERE key = '{_PERMISSION_KEY}'")
