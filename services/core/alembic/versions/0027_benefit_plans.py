"""Benefit plans + elections (HR-AUT-001, pre-flight finish-up).

Creates the tenant-scoped benefit catalogue the pre-flight ``benefit_elections``
warning check reads: ``erp_benefit_plans`` holds the plans a tenant offers
(medical/retirement/etc.), ``erp_benefit_elections`` records per-employee
``enrolled``/``waived`` elections effective-dated by ``effective_from``. Both
follow the ERD conventions: tenant-scoped with RLS enabled and composite
``(tenant_id, id)`` primary keys.

Status strings (not native enums — the codebase keeps statuses as varchar +
check constraints so they stay mutable without a type migration):
  election: enrolled | waived

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-30
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
    # --- erp_benefit_plans ---------------------------------------------------
    op.create_table(
        "erp_benefit_plans",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("plan_code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("plan_type", sa.String(20), nullable=False),
        sa.Column("monthly_cost_cents", sa.Numeric(18, 0), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("effective_from", sa.Date(), nullable=False),
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
            "plan_type IN ('medical', 'dental', 'retirement', 'other')",
            name="ck_erp_benefit_plans_type",
        ),
        sa.UniqueConstraint(
            "tenant_id", "plan_code", name="uq_erp_benefit_plans_tenant_code"
        ),
    )
    _enable_rls("erp_benefit_plans")

    # --- erp_benefit_elections -----------------------------------------------
    op.create_table(
        "erp_benefit_elections",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_benefit_elections_employee",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "plan_id"],
            ["erp_benefit_plans.tenant_id", "erp_benefit_plans.id"],
            name="fk_erp_benefit_elections_plan",
        ),
        sa.CheckConstraint(
            "status IN ('enrolled', 'waived')",
            name="ck_erp_benefit_elections_status",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "employee_id",
            "plan_id",
            "effective_from",
            name="uq_erp_benefit_elections_employee_plan_effective",
        ),
    )
    _enable_rls("erp_benefit_elections")


def downgrade() -> None:
    _disable_rls("erp_benefit_elections")
    op.drop_table("erp_benefit_elections")
    _disable_rls("erp_benefit_plans")
    op.drop_table("erp_benefit_plans")
