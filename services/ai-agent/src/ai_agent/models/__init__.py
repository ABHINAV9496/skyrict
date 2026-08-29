"""ORM model registry.

Importing this package registers every model on the declarative ``Base`` so
SQLAlchemy can configure cross-module relationships before the first query and
Alembic's ``target_metadata`` reflects the full schema.

- ``tenants`` is a read-only projection of identity's shared table.
- The AI tables (ai_query_log, ai_suggestions, ai_anomalies, ai_audit_log)
  are owned by this service and migrated under ``alembic_version_ai``.
- ``agent_registry`` is global platform data (no tenant scoping).
"""

from ai_agent.models.agent_registry import AgentRegistryModel
from ai_agent.models.ai_anomaly import AiAnomalyModel
from ai_agent.models.ai_anomaly_rule_stats import AiAnomalyRuleStatsModel
from ai_agent.models.ai_audit_log import AiAuditLogModel
from ai_agent.models.ai_query_log import AiQueryLogModel
from ai_agent.models.ai_restock_demand_stats import AiRestockDemandStatsModel
from ai_agent.models.ai_restock_settings import AiRestockSettingsModel
from ai_agent.models.ai_suggestion import AiSuggestionModel
from ai_agent.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from ai_agent.models.tenant import TenantModel

__all__ = [
    "AgentRegistryModel",
    "AiAnomalyModel",
    "AiAnomalyRuleStatsModel",
    "AiAuditLogModel",
    "AiQueryLogModel",
    "AiRestockDemandStatsModel",
    "AiRestockSettingsModel",
    "AiSuggestionModel",
    "Base",
    "TenantModel",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
]
