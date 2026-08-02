"""ORM model registry — import every model so SQLAlchemy can configure mappers.

SQLAlchemy resolves relationship targets (e.g. ``UserModel.tenant_roles`` ->
``TenantRoleModel``) against the registry when mappers are configured. Models
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

from identity.application.audit.models.audit_log import AuditLogModel
from identity.application.auth.models.user import UserModel
from identity.application.role.models.role import RoleModel, TenantRoleModel
from identity.application.session.models.session import SessionModel
from identity.application.tenant.models.tenant import TenantModel

__all__ = [
    "AuditLogModel",
    "RoleModel",
    "SessionModel",
    "TenantModel",
    "TenantRoleModel",
    "UserModel",
]
