"""ORM model registry.

Importing this package registers every model on the declarative ``Base`` so
SQLAlchemy can configure cross-module relationships before the first query and
Alembic's ``target_metadata`` reflects the full schema.

Currently maps only the read-only ``tenants`` projection; the AI tables
(``ai_query_log``, ``ai_suggestions``, ``ai_anomalies``, ``agent_registry``,
``ai_audit_log``) are added with the SKY-57 migration commit.
"""

from ai_agent.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from ai_agent.models.tenant import TenantModel

__all__ = [
    "Base",
    "TenantModel",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
]
