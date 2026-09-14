"""CRM anomaly table: ai_crm_anomalies (SKY-91 Part 13).

Lands the persistence layer for the deterministic CRM pipeline anomaly
detection engine (SKY-91):

- ``ai_crm_anomalies`` - one row per detected anomaly on an open opportunity.
  Severity is ``critical | warning | info``; status transitions from ``open``
  to ``resolved`` (human acted) or ``dismissed`` (false positive) - enforced
  by CHECK constraints.
  ``opportunity_id`` is a soft-link UUID with NO FK (the opportunity is
  owned by core in the shared database, same cross-service idiom as
  ``ai_deal_health.opportunity_id``).

Tenant-scoped (composite ``(tenant_id, id)`` PK + RLS against
``public.current_tenant_id()``, the repo-wide convention for every AI table).

Chains after 0022 (SKY-91 transcript analyses).

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def _create_rls_policy(table: str) -> None:
    """Enable RLS and create the tenant-isolation policy for a tenant table."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON public.{table} "
        "USING (tenant_id = public.current_tenant_id()) "
        "WITH CHECK (tenant_id = public.current_tenant_id())"
    )


def _drop_rls_policy(table: str) -> None:
    """Disable RLS and drop the tenant-isolation policy for a tenant table."""
    op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON public.{table}")


def upgrade() -> None:
    # --- ai_crm_anomalies: one detected pipeline anomaly per opportunity -----
    op.create_table(
        "ai_crm_anomalies",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("opportunity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'open'")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("context", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "severity IN ('critical', 'warning', 'info')",
            name="ck_ai_crm_anomalies_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')",
            name="ck_ai_crm_anomalies_status",
        ),
        sa.Index(
            "idx_ai_crm_anomalies_tenant_opportunity",
            "tenant_id",
            "opportunity_id",
            "detected_at",
        ),
        sa.Index(
            "idx_ai_crm_anomalies_tenant_rule",
            "tenant_id",
            "rule_id",
            "detected_at",
        ),
        sa.Index(
            "idx_ai_crm_anomalies_tenant_status",
            "tenant_id",
            "status",
            "detected_at",
        ),
    )

    _create_rls_policy("ai_crm_anomalies")


def downgrade() -> None:
    _drop_rls_policy("ai_crm_anomalies")
    op.drop_table("ai_crm_anomalies")
