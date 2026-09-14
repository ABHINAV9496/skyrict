"""Smart notification center tables (SKY-93, PLT-NOTIF-001).

Renumbered from ``0053`` on merge with dev: dev's HR-AI-003 chain took
``0053_hr_ai_management_permission`` and ``0054_ai_l3_refresh_permission``,
so this migration chains after ``0054`` as head ``0055`` (single alembic head).

Creates the three tables backing the unified notification center:

- ``erp_notification_events`` - one row per inbound producer event, idempotent
  by ``(tenant_id, dedupe_key)``. A producer may emit the same event many
  times; only the first insert wins (``ON CONFLICT DO NOTHING``), which gives
  at-least-once producers a safe dedupe anchor.
- ``erp_notifications`` - one delivery row per recipient per event. Priority
  scoring (severity x recency x role relevance), pinning (``is_pinned`` for
  critical), burst batching (``is_digest``/``digest_count`` with the originals
  marked ``digest_suppressed``) and per-user read/snooze state live here.
  ``dedupe_key`` is unique per recipient so re-emitting an event never creates
  a second copy for the same user. Mandatory categories are never
  ``is_dismissible=False`` at delivery time and cannot be snoozed or opted
  out of server-side.
- ``erp_notification_prefs`` - per-user, per-category channel opt-outs
  (``in_app`` on by default; email/webhook off by default). Mandatory
  categories ignore the opt-outs for ``in_app``; email/webhook honour the
  config master switches (log-only adapters this sprint).

Every table follows core's tenancy convention: composite ``(tenant_id, id)``
primary key, ``created_at``/``updated_at`` audit columns, RLS enforced via the
``public.current_tenant_id()`` policy. Reads against ``erp_notifications``
are additionally scoped to the recipient in the query layer (RLS only
guarantees the tenant; recipient scoping is an application rule because the
worker and producers legitimately write rows for many users).

Revision ID: 0055
Revises: 0054
Create Date: 2026-09-13
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
        "erp_notification_events",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("recipient_kind", sa.String(16), nullable=False),
        sa.Column("recipient_value", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("relevance_key", sa.String(100), nullable=True),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "is_dismissible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
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
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_erp_notification_events_severity",
        ),
        sa.CheckConstraint(
            "recipient_kind IN ('users', 'permission', 'role')",
            name="ck_erp_notification_events_recipient_kind",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "dedupe_key",
            name="uq_erp_notification_events_tenant_dedupe_key",
        ),
    )
    op.create_index(
        "ix_erp_notification_events_tenant_category_occurred",
        "erp_notification_events",
        ["tenant_id", "category", "occurred_at"],
    )
    op.create_index(
        "ix_erp_notification_events_tenant_module_occurred",
        "erp_notification_events",
        ["tenant_id", "module", "occurred_at"],
    )
    _enable_rls("erp_notification_events")

    op.create_table(
        "erp_notifications",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        # Logical reference to erp_notification_events.id (no FK: events are
        # append-only and the id alone would be joinable across RLS scopes).
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("priority_score", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_digest", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("digest_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "digest_suppressed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_dismissible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "channels",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{\"in_app\": true}'::jsonb"),
        ),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
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
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_erp_notifications_severity",
        ),
        sa.CheckConstraint(
            "priority_score BETWEEN 0 AND 100",
            name="ck_erp_notifications_priority_score",
        ),
        sa.CheckConstraint(
            "digest_count >= 1",
            name="ck_erp_notifications_digest_count",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "recipient_user_id",
            "dedupe_key",
            name="uq_erp_notifications_tenant_recipient_dedupe",
        ),
    )
    op.create_index(
        "ix_erp_notifications_recipient_unread",
        "erp_notifications",
        ["tenant_id", "recipient_user_id", "read_at"],
    )
    op.create_index(
        "ix_erp_notifications_recipient_created",
        "erp_notifications",
        ["tenant_id", "recipient_user_id", "created_at"],
    )
    op.create_index(
        "ix_erp_notifications_recipient_suppressed_severity",
        "erp_notifications",
        ["tenant_id", "recipient_user_id", "digest_suppressed", "severity"],
    )
    op.create_index(
        "ix_erp_notifications_pinned_unread",
        "erp_notifications",
        ["tenant_id", "is_pinned", "read_at"],
    )
    _enable_rls("erp_notifications")

    op.create_table(
        "erp_notification_prefs",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("in_app_on", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("email_on", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("webhook_on", sa.Boolean(), nullable=False, server_default=sa.text("false")),
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
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "category",
            name="uq_erp_notification_prefs_tenant_user_category",
        ),
    )
    op.create_index(
        "ix_erp_notification_prefs_user",
        "erp_notification_prefs",
        ["tenant_id", "user_id"],
    )
    _enable_rls("erp_notification_prefs")


def downgrade() -> None:
    for table in (
        "erp_notification_prefs",
        "erp_notifications",
        "erp_notification_events",
    ):
        _disable_rls(table)
        op.drop_table(table)
