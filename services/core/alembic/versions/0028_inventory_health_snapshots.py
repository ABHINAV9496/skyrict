"""Stock-health report snapshots + erp.inventory.cost permission (INV-ANL-001).

Lightweight M-RPT snapshot persistence for the stock-health analytics views:
``erp_report_snapshots`` stores the computed payload of a report run keyed by
``(tenant_id, definition_slug, period)`` so history is queryable and a manual
refresh is idempotent per definition+period — before the full
definitions/dashboards reporting workspace lands (see docs/architecture/
erp-phase1.md, M-RPT section). Only core-owned inventory reports are persisted
here for now; the wider reporting workspace is a follow-up.

Also seeds the ``erp.inventory.cost`` permission used to gate server-side the
cost-price valuations (dead-stock tied-up capital, slow-mover carrying cost)
returned by these reports. Unit-cost access is a distinct capability from
``erp.inventory.read``: read grants the aggregate counts, cost grants the
money figures.

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_TABLE = "erp_report_snapshots"

_PERMISSIONS: tuple[tuple[str, str], ...] = (
    (
        "erp.inventory.cost",
        "View cost-price valuations in inventory reports (dead stock / slow movers)",
    ),
)


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
        _TABLE,
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("definition_slug", sa.String(64), nullable=False),
        sa.Column("period", sa.String(32), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "definition_slug",
            "period",
            name="uq_erp_report_snapshots_def_period",
        ),
    )
    op.create_index(
        "ix_erp_report_snapshots_tenant_slug",
        _TABLE,
        ["tenant_id", "definition_slug"],
    )
    _enable_rls(_TABLE)

    for key, description in _PERMISSIONS:
        op.execute(
            "INSERT INTO core_permissions (key, description) VALUES "
            f"('{key}', '{description}') ON CONFLICT (key) DO NOTHING"
        )


def downgrade() -> None:
    for key, _ in _PERMISSIONS:
        op.execute(f"DELETE FROM core_permissions WHERE key = '{key}'")

    _disable_rls(_TABLE)
    op.drop_table(_TABLE)
