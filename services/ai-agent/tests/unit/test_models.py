"""ORM metadata tests for the AI foundation tables (no database needed).

These pin the schema contract at the SQLAlchemy metadata level: table names,
composite PK shape, money precision, CHECK constraints, the partial unique
pending index, insert-only tables, the global agent registry, and the
INV-AI-002 predictive tables.
"""

from __future__ import annotations

import ai_agent.models  # noqa: F401  # registers every model on Base.metadata
from ai_agent.models.agent_registry import AgentRegistryModel
from ai_agent.models.ai_anomaly import AiAnomalyModel
from ai_agent.models.ai_anomaly_rule_stats import AiAnomalyRuleStatsModel
from ai_agent.models.ai_audit_log import AiAuditLogModel
from ai_agent.models.ai_digest import AiDigestModel
from ai_agent.models.ai_query_cache import AiQueryCacheModel
from ai_agent.models.ai_query_log import AiQueryLogModel
from ai_agent.models.ai_restock_demand_stats import AiRestockDemandStatsModel
from ai_agent.models.ai_restock_settings import AiRestockSettingsModel
from ai_agent.models.ai_suggestion import AiSuggestionModel
from ai_agent.models.base import Base


class TestRegistry:
    def test_all_expected_tables_registered(self) -> None:
        expected = {
            # read-only projection of identity's shared table
            "tenants",
            # read-only projections of core's RBAC tables (SKY-59)
            "core_roles",
            "core_user_roles",
            # AI-owned tables (SKY-57)
            "ai_query_log",
            "ai_suggestions",
            "ai_anomalies",
            "ai_audit_log",
            "ai_digest_snapshots",
            "agent_registry",
            # INV-AI-002 predictive tables
            "ai_restock_settings",
            "ai_restock_demand_stats",
            "ai_anomaly_rule_stats",
            # RAG tables (SKY-58)
            "ai_rag_parents",
            "ai_rag_chunks",
            "ai_episodic_memory",
            "ai_query_cache",
            "ai_eval_runs",
            # LangGraph orchestration (SKY-59)
            "graph_checkpoints",
            "graph_checkpoint_writes",
            "agent_interrupts",
        }
        assert expected == set(Base.metadata.tables.keys())

    def test_tenant_tables_use_composite_pk(self) -> None:
        for table in (
            "ai_query_log",
            "ai_suggestions",
            "ai_anomalies",
            "ai_audit_log",
            "ai_digest_snapshots",
            "ai_rag_parents",
            "ai_rag_chunks",
            "ai_episodic_memory",
            "ai_query_cache",
        ):
            pk = list(Base.metadata.tables[table].primary_key.columns.keys())
            assert pk == ["tenant_id", "id"], table


class TestAiQueryLog:
    def test_insert_only_table_has_no_updated_at(self) -> None:
        assert "updated_at" not in AiQueryLogModel.__table__.columns

    def test_parsed_intent_is_jsonb(self) -> None:
        type_name = type(AiQueryLogModel.__table__.c.parsed_intent.type).__name__
        assert type_name == "JSONB"


class TestAiSuggestions:
    def test_money_columns_are_numeric_18_4(self) -> None:
        for column_name in (
            "current_stock",
            "reorder_point",
            "suggested_qty",
            "estimated_cost",
        ):
            column = AiSuggestionModel.__table__.columns[column_name]
            assert column.type.precision == 18, column_name  # type: ignore[attr-defined]
            assert column.type.scale == 4, column_name  # type: ignore[attr-defined]

    def test_confidence_is_numeric_3_2(self) -> None:
        confidence = AiSuggestionModel.__table__.c.confidence.type
        assert confidence.precision == 3
        assert confidence.scale == 2

    def test_check_constraints_present(self) -> None:
        names = {
            constraint.name
            for constraint in AiSuggestionModel.__table__.constraints
            if constraint.name is not None and str(constraint.name).startswith("ck_")
        }
        assert {
            "ck_ai_suggestions_status",
            "ck_ai_suggestions_suggested_qty_positive",
            "ck_ai_suggestions_confidence_range",
        } <= names

    def test_pending_unique_index_is_partial(self) -> None:
        index = next(
            index
            for index in AiSuggestionModel.__table__.indexes
            if index.name == "idx_ai_suggestions_pending_unique"
        )
        assert index.unique
        where_sql = str(index.dialect_options["postgresql"]["where"]).lower()
        assert "pending" in where_sql

    def test_default_status_is_pending(self) -> None:
        default = AiSuggestionModel.__table__.c.status.server_default.arg
        assert str(default) == "'pending'"


