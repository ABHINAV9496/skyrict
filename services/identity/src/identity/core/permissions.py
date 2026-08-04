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
)

__all__ = [
    "AUDIT_READ",
    "BILLING_MANAGE",
    "CATALOG",
    "ERP_INVOICE_APPROVE",
    "ERP_INVOICE_READ",
    "ERP_PURCHASE_APPROVE",
    "MFA_MANAGE",
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
