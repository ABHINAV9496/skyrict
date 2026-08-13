"""hr_payroll: the 10 erp_* HR & Payroll tables, enums, composite FKs, RLS.

HR-DATA-001 (ticket: migration 0005_hr_payroll). All tenant-scoped tables
follow the composite-FK RLS convention established by 0001:

- composite PRIMARY KEY ``(tenant_id, id)`` — ``tenant_id`` is both the RLS
  column and a member of the key;
- every child references its parent with a composite FK ``(tenant_id, ref) ->
  parent(tenant_id, id)`` so a cross-tenant reference is impossible at the
  constraint level (referential integrity agrees with RLS);
- ``tenant_id -> tenants(id)`` uses ``ON DELETE CASCADE``; **all HR composite
  child FKs use the default NO ACTION** — an employee/department/run/leave-type
  with any referencing rows can never be hard-deleted, only retired. For an
  audit-relevant HR system an employee with leave/payroll history is never
  deleted, only moved to ``terminated``. Do not "fix" this into a cascade.

``erp_leave_movements`` and ``erp_payroll_entries`` are immutable ledger/entry
records: no ``updated_at`` column (and no update/delete endpoints in later
service tickets).

NOTES:
- ``total_gross`` / ``total_net`` are intentionally NULLABLE: NULL means
  "not yet computed", never a genuine zero-dollar run.
- ``leave_type`` on requests/movements/balances is a REAL composite FK to
  ``erp_leave_types(tenant_id, code)`` (not a logical reference), so a typo'd
  or cross-tenant leave type is rejected by the database.
- ``user_id`` / ``approved_by`` / ``computed_by`` / ``approved_by`` / ``paid_by``
  are plain UUIDs with NO FK: they reference identity users in the same shared
  database but are owned by another service's schema/RLS; validated via ports.
- ``erp_currencies`` (global, 0001) is deliberately NOT FK'd from
  ``erp_compensation.currency`` — currency is validated via Money at the
  service layer (spec §3.2).

NUMBERING GATE: this file is ``revision = "0005"`` but 0002_inventory /
0003_crm_sales / 0004_finance do not exist yet. ``down_revision = "0001"`` is
a DRAFT PLACEHOLDER — before this branch merges, 0002-0004 must land first and
``down_revision`` must be rewired to "0004" so the core chain stays linear.

Revision ID: 0005
Revises: 0001
Create Date: 2026-08-13
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0001"  # DRAFT PLACEHOLDER — rewire to "0004" before merge
branch_labels = None
depends_on = None

_TENANT_SCOPED_TABLES = (
    "erp_departments",
    "erp_employees",
    "erp_leave_types",
    "erp_leave_requests",
    "erp_leave_movements",
    "erp_leave_balances",
    "erp_compensation",
    "erp_payroll_runs",
    "erp_payroll_entries",
    "erp_payroll_settings",
)

_ENUM_TYPES = (
    "erp_employment_status",
    "erp_leave_request_status",
    "erp_payroll_run_status",
    "erp_payroll_rounding",
)


def _tenant_scoped_pk() -> list[sa.Column[Any]]:
    """The shared composite-PK column pair used by every tenant table."""
    return [
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    ]


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def _updated_at() -> sa.Column[Any]:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def upgrade() -> None:
    # --- Native enum types (migrations own type creation; models use create_type=False) ---
    op.execute("CREATE TYPE erp_employment_status AS ENUM ('active', 'on_leave', 'terminated')")
    op.execute(
        "CREATE TYPE erp_leave_request_status AS ENUM "
        "('pending', 'approved', 'rejected', 'cancelled')"
    )
    op.execute(
        "CREATE TYPE erp_payroll_run_status AS ENUM "
        "('draft', 'computed', 'approved', 'paid', 'void')"
    )
    op.execute("CREATE TYPE erp_payroll_rounding AS ENUM ('nearest', 'up', 'down')")

    emp_status = postgresql.ENUM(
        "active", "on_leave", "terminated", name="erp_employment_status", create_type=False
    )
    leave_status = postgresql.ENUM(
        "pending",
        "approved",
        "rejected",
        "cancelled",
        name="erp_leave_request_status",
        create_type=False,
    )
    run_status = postgresql.ENUM(
        "draft",
        "computed",
        "approved",
        "paid",
        "void",
        name="erp_payroll_run_status",
        create_type=False,
    )
    rounding = postgresql.ENUM(
        "nearest", "up", "down", name="erp_payroll_rounding", create_type=False
    )

    # --- erp_leave_types (tenant-scoped leave catalogue, created first) ---
    op.create_table(
        "erp_leave_types",
        *_tenant_scoped_pk(),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_accrual", sa.Boolean(), nullable=False),
        sa.Column("accrual_days_per_year", sa.Integer(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("tenant_id", "code", name="uq_erp_leave_types_tenant_code"),
    )

    # --- erp_departments (manager FK added AFTER erp_employees exists) ---
    op.create_table(
        "erp_departments",
        *_tenant_scoped_pk(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("manager_employee_id", sa.Uuid(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_erp_departments_tenant_name"),
    )

    # --- erp_employees ---
    op.create_table(
        "erp_employees",
        *_tenant_scoped_pk(),
        sa.Column("employee_number", sa.String(20), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("job_title", sa.String(100), nullable=False),
        sa.Column(
            "employment_status",
            emp_status,
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("hire_date", sa.Date(), nullable=False),
        sa.Column("termination_date", sa.Date(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["erp_departments.tenant_id", "erp_departments.id"],
            name="fk_erp_employees_department",
        ),
        sa.UniqueConstraint("tenant_id", "employee_number", name="uq_erp_employees_tenant_number"),
        sa.CheckConstraint(
            "employment_status <> 'terminated' OR termination_date IS NOT NULL",
            name="ck_erp_employees_termination_required",
        ),
    )
    op.create_index(
        "ix_erp_employees_tenant_status", "erp_employees", ["tenant_id", "employment_status"]
    )
    op.create_index(
        "ix_erp_employees_tenant_department", "erp_employees", ["tenant_id", "department_id"]
    )

    # --- erp_departments.manager_employee_id self-FK (circular dep resolution) ---
    op.create_foreign_key(
        "fk_erp_departments_manager_employee",
        "erp_departments",
        "erp_employees",
        ["tenant_id", "manager_employee_id"],
        ["tenant_id", "id"],
    )

    # --- erp_leave_requests ---
    op.create_table(
        "erp_leave_requests",
        *_tenant_scoped_pk(),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("leave_type", sa.String(32), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("status", leave_status, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_leave_requests_employee",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "leave_type"],
            ["erp_leave_types.tenant_id", "erp_leave_types.code"],
            name="fk_erp_leave_requests_leave_type",
        ),
    )
    op.create_index(
        "ix_erp_leave_requests_tenant_status", "erp_leave_requests", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_erp_leave_requests_tenant_employee", "erp_leave_requests", ["tenant_id", "employee_id"]
    )

    # --- erp_leave_movements (immutable ledger — no updated_at) ---
    op.create_table(
        "erp_leave_movements",
        *_tenant_scoped_pk(),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("leave_type", sa.String(32), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("ref_type", sa.String(32), nullable=False),
        sa.Column("ref_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_leave_movements_employee",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "leave_type"],
            ["erp_leave_types.tenant_id", "erp_leave_types.code"],
            name="fk_erp_leave_movements_leave_type",
        ),
    )
    op.create_index(
        "ix_erp_leave_movements_tenant_employee",
        "erp_leave_movements",
        ["tenant_id", "employee_id"],
    )

    # --- erp_leave_balances (materialized current balance) ---
    op.create_table(
        "erp_leave_balances",
        *_tenant_scoped_pk(),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("leave_type", sa.String(32), nullable=False),
        sa.Column("balance", sa.Integer(), nullable=False, server_default=sa.text("0")),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_leave_balances_employee",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "leave_type"],
            ["erp_leave_types.tenant_id", "erp_leave_types.code"],
            name="fk_erp_leave_balances_leave_type",
        ),
        sa.UniqueConstraint(
            "tenant_id", "employee_id", "leave_type", name="uq_erp_leave_balances_employee_type"
        ),
        sa.CheckConstraint("balance >= 0", name="ck_erp_leave_balances_non_negative"),
    )

    # --- erp_compensation (effective-dated salary history) ---
    op.create_table(
        "erp_compensation",
        *_tenant_scoped_pk(),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("monthly_salary", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_compensation_employee",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "employee_id",
            "effective_from",
            name="uq_erp_compensation_employee_effective",
        ),
    )
    op.create_index(
        "ix_erp_compensation_tenant_employee_active",
        "erp_compensation",
        ["tenant_id", "employee_id", "is_active"],
    )

    # --- erp_payroll_runs (not tied to an employee) ---
    op.create_table(
        "erp_payroll_runs",
        *_tenant_scoped_pk(),
        sa.Column("run_code", sa.String(20), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", run_status, nullable=False, server_default=sa.text("'draft'")),
        # NULLABLE on purpose: NULL = "not yet computed", never a zero-dollar run.
        sa.Column("total_gross", sa.Numeric(18, 4), nullable=True),
        sa.Column("total_net", sa.Numeric(18, 4), nullable=True),
        sa.Column("computed_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("paid_by", sa.Uuid(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("void_reason", sa.String(255), nullable=True),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("tenant_id", "run_code", name="uq_erp_payroll_runs_tenant_code"),
    )
    op.create_index(
        "ix_erp_payroll_runs_tenant_status", "erp_payroll_runs", ["tenant_id", "status"]
    )
    # A voided run keeps its row for audit but does NOT block a fresh run for
    # the same period. Blocks only identical periods; overlapping-but-different
    # periods are caught by the service-level overlap check (spec §3.2).
    op.create_index(
        "uq_erp_payroll_runs_period_active",
        "erp_payroll_runs",
        ["tenant_id", "period_start", "period_end"],
        unique=True,
        postgresql_where=sa.text("status <> 'void'"),
    )

    # --- erp_payroll_entries (immutable per-run entry — no updated_at) ---
    op.create_table(
        "erp_payroll_entries",
        *_tenant_scoped_pk(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("base_salary", sa.Numeric(18, 4), nullable=False),
        sa.Column("pay_days", sa.Integer(), nullable=False),
        sa.Column("gross", sa.Numeric(18, 4), nullable=False),
        sa.Column("deductions", sa.Numeric(18, 4), nullable=False),
        sa.Column("net", sa.Numeric(18, 4), nullable=False),
        sa.Column("adjustments", postgresql.JSONB(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["erp_payroll_runs.tenant_id", "erp_payroll_runs.id"],
            name="fk_erp_payroll_entries_run",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_payroll_entries_employee",
        ),
        sa.UniqueConstraint(
            "tenant_id", "run_id", "employee_id", name="uq_erp_payroll_entries_run_employee"
        ),
    )
    op.create_index(
        "ix_erp_payroll_entries_tenant_run", "erp_payroll_entries", ["tenant_id", "run_id"]
    )

    # --- erp_payroll_settings (single row per tenant) ---
    op.create_table(
        "erp_payroll_settings",
        *_tenant_scoped_pk(),
        sa.Column("default_currency", sa.String(3), nullable=False),
        sa.Column("pf_rate", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("tax_rate", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("rounding", rounding, nullable=False, server_default=sa.text("'nearest'")),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("tenant_id", name="uq_erp_payroll_settings_tenant"),
    )

    # --- Row-Level Security on every tenant-scoped table ---
    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON public.{table} "
            "USING (tenant_id = public.current_tenant_id()) "
            "WITH CHECK (tenant_id = public.current_tenant_id())"
        )


def downgrade() -> None:
    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON public.{table}")

    # Only the manager FK was deferred (added via ALTER after erp_employees
    # existed); employees.department_id drops inline with its table.
    op.drop_constraint("fk_erp_departments_manager_employee", "erp_departments", type_="foreignkey")

    # Reverse dependency order.
    op.drop_table("erp_payroll_settings")
    op.drop_table("erp_payroll_entries")
    op.drop_table("erp_payroll_runs")
    op.drop_table("erp_compensation")
    op.drop_table("erp_leave_balances")
    op.drop_table("erp_leave_movements")
    op.drop_table("erp_leave_requests")
    op.drop_table("erp_employees")
    op.drop_table("erp_departments")
    op.drop_table("erp_leave_types")

    for enum_type in _ENUM_TYPES:
        op.execute(f"DROP TYPE IF EXISTS {enum_type}")
