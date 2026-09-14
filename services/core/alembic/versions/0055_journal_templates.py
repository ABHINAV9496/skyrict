"""Recurring journal templates (FIN-AUT-003 B5, Commit 1).

Creates ``erp_journal_templates``: configuration rows (never ledger rows) that
describe a recurring DRAFT journal entry. Lines are a JSONB array of
``{account_code, debit, credit, currency}`` resolved to account ids at generate
time, so a template survives account renames. ``next_run_at`` is the next
5-field-cron match, computed by the service on create/edit and advanced after
each generate; the run-due scan reads ``enabled AND next_run_at <= now``.

Generated entries are stamped ``source='journal_template'`` with
``source_ref=f"{id}:{entry_date}"``, so the existing
``UNIQUE (tenant_id, source, source_ref)`` on ``erp_journal_entries`` makes
every scheduled occurrence exactly-once without a scheduler.

Follows core's tenancy convention: composite ``(tenant_id, id)`` PK,
``created_at``/``updated_at``, RLS via ``public.current_tenant_id()``.

Renumbered from ``0053`` to ``0055`` when dev's HR-AI-003 L3 migrations
occupied 0053/0054.

Revision ID: 0055
Revises: 0054
Create Date: 2026-09-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0055"
down_revision = "0054"
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
        "erp_journal_templates",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("cron_expression", sa.String(64), nullable=False),
        sa.Column(
            "entry_date_offset_days", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("memo", sa.String(500), nullable=True),
        sa.Column(
            "lines",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "entry_date_offset_days >= 0 AND entry_date_offset_days <= 366",
            name="ck_erp_journal_templates_entry_date_offset_days",
        ),
    )
    op.create_index(
        "ix_erp_journal_templates_tenant_due",
        "erp_journal_templates",
        ["tenant_id", "enabled", "next_run_at"],
    )
    _enable_rls("erp_journal_templates")


def downgrade() -> None:
    _disable_rls("erp_journal_templates")
    op.drop_table("erp_journal_templates")