class TestAiAnomalies:
    def test_severity_and_status_checks_present(self) -> None:
        names = {
            constraint.name
            for constraint in AiAnomalyModel.__table__.constraints
            if constraint.name is not None and str(constraint.name).startswith("ck_")
        }
        assert {"ck_ai_anomalies_severity", "ck_ai_anomalies_status"} <= names

    def test_related_movement_ids_is_uuid_array(self) -> None:
        type_name = type(AiAnomalyModel.__table__.c.related_movement_ids.type).__name__
        assert type_name == "ARRAY"

    def test_default_status_is_open(self) -> None:
        default = AiAnomalyModel.__table__.c.status.server_default.arg
        assert str(default) == "'open'"


class TestAiAuditLog:
    def test_insert_only_table_has_no_updated_at(self) -> None:
        assert "updated_at" not in AiAuditLogModel.__table__.columns

    def test_input_output_are_jsonb(self) -> None:
        assert type(AiAuditLogModel.__table__.c.input.type).__name__ == "JSONB"
        assert type(AiAuditLogModel.__table__.c.output.type).__name__ == "JSONB"


class TestAiDigest:
    def test_insert_only_table_has_no_updated_at(self) -> None:
        assert "updated_at" not in AiDigestModel.__table__.columns

    def test_points_and_signals_are_jsonb(self) -> None:
        assert type(AiDigestModel.__table__.c.points.type).__name__ == "JSONB"
        assert type(AiDigestModel.__table__.c.signals.type).__name__ == "JSONB"

    def test_as_of_index_applies_desc_order(self) -> None:
        index = next(
            index
            for index in AiDigestModel.__table__.indexes
            if index.name == "idx_ai_digest_snapshots_tenant_as_of"
        )
        cols = [column.name for column in index.columns]
        assert cols == ["tenant_id", "as_of"]
        desc = str(index.expressions[-1].compile()).lower()
        assert "generated_at desc" in desc


class TestAiQueryCache:
    def test_tenant_hash_unique_index_is_tenant_scoped(self) -> None:
        """One cache entry per tenant+query — never a global query hash."""
        index = next(
            index
            for index in AiQueryCacheModel.__table__.indexes
            if index.name == "uq_ai_query_cache_tenant_hash"
        )
        assert index.unique
        assert [c.name for c in index.columns] == ["tenant_id", "query_hash"]


class TestAgentRegistry:
    def test_global_table_has_no_tenant_scoping(self) -> None:
        assert "tenant_id" not in AgentRegistryModel.__table__.columns

    def test_name_is_unique(self) -> None:
        uniques = {
            constraint.name
            for constraint in AgentRegistryModel.__table__.constraints
            if constraint.name is not None and str(constraint.name).startswith("uq_")
        }
        assert "uq_agent_registry_name" in uniques

    def test_enabled_defaults_to_true(self) -> None:
        default = AgentRegistryModel.__table__.c.enabled.server_default.arg
        assert str(default).lower() == "true"


class TestAiRestockSettings:
    def test_single_column_tenant_pk(self) -> None:
        pk = list(AiRestockSettingsModel.__table__.primary_key.columns.keys())
        assert pk == ["tenant_id"]

    def test_defaults_are_conservative(self) -> None:
        cols = AiRestockSettingsModel.__table__.c
        assert str(cols.lead_time_days.server_default.arg) == "7"
        assert str(cols.safety_factor.server_default.arg) == "1"
        assert str(cols.v2_enabled.server_default.arg).lower() == "false"

    def test_check_constraints_present(self) -> None:
        names = {
            constraint.name
            for constraint in AiRestockSettingsModel.__table__.constraints
            if constraint.name is not None and str(constraint.name).startswith("ck_")
        }
        assert {
            "ck_ai_restock_settings_lead_time_positive",
            "ck_ai_restock_settings_safety_factor_positive",
            "ck_ai_restock_settings_sensitivity_range",
            "ck_ai_restock_settings_fp_threshold_range",
        } <= names


class TestAiRestockDemandStats:
    def test_composite_pk(self) -> None:
        pk = list(AiRestockDemandStatsModel.__table__.primary_key.columns.keys())
        assert pk == ["tenant_id", "product_id", "warehouse_id"]

    def test_eligible_lookup_index_exists(self) -> None:
        index = next(
            index
            for index in AiRestockDemandStatsModel.__table__.indexes
            if index.name == "idx_ai_restock_demand_stats_eligible"
        )
        assert not index.unique
        assert [str(c.name) for c in index.expressions] == ["tenant_id", "eligible"]


class TestAiAnomalyRuleStats:
    def test_composite_pk(self) -> None:
        pk = list(AiAnomalyRuleStatsModel.__table__.primary_key.columns.keys())
        assert pk == ["tenant_id", "anomaly_type"]

    def test_counters_cannot_be_negative(self) -> None:
        names = {
            constraint.name
            for constraint in AiAnomalyRuleStatsModel.__table__.constraints
            if constraint.name is not None and str(constraint.name).startswith("ck_")
        }
        assert "ck_ai_anomaly_rule_stats_counts_non_negative" in names
