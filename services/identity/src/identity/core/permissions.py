"""Canonical permission keys for the identity domain.

Platform-fixed catalog: these keys are the source of truth that role
definitions (``db/seed.py``) and the RBAC authorization service reference.
Keys follow the ``{scope}:{action}`` convention (e.g. ``users:write``).

A permission must be added here AND via migration before it can be assigned
to roles.
"""

from __future__ import annotations

# Full access within a tenant (owner role).
WILDCARD = "*"

# User management
USERS_READ = "users:read"
USERS_WRITE = "users:write"

# Organization settings
SETTINGS_READ = "settings:read"
SETTINGS_WRITE = "settings:write"

# Every catalogued permission, in catalog order.
CATALOG: tuple[str, ...] = (
    USERS_READ,
    USERS_WRITE,
    SETTINGS_READ,
    SETTINGS_WRITE,
)

__all__ = [
    "WILDCARD",
    "USERS_READ",
    "USERS_WRITE",
    "SETTINGS_READ",
    "SETTINGS_WRITE",
    "CATALOG",
]
