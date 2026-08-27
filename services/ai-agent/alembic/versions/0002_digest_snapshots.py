"""AI digest snapshots - cached cross-module narrator digests (SKY-63).

Creates ``ai_digest_snapshots`` in the shared ``skyrict_identity`` database,
following the 0001 idioms: composite ``(tenant_id, id)`` PK, RLS against
``public.current_tenant_id()``, cross-service UUID columns with no FK.

A digest row is written per generation; freshness/caching is derived by
picking the newest row for a tenant + date. ``signals`` stores the compact
cross-module gold signals the digest was computed from.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_TENANT_SCOPED_TABLES = ("ai_digest_snapshots",)


# ---------------------------------------------------------------------------
# Schema helpers (shared idiom across the core/ai-agent chains)
# ---------------------------------------------------------------------------
def _tenant_scoped_pk(fk: bool) -> list[Any]:
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


def _create_rls_policy(table: str) -> None:
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON public.{table} "
        "USING (tenant_id = public.current_tenant_id()) "
        "WITH CHECK (tenant_id = public.current_tenant_id())"
    )


def _drop_rls_policy(table: str) -> None:
    op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON public.{table}")


def upgrade() -> None:
    op.create_table(
        "ai_digest_snapshots",
        *_tenant_scoped_pk(fk=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'generated'"),
        ),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("points", postgresql.JSONB(), nullable=True),
        sa.Column("caveat", sa.Text(), nullable=True),
        sa.Column("signals", postgresql.JSONB(), nullable=True),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_ai_digest_snapshots_tenant_as_of",
        "ai_digest_snapshots",
        ["tenant_id", "as_of", sa.text("generated_at DESC")],
    )

    for table in _TENANT_SCOPED_TABLES:
        _create_rls_policy(table)


def downgrade() -> None:
    for table in _TENANT_SCOPED_TABLES:
        _drop_rls_policy(table)
    op.drop_table("ai_digest_snapshots")
