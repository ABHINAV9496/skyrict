"""Canonical ORM models for the identity service.

Single source of truth for the persistence layer. Models live here (not
scattered across ``application/*/models``) so alembic autogen, the model
registry, and app code all agree on the schema.
"""

from __future__ import annotations

from identity.models.audit_log import AuditLogModel
from identity.models.invitation import InvitationModel
from identity.models.membership import MembershipModel
from identity.models.permission import PermissionModel
from identity.models.role import RoleModel
from identity.models.session import SessionModel
from identity.models.tenant import TenantModel
from identity.models.user import UserModel
from identity.models.user_role import UserRoleModel

__all__ = [
    "AuditLogModel",
    "InvitationModel",
    "MembershipModel",
    "PermissionModel",
    "RoleModel",
    "SessionModel",
    "TenantModel",
    "UserModel",
    "UserRoleModel",
]
