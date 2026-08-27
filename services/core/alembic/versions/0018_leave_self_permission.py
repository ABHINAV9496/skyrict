"""Register erp.leave.self in the core_permissions catalog.

Mirrors identity migration 0018: the employee self-service portal permission
becomes assignable to roles (``employee_self_service`` seeds it via
``core.seed.CORE_SYSTEM_ROLES``, and the invite-accept mirror writes it into
``core_roles.permissions`` directly).

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-25
"""

from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO core_permissions (key, description) VALUES "
        "('erp.leave.self', 'Employee self-service access to own leave balances and requests') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM core_permissions WHERE key = 'erp.leave.self'")
