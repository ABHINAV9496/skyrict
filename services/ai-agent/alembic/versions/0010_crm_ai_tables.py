"""CRM AI tables: lead scores, deal health, follow-up suggestions (SKY-61).

Lands the Part 11 storage for the CRM AI feature:

- ``ai_lead_scores`` - one row per scoring run of a lead. ``score`` is the
  deterministic weighted sum (0-100) from the CRM scoring engine; ``factors``
  is the JSONB breakdown the UI shows in the badge tooltip; ``computed_at``
  lets a lead carry a history of runs. ``UNIQUE (tenant_id, lead_id,
  computed_at)`` makes a re-score insert a new version rather than clobber.
- ``ai_deal_health`` - one row per opportunity health assessment. ``health``
  is the band ``green|yellow|red``; ``risk_factors`` + ``recommended_actions``
  are the JSONB lists surfaced in the insights panel; ``engagement_velocity``
  (+accelerating/-decelerating) and ``days_in_stage`` are stored as assessed.
- ``ai_follow_up_suggestions`` - one row per generated follow-up. Links a
  suggestion to any CRM entity via ``entity_type``/``entity_id`` soft-link
  (no cross-service FK, per repo convention). ``status`` moves
  pending -> sent|dismissed|expired on a one-click apply; ``expires_at``
  (default 7 days) drives the expiry sweep.

All three are tenant-scoped (composite ``(tenant_id, id)`` PK + RLS against
``public.current_tenant_id()``, the repo-wide convention). CRM entity ids are
soft-link UUIDs - the actual CRM rows stay owned by core.

Flips ``crm_assistant`` in ``agent_registry`` to enabled so the supervisor
routes CRM questions to the live delegate (the seed row already exists from
migration 0009, disabled).

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-31
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_TENANT_SCOPED_TABLES = (
    "ai_lead_scores",
    "ai_deal_health",
    "ai_follow_up_suggestions",
)


# ---------------------------------------------------------------------------
# Schema helpers (same idiom as migrations 0001/0008)
# ---------------------------------------------------------------------------
def _tenant_scoped_pk(fk: bool) -> list[Any]:
    """Composite (tenant_id, id) PK so no generated PK column leaks."""
    columns: list[Any] = [
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        )
        if fk
        else sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    ]
    return columns


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def _updated_at() -> sa.Column[Any]:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


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


def _ensure_current_tenant_id() -> None:
    """Pins the current-tenant-id function that RLS policies reference."""
    op.execute(
        "CREATE OR REPLACE FUNCTION public.current_tenant_id() RETURNS uuid "
        "LANGUAGE sql STABLE AS $$ "
        "SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid $$"
    )


def upgrade() -> None:
    # --- ai_lead_scores: one row per lead scoring run -----------------------
    op.create_table(
        "ai_lead_scores",
        *_tenant_scoped_pk(fk=True),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("factors", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("model_version", sa.String(64), nullable=False, server_default=sa.text("'v1'")),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        _created_at(),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_ai_lead_scores_score_range"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_ai_lead_scores_confidence_range"
        ),
        sa.UniqueConstraint(
            "tenant_id", "lead_id", "computed_at", name="uq_ai_lead_scores_lead_computed"
        ),
        sa.Index("idx_ai_lead_scores_tenant_lead", "tenant_id", "lead_id"),
        sa.Index("idx_ai_lead_scores_computed", "tenant_id", "computed_at"),
    )

    # --- ai_deal_health: one row per opportunity health assessment ----------
    op.create_table(
        "ai_deal_health",
        *_tenant_scoped_pk(fk=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("health", sa.String(16), nullable=False, server_default=sa.text("'green'")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "risk_factors", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "recommended_actions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("engagement_velocity", sa.Float(), nullable=True),
        sa.Column("days_in_stage", sa.Integer(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        _created_at(),
        sa.CheckConstraint("health IN ('green', 'yellow', 'red')", name="ck_ai_deal_health_band"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_ai_deal_health_confidence_range"
        ),
        sa.Index("idx_ai_deal_health_tenant", "tenant_id", "computed_at"),
        sa.Index("idx_ai_deal_health_opportunity", "tenant_id", "opportunity_id"),
    )

    # --- ai_follow_up_suggestions: generated follow-ups ----------------------
    op.create_table(
        "ai_follow_up_suggestions",
        *_tenant_scoped_pk(fk=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column(
            "suggestion_type",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'task'"),
        ),
        sa.Column("draft_content", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_by", sa.Uuid(), nullable=True),
        sa.Column("activity_id", sa.Uuid(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('lead', 'opportunity', 'customer', 'contact')",
            name="ck_ai_follow_up_entity_type",
        ),
        sa.CheckConstraint(
            "suggestion_type IN ('email', 'call', 'meeting', 'task')",
            name="ck_ai_follow_up_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'dismissed', 'expired')",
            name="ck_ai_follow_up_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_ai_follow_up_confidence_range"
        ),
        sa.Index("idx_follow_up_tenant_user", "tenant_id", "user_id", "status"),
        sa.Index("idx_follow_up_entity", "tenant_id", "entity_type", "entity_id"),
    )

    # --- Row-level security ---------------------------------------------------
    _ensure_current_tenant_id()
    for table in _TENANT_SCOPED_TABLES:
        _create_rls_policy(table)

    # --- Enable the CRM Assistant (seed row came from migration 0009) --------
    op.execute(
        "UPDATE agent_registry "
        "SET enabled = true "
        "WHERE name = 'crm_assistant' "
        "AND module = 'ai_agent.features.supervisor.delegates'"
    )


def downgrade() -> None:
    # 1) drop RLS policies
    for table in _TENANT_SCOPED_TABLES:
        _drop_rls_policy(table)

    # 2) drop tables (indexes/constraints go with them)
    op.drop_table("ai_follow_up_suggestions")
    op.drop_table("ai_deal_health")
    op.drop_table("ai_lead_scores")

    # 3) re-disable the CRM Assistant (restore 0009 state)
    op.execute(
        "UPDATE agent_registry "
        "SET enabled = false "
        "WHERE name = 'crm_assistant' "
        "AND module = 'ai_agent.features.supervisor.delegates'"
    )
