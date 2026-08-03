"""ORM model registry — import every model so SQLAlchemy can configure mappers.

SQLAlchemy resolves relationship targets (e.g. ``UserModel.user_roles`` ->
``UserRoleModel``) against the registry when mappers are configured. Models
that reference each other across modules must ALL be imported before the first
query, otherwise mapper configuration fails with "failed to locate a name".

Every runtime entry point imports this module for its side effect:
    - ``identity/main.py`` (FastAPI app startup)
    - ``identity/alembic/env.py`` (migrations)
    - integration test fixtures (schema creation / seeding)

Keeping the list here — instead of scattering per-file imports — makes it the
single source of truth for "what models exist", matching what alembic autogen
would discover.
"""

from __future__ import annotations

from identity.models.audit_log import AuditLogModel
from identity.models.permission import PermissionModel
from identity.models.role import RoleModel
from identity.models.session import SessionModel
from identity.models.tenant import TenantModel
from identity.models.user import UserModel
from identity.models.user_role import UserRoleModel

__all__ = [
    "AuditLogModel",
    "PermissionModel",
    "RoleModel",
    "SessionModel",
    "TenantModel",
    "UserModel",
    "UserRoleModel",
]
