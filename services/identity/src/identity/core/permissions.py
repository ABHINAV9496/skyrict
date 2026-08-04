"""Canonical permission keys for the identity domain.

Platform-fixed catalog: these keys are the source of truth that role
definitions (``core/constants.py``) and the RBAC authorization service
reference. Keys follow the ``{scope}:{action}`` convention (e.g.
``users:write``).

A permission must be added here AND via migration before it can be assigned
to roles.
"""

from __future__ import annotations

# Full access within a tenant (owner role).
WILDCARD = "*"

# User management
USERS_READ = "users:read"
USERS_WRITE = "users:write"
USERS_DELETE = "users:delete"

# Role management
ROLES_READ = "roles:read"
ROLES_WRITE = "roles:write"

# Tenant / organization
TENANTS_READ = "tenants:read"
TENANTS_WRITE = "tenants:write"

# Sessions
SESSIONS_READ = "sessions:read"
SESSIONS_REVOKE = "sessions:revoke"

# Audit
AUDIT_READ = "audit:read"

# Security configuration
MFA_MANAGE = "mfa:manage"
SSO_MANAGE = "sso:manage"

# Organization settings
SETTINGS_READ = "settings:read"
SETTINGS_WRITE = "settings:write"

# ERP
ERP_INVOICE_READ = "erp.invoice.read"
ERP_INVOICE_APPROVE = "erp.invoice.approve"
ERP_PURCHASE_APPROVE = "erp.purchase.approve"

# Billing
BILLING_MANAGE = "billing.manage"

# Invitations
INVITATIONS_SEND = "invitations:send"

# Every catalogued permission, in catalog order.
CATALOG: tuple[str, ...] = (
    USERS_READ,
    USERS_WRITE,
    USERS_DELETE,
    ROLES_READ,
    ROLES_WRITE,
    TENANTS_READ,
    TENANTS_WRITE,
    SESSIONS_READ,
    SESSIONS_REVOKE,
    AUDIT_READ,
    MFA_MANAGE,
    SSO_MANAGE,
    SETTINGS_READ,
    SETTINGS_WRITE,
    ERP_INVOICE_READ,
    ERP_INVOICE_APPROVE,
    ERP_PURCHASE_APPROVE,
    BILLING_MANAGE,
    INVITATIONS_SEND,
)

# Permission module groupings (for GET /permissions catalog endpoint)
# Each entry: (module_key, module_label, (permission_keys, ...))
PERMISSION_MODULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("user", "User management", (USERS_READ, USERS_WRITE, USERS_DELETE)),
    ("role", "Role management", (ROLES_READ, ROLES_WRITE)),
    ("tenant", "Tenant / organization", (TENANTS_READ, TENANTS_WRITE)),
    ("session", "Sessions", (SESSIONS_READ, SESSIONS_REVOKE)),
    ("audit", "Audit", (AUDIT_READ,)),
    ("security", "Security configuration", (MFA_MANAGE, SSO_MANAGE)),
    ("settings", "Organization settings", (SETTINGS_READ, SETTINGS_WRITE)),
    ("erp", "ERP", (ERP_INVOICE_READ, ERP_INVOICE_APPROVE, ERP_PURCHASE_APPROVE)),
    ("billing", "Billing", (BILLING_MANAGE,)),
    ("invitations", "User invitations", (INVITATIONS_SEND,)),
)


def _assert_catalog_union() -> None:
    """Ensure PERMISSION_MODULES and CATALOG stay in sync (fail-fast on drift)."""
    module_keys = {k for _, _, keys in PERMISSION_MODULES for k in keys}
    catalog_keys = set(CATALOG)
    if module_keys != catalog_keys:
        missing = catalog_keys - module_keys
        orphaned = module_keys - catalog_keys
        msg = "PERMISSION_MODULES <-> CATALOG mismatch:\n"
        if missing:
            msg += f"  Missing from PERMISSION_MODULES: {missing}\n"
        if orphaned:
            msg += f"  Orphaned in PERMISSION_MODULES: {orphaned}\n"
        raise ValueError(msg)


_assert_catalog_union()

__all__ = [
    "AUDIT_READ",
    "BILLING_MANAGE",
    "CATALOG",
    "ERP_INVOICE_APPROVE",
    "ERP_INVOICE_READ",
    "ERP_PURCHASE_APPROVE",
    "INVITATIONS_SEND",
    "MFA_MANAGE",
    "PERMISSION_MODULES",
    "ROLES_READ",
    "ROLES_WRITE",
    "SESSIONS_READ",
    "SESSIONS_REVOKE",
    "SETTINGS_READ",
    "SETTINGS_WRITE",
    "SSO_MANAGE",
    "TENANTS_READ",
    "TENANTS_WRITE",
    "USERS_DELETE",
    "USERS_READ",
    "USERS_WRITE",
    "WILDCARD",
]
