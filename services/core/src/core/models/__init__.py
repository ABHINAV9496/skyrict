"""ORM model registry.

Importing this package registers every model on the declarative ``Base`` so
SQLAlchemy can configure cross-module relationships before the first query and
Alembic's ``target_metadata`` reflects the full schema.
"""

from core.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from core.models.core_permission import CorePermissionModel
from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel
from core.models.erp_currency import ErpCurrencyModel
from core.models.tenant import TenantModel

__all__ = [
    "Base",
    "CorePermissionModel",
    "CoreRoleModel",
    "CoreUserRoleModel",
    "ErpCurrencyModel",
    "TenantModel",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
]
