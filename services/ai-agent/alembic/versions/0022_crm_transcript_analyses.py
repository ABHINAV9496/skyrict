"""Transcript analysis table: ai_transcript_analyses (SKY-91 Part 13).

Lands the storage for CRM transcript analysis (Part 13 of AI-CRM-Sales-Integration):

- ``ai_transcript_analyses`` - one row per analyzed call/meeting activity.
  The raw transcript never lands here: it stays in core on
  ``erp_crm_activities.transcript_text`` (user-submitted CRM data plane);
  this table owns ONLY the AI product data - summary, objection score,
  objections, next-best action, sentiment, key topics, and the model's
  confidence. ``activity_id`` is a soft-link UUID with NO FK (the activity is
  owned by core in the shared database, same cross-service idiom as
  ``ai_deal_health.opportunity_id``).

Tenant-scoped (composite ``(tenant_id, id)`` PK + RLS against
``public.current_tenant_id()``, the repo-wide convention for every AI table).

Chains after 0021 (SKY-90 wave 2).

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0022"
down_revision = "0021"
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
    # --- ai_transcript_analyses: one row per analyzed activity -------------
    op.create_table(
        "ai_transcript_analyses",
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
        sa.Column("activity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("objection_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("objections", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("next_best_action", sa.Text(), nullable=True),
        sa.Column("sentiment", sa.String(16), nullable=False, server_default=sa.text("'neutral'")),
        sa.Column("key_topics", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("model_version", sa.String(64), nullable=False, server_default=sa.text("'v1'")),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "objection_score >= 0 AND objection_score <= 100",
            name="ck_ai_transcript_analyses_objection_score_range",
        ),
        sa.CheckConstraint(
            "sentiment IN ('positive', 'neutral', 'negative', 'mixed')",
            name="ck_ai_transcript_analyses_sentiment",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_ai_transcript_analyses_confidence_range",
        ),
        sa.Index(
            "idx_transcript_analyses_tenant_activity",
            "tenant_id",
            "activity_id",
        ),
        sa.Index(
            "idx_transcript_analyses_tenant_analyzed",
            "tenant_id",
            "analyzed_at",
        ),
    )

    _create_rls_policy("ai_transcript_analyses")


def downgrade() -> None:
    _drop_rls_policy("ai_transcript_analyses")
    op.drop_table("ai_transcript_analyses")
