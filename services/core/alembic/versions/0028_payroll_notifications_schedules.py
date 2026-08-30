"""Payroll automation notifications + schedules (HR-AUT-001, Commit 3).

Commit 3 of the HR-AUT-001 plan adds the post-commit notification orchestrator
and the per-tenant recurring scheduler:

``ai_payroll_notifications``
    One row per (tenant, recipient_user_id, dedupe_key). Two event kinds:
    ``payslip_ready`` — created for every employee with a committed payslip
    entry after a batch completes, routed by the employee's own preference
    (``in-app`` always, ``email_stub`` only when opted in); and
    ``payroll_batch_digest`` — one row per payroll admin (holders of
    ``erp.payroll.ai.read``) with the batch's totals and failure list. The
    unique ``(tenant_id, recipient_user_id, dedupe_key)`` constraint is the
    dedupe: re-running the orchestrator after a batch finishes can never create
    a second row for the same recipient + event (the acceptance criterion
    "each employee holds exactly one notification row").

``ai_payroll_notification_prefs``
    Employee delivery preferences. A row carries ``in_app_on`` (default true)
    and ``email_on`` (default false); NO row means exactly those defaults
    (in-app ON, email OFF), so routing is defined without any seeding.

``ai_payroll_schedules``
    Per-tenant recurring batch submissions (scheduler section 5.8): a 5-field
    cron expression plus an enable flag. ``next_run_at`` is the cron-derived
    next due timestamp; when due the automation worker creates (or reuses) the
    payroll run for the last fully-elapsed calendar month and submits it
    through the existing enqueue path.

All three follow the ``ai_`` table conventions from 0026: tenant-scoped,
RLS enabled, composite ``(tenant_id, id)`` primary keys (prefs key on
``(tenant_id, user_id)`` — one row per user).

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_NOTIFICATION_EVENT_TYPES = ("payslip_ready", "payroll_batch_digest")


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
    # --- ai_payroll_notifications --------------------------------------------
    op.create_table(
        "ai_payroll_notifications",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("dedupe_key", sa.String(96), nullable=False),
        sa.Column("in_app", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "email_stub",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("subject", sa.String(160), nullable=False),
        sa.Column("body", sa.String(4000), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
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
            "event_type IN "
            "('payslip_ready', 'payroll_batch_digest')",
            name="ck_ai_payroll_notifications_event_type",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "recipient_user_id",
            "dedupe_key",
            name="uq_ai_payroll_notifications_dedupe",
        ),
    )
    op.create_index(
        "ix_ai_payroll_notifications_inbox",
        "ai_payroll_notifications",
        ["tenant_id", "recipient_user_id", "created_at"],
    )
    _enable_rls("ai_payroll_notifications")

    # --- ai_payroll_notification_prefs ---------------------------------------
    op.create_table(
        "ai_payroll_notification_prefs",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "in_app_on",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "email_on",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
    )
    _enable_rls("ai_payroll_notification_prefs")

    # --- ai_payroll_schedules -------------------------------------------------
    op.create_table(
        "ai_payroll_schedules",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(64), nullable=True),
        sa.Column("cron_expression", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "ix_ai_payroll_schedules_due",
        "ai_payroll_schedules",
        ["tenant_id", "enabled", "next_run_at"],
    )
    _enable_rls("ai_payroll_schedules")


def downgrade() -> None:
    _disable_rls("ai_payroll_schedules")
    op.drop_index("ix_ai_payroll_schedules_due", table_name="ai_payroll_schedules")
    op.drop_table("ai_payroll_schedules")

    _disable_rls("ai_payroll_notification_prefs")
    op.drop_table("ai_payroll_notification_prefs")

    _disable_rls("ai_payroll_notifications")
    op.drop_index("ix_ai_payroll_notifications_inbox", table_name="ai_payroll_notifications")
    op.drop_table("ai_payroll_notifications")

