"""Add erp.hr.ai.* permissions (HR/Payroll AI slice).

Ticket HR-AI-001 (docs/modules/skyrict-ai/hr-payroll-ai-features.md §3):
four new ``erp.hr.ai.*`` keys gate the HR & Payroll AI panels at the core
edge, mirroring identity.core.permissions so role grants stay portable.

Grant matrix (from the spec):
  - ``erp.hr.ai.read``        L1 -> organization_admin, department_manager, auditor
  - ``erp.hr.ai.individual``  L2 -> tenant_owner ONLY (owner also holds ``*``);
                                 deliberately NOT granted to organization_admin
                                 or department_manager. Available in the catalog
                                 so a dedicated executive role can be granted it.
  - ``erp.hr.ai.acknowledge`` L2 -> organization_admin, department_manager
  - ``erp.hr.ai.copilot``     L1 -> organization_admin, department_manager

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

# (key, description) - mirrors identity.core.permissions catalog entries.
_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("erp.hr.ai.read", "View aggregate (L1) HR & Payroll AI panels"),
    ("erp.hr.ai.individual", "View individual (L2) attrition scores + factor explanations"),
    ("erp.hr.ai.acknowledge", "Acknowledge a team-risk item (audited)"),
    ("erp.hr.ai.copilot", "Use the HR Copilot agent"),
)

# Roles granted each key when migrating (owner is covered by its "*" grant).
_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("erp.hr.ai.read", ("organization_admin", "department_manager", "auditor")),
    ("erp.hr.ai.individual", ("tenant_owner",)),
    ("erp.hr.ai.acknowledge", ("organization_admin", "department_manager")),
    ("erp.hr.ai.copilot", ("organization_admin", "department_manager")),
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
