"""Create erp_report_cache table for tenant-scoped aggregate caching (SKY-99).

``erp_report_cache`` stores pre-computed JSON payloads for expensive report
aggregates (health_score, cashflow_projection, etc.) keyed by a SHA-256
``cache_key``.  The default TTL is 300 seconds (5 minutes); the
``core sweep-report-cache`` CLI command purges expired rows.

Revision ID: 0056
Revises: 0055
Create Date: 2026-09-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON public.{table} "
        "USING (tenant_id = public.current_tenant_id()) "
        "WITH CHECK (tenant_id = public.current_tenant_id())"
    )


def _disable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON public.{table}")


def upgrade() -> None:
    op.create_table(
        "erp_report_cache",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("cache_key", sa.String(128), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "hit_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now() + interval '5 minutes'"),
        ),
    )
    op.create_index(
        "uq_erp_report_cache_tenant_key",
        "erp_report_cache",
        ["tenant_id", "cache_key"],
        unique=True,
    )
    op.create_index(
        "ix_erp_report_cache_expires",
        "erp_report_cache",
        ["expires_at"],
    )
    _enable_rls("erp_report_cache")


def downgrade() -> None:
    _disable_rls("erp_report_cache")
    op.drop_index("ix_erp_report_cache_expires", "erp_report_cache")
    op.drop_index("uq_erp_report_cache_tenant_key", "erp_report_cache")
    op.drop_table("erp_report_cache")
