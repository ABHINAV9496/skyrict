"""Add predictive reorder-support tables (INV-AI-002).

Creates three tenant-scoped (RLS) tables:

- ai_restock_demand_stats: per product+warehouse rolling demand profile
  (avg daily demand from the movement ledger, demand CV, observed window,
  last receipt) plus the ``eligible`` flag that gates the v2 restock formula.
- ai_restock_settings: per-tenant tunables for the v2 formula (lead time,
  safety factor), feature flag (``v2_enabled``), anomaly sensitivity /
  false-positive suppression threshold, and email-alert toggle.
- ai_anomaly_rule_stats: per-rule false-positive counters feeding the
  sensitivity tuning loop (dismissals reduce detection sensitivity).

The demand stats table uses composite PK ``(tenant_id, product_id,
warehouse_id)`` and composite FKs into core-owned ``erp_products`` /
``erp_warehouses`` (cross-service idiom: tenant_id carries no direct FK to
``tenants`` here because RLS + the composite FKs keep integrity).

Renumbered from 0004 to 0006 on 2026-08-30 after dev merged SKY-73
(0004_pgvector_rag_tables) and SKY-58 (0005_fix_query_cache_unique) while
this branch was in flight. Final ai-agent chain: 0001 (foundation) -> 0002
(hr copilot) -> 0003 (forecast/abc/monitor) -> 0004 (RAG) -> 0005 (query-cache
unique fix) -> 0006 (this restock work).

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _enable_rls(table: str) -> None:
    """RLS + tenant isolation policy, matching the 0001 convention."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON {table} "
        "USING (tenant_id = public.current_tenant_id())"
    )


def upgrade() -> None:
    # --- ai_restock_settings (per-tenant tunables, RLS) ---
    op.create_table(
        "ai_restock_settings",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "lead_time_days",
            sa.Numeric(8, 2),
            nullable=False,
            server_default=sa.text("7"),
        ),
        sa.Column(
            "safety_factor",
            sa.Numeric(4, 3),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "v2_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sensitivity",
            sa.Numeric(4, 3),
            nullable=False,
            server_default=sa.text("0.5"),
        ),
        sa.Column(
            "fp_threshold",
            sa.Numeric(4, 3),
            nullable=False,
            server_default=sa.text("0.5"),
        ),
        sa.Column(
            "email_alerts_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("lead_time_days > 0", name="ck_ai_restock_settings_lead_time_positive"),
        sa.CheckConstraint(
            "safety_factor > 0", name="ck_ai_restock_settings_safety_factor_positive"
        ),
        sa.CheckConstraint(
            "sensitivity >= 0 AND sensitivity <= 1",
            name="ck_ai_restock_settings_sensitivity_range",
        ),
        sa.CheckConstraint(
            "fp_threshold >= 0 AND fp_threshold <= 1",
            name="ck_ai_restock_settings_fp_threshold_range",
        ),
    )

    # --- ai_restock_demand_stats (rolling demand profile, RLS) ---
    op.create_table(
        "ai_restock_demand_stats",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("product_id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("warehouse_id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "avg_daily_demand",
            sa.Numeric(18, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "demand_cv",
            sa.Numeric(8, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "window_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_receipt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["erp_warehouses.tenant_id", "erp_warehouses.id"],
            ondelete="CASCADE",
            name="fk_ai_restock_demand_stats_warehouse_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["erp_products.tenant_id", "erp_products.id"],
            ondelete="CASCADE",
            name="fk_ai_restock_demand_stats_product_tenant",
        ),
    )
    op.create_index(
        "idx_ai_restock_demand_stats_eligible",
        "ai_restock_demand_stats",
        ["tenant_id", "eligible"],
    )

    # --- ai_anomaly_rule_stats (false-positive counters, RLS) ---
    op.create_table(
        "ai_anomaly_rule_stats",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("anomaly_type", sa.String(50), primary_key=True, nullable=False),
        sa.Column(
            "findings_total",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "false_positives",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "findings_total >= 0 AND false_positives >= 0",
            name="ck_ai_anomaly_rule_stats_counts_non_negative",
        ),
    )

    for table in ("ai_restock_settings", "ai_restock_demand_stats", "ai_anomaly_rule_stats"):
        _enable_rls(table)


def downgrade() -> None:
    op.drop_table("ai_anomaly_rule_stats")
    op.drop_table("ai_restock_demand_stats")
    op.drop_table("ai_restock_settings")
