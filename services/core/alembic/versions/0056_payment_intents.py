"""Payment-matching inbox (FIN-AUT-003 B7, Commit 2).

Creates ``erp_payment_intents``: unmatched cash receipts waiting for a human
to apply them to an invoice. The table is deliberately small - it only queues
receipts and remembers the match outcome. Accepted intents move money through
the existing ``apply_payment`` path (a real ``erp_payments`` row + invoice
paid flag); the intent's ``applied_payment_id`` lets the 15-minute undo delete
exactly that row and restore the invoice status.

The partial unique index ``uq_erp_payment_intents_source_ref`` (enforced only
where ``source_ref`` is not null) is the idempotency stamp for bank-feed
pushes - a replayed feed row never double-queues. Decided thresholds live in
the service (``score >= 0.9`` auto / ``>= 0.7`` candidate / below hidden).

Follows core's tenancy convention: composite ``(tenant_id, id)`` PK,
``created_at``/``updated_at``, RLS via ``public.current_tenant_id()``.
Invoice FKs are issued as bare UUIDs (mirroring ``erp_invoices.customer_id``)
so intent rows survive invoice voiding without guarding RESTRICT cascades.

Renumbered from ``0054`` to ``0056`` when dev's HR-AI-003 L3 migrations
occupied 0053/0054.

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
        "erp_payment_intents",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(64), nullable=True),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column(
            "method",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'bank_transfer'"),
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'open'")),
        sa.Column("score", sa.Numeric(5, 4), nullable=True),
        sa.Column("suggested_invoice_id", sa.Uuid(), nullable=True),
        sa.Column("applied_invoice_id", sa.Uuid(), nullable=True),
        sa.Column("applied_payment_id", sa.Uuid(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_by", sa.Uuid(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name="ck_erp_payment_intents_amount"),
        sa.CheckConstraint(
            "status IN ('open', 'candidate', 'applied', 'dismissed')",
            name="ck_erp_payment_intents_status",
        ),
    )
    op.create_index(
        "ix_erp_payment_intents_tenant_status",
        "erp_payment_intents",
        ["tenant_id", "status"],
    )
    op.create_index(
        "uq_erp_payment_intents_source_ref",
        "erp_payment_intents",
        ["tenant_id", "source", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source_ref IS NOT NULL"),
    )
    _enable_rls("erp_payment_intents")


def downgrade() -> None:
    _disable_rls("erp_payment_intents")
    op.drop_table("erp_payment_intents")
