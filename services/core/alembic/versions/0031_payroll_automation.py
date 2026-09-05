"""Payroll automation batch engine (HR-AUT-001, Commit 1).

Creates the tenant-scoped batch/checkpoint tables for the payroll process
automation engine (commit 1 of the HR-AUT-001 plan): ``ai_payroll_batch_runs``
holds one queued/progress/finished batch per (source, source_ref) idempotency
key; ``ai_payroll_batch_items`` holds one per-employee work item with a
per-item retry budget and terminal error text. Both follow the HR-AI-001
``ai_`` table conventions: tenant-scoped with RLS enabled and composite
``(tenant_id, id)`` primary keys.

Also:
  - adds ``erp_payroll_settings.ai_automation_enabled`` (default on) so the
    automation stays a per-tenant opt-out flag;
  - adds ``erp_employees.bank_account`` / ``bank_name`` (payslip/notification
    payload fields for commit 4; additive varchar columns, no FKs);
  - seeds the four new ``erp.payroll.ai.*`` permission keys into
    ``core_permissions`` (the runtime catalog ``require_permission`` checks).

Status strings (not native enums — the codebase keeps statuses as varchar +
check constraints so they stay mutable without a type migration):
  batch:  queued | processing | completed | failed | aborted
  item:   pending | processing | done | failed

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("erp.payroll.ai.read", "View payroll automation batch runs and progress"),
    ("erp.payroll.ai.run", "Start, poll, and resume payroll automation batch runs"),
    ("erp.payroll.ai.notify", "Manage payroll automation notifications"),
    ("erp.payroll.ai.approve", "Approve payroll automation outcomes"),
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
    # --- ai_payroll_batch_runs ------------------------------------------------
    op.create_table(
        "ai_payroll_batch_runs",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("claimed_by", sa.String(64), nullable=True),
        sa.Column("preflight", postgresql.JSONB(), nullable=True),
        sa.Column("totals", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed', 'aborted')",
            name="ck_ai_payroll_batch_runs_status",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source",
            "source_ref",
            name="uq_ai_payroll_batch_runs_source",
        ),
    )
    op.create_index(
        "ix_ai_payroll_batch_runs_claim",
        "ai_payroll_batch_runs",
        ["status", "created_at"],
    )
    _enable_rls("ai_payroll_batch_runs")

    # --- ai_payroll_batch_items -----------------------------------------------
    op.create_table(
        "ai_payroll_batch_items",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["ai_payroll_batch_runs.tenant_id", "ai_payroll_batch_runs.id"],
            name="fk_ai_payroll_batch_items_batch",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_ai_payroll_batch_items_employee",
            ondelete="CASCADE",
        ),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_text", sa.String(1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed')",
            name="ck_ai_payroll_batch_items_status",
        ),
        sa.UniqueConstraint("batch_id", "employee_id", name="uq_ai_payroll_batch_items_emp"),
    )
    op.create_index(
        "ix_ai_payroll_batch_items_proc",
        "ai_payroll_batch_items",
        ["tenant_id", "batch_id", "status"],
    )
    _enable_rls("ai_payroll_batch_items")

    # --- additive ERP columns -------------------------------------------------
    op.add_column(
        "erp_payroll_settings",
        sa.Column(
            "ai_automation_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column("erp_employees", sa.Column("bank_account", sa.String(64), nullable=True))
    op.add_column("erp_employees", sa.Column("bank_name", sa.String(64), nullable=True))

    # --- Seed erp.payroll.ai.* keys into core_permissions --------------------
    for key, description in _PERMISSIONS:
        op.execute(
            "INSERT INTO core_permissions (key, description) VALUES "
            f"('{key}', '{description}') ON CONFLICT (key) DO NOTHING"
        )


def downgrade() -> None:
    for key, _description in reversed(_PERMISSIONS):
        op.execute(f"DELETE FROM core_permissions WHERE key = '{key}'")

    op.drop_column("erp_employees", "bank_account")
    op.drop_column("erp_employees", "bank_name")
    op.drop_column("erp_payroll_settings", "ai_automation_enabled")

    _disable_rls("ai_payroll_batch_items")
    op.drop_index("ix_ai_payroll_batch_items_proc", table_name="ai_payroll_batch_items")
    op.drop_table("ai_payroll_batch_items")

    _disable_rls("ai_payroll_batch_runs")
    op.drop_index("ix_ai_payroll_batch_runs_claim", table_name="ai_payroll_batch_runs")
    op.drop_table("ai_payroll_batch_runs")
