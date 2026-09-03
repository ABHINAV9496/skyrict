"""SKY-62 erp dashboards - per-user layout customization + widget telemetry.

Adds the data layer for the ERP dashboard customizer:

  - ``erp_dashboards``              tenant-level default dashboard layouts
  - ``user_dashboard_layouts``      per-user layout overrides (unique per tenant)
  - ``widget_events``               lightweight widget interaction telemetry

Each tenant gets one default dashboard (``tenant_default = true``).  Users
may override it with a personal layout stored in ``user_dashboard_layouts``.
Widget open/hide events are recorded in ``widget_events`` for the AI-powered
layout suggestion engine.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
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
    # --- erp_dashboards -------------------------------------------------------
    op.create_table(
        "erp_dashboards",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(128), nullable=False, server_default=sa.text("'Default'")),
        sa.Column(
            "layout",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "tenant_default",
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
    op.execute("COMMENT ON TABLE public.erp_dashboards IS 'Tenant-level default dashboard layouts'")
    op.create_index(
        "ix_erp_dashboards_tenant_default",
        "erp_dashboards",
        ["tenant_id", "tenant_default"],
        unique=False,
    )
    _enable_rls("erp_dashboards")

    # --- user_dashboard_layouts -----------------------------------------------
    op.create_table(
        "user_dashboard_layouts",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "layout",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            name="uq_user_dashboard_layouts_tenant_user",
        ),
    )
    op.execute(
        "COMMENT ON TABLE public.user_dashboard_layouts IS "
        "'Per-user dashboard layout overrides, unique per tenant'"
    )
    _enable_rls("user_dashboard_layouts")

    # --- widget_events --------------------------------------------------------
    op.create_table(
        "widget_events",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("widget_id", sa.String(64), nullable=False),
        sa.Column(
            "event",
            sa.String(16),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "event IN ('open', 'hide')",
            name="ck_widget_events_event",
        ),
    )
    op.execute(
        "COMMENT ON TABLE public.widget_events IS "
        "'Lightweight widget interaction telemetry for AI suggestions'"
    )
    op.create_index(
        "ix_widget_events_tenant_widget",
        "widget_events",
        ["tenant_id", "widget_id"],
        unique=False,
    )
    op.create_index(
        "ix_widget_events_tenant_user",
        "widget_events",
        ["tenant_id", "user_id"],
        unique=False,
    )
    _enable_rls("widget_events")

    # --- permission seed ------------------------------------------------------
    op.execute(
        "INSERT INTO core_permissions (key, description) VALUES "
        "('erp.dashboard.manage', 'Manage ERP dashboard layouts') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    # Revoke permission
    op.execute("DELETE FROM core_permissions WHERE key = 'erp.dashboard.manage'")

    _disable_rls("widget_events")
    op.drop_index("ix_widget_events_tenant_user", table_name="widget_events")
    op.drop_index("ix_widget_events_tenant_widget", table_name="widget_events")
    op.drop_table("widget_events")

    _disable_rls("user_dashboard_layouts")
    op.drop_table("user_dashboard_layouts")

    _disable_rls("erp_dashboards")
    op.drop_index("ix_erp_dashboards_tenant_default", table_name="erp_dashboards")
    op.drop_table("erp_dashboards")
