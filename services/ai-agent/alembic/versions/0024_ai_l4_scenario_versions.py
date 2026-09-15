"""L4 what-if scenario snapshots: ai_l4_scenario_versions (SKY-93, Commit 2).

Lands the persistence layer for the L4 workforce-cost planning what-if
simulator (SKY-93):

- ``ai_l4_scenario_versions`` - one named, versioned scenario per planning
  session.  Stores the normalized actions (request) and the deterministic
  projection (snapshot) as JSONB.  Projections are frozen at save time so
  reads are deterministic even as the live roster evolves.

Tenant-scoped (composite ``(tenant_id, id)`` PK + RLS against
``public.current_tenant_id()``, the repo-wide convention for every AI table).

Chains after 0023 (SKY-91 CRM anomalies).

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0024"
down_revision = "0023"
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
    # --- ai_l4_scenario_versions: named what-if scenarios with frozen projections -----
    op.create_table(
        "ai_l4_scenario_versions",
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
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("base_as_of", sa.Date(), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "actions",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "projection",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "horizon >= 1 AND horizon <= 36",
            name="ck_ai_l4_scenario_versions_horizon",
        ),
        sa.Index(
            "idx_ai_l4_scenario_versions_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )

    _create_rls_policy("ai_l4_scenario_versions")


def downgrade() -> None:
    _drop_rls_policy("ai_l4_scenario_versions")
    op.drop_table("ai_l4_scenario_versions")
