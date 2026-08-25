"""erp_attendance_records — one attendance row per employee per work day

Attendance is recorded daily per employee with a status of ``on_time``,
``late``, or ``absent``. The payroll-facing ``pay_impact`` column is derived
by the service from the status (on_time -> full, late -> half, absent ->
none) and stored for queryability; it is never trusted from clients. One
record per ``(tenant_id, employee_id, work_date)`` — corrections upsert the
existing day instead of adding history rows.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    status = postgresql.ENUM(
        "on_time",
        "late",
        "absent",
        name="erp_attendance_status",
        # Migrations own type creation; columns must not re-create it.
        create_type=False,
    )
    status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "erp_attendance_records",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        # Composite soft-FK to the tenant's employee (same convention as
        # erp_leave_requests): a typo'd or cross-tenant employee is rejected.
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_attendance_records_employee",
        ),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("status", status, nullable=False),
        sa.Column("pay_impact", sa.String(8), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
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
            "pay_impact IN ('full', 'half', 'none')",
            name="ck_erp_attendance_records_pay_impact",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "employee_id",
            "work_date",
            name="uq_erp_attendance_records_employee_day",
        ),
    )
    op.create_index(
        "ix_erp_attendance_records_tenant_date",
        "erp_attendance_records",
        ["tenant_id", "work_date"],
    )

    op.execute("ALTER TABLE public.erp_attendance_records ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_erp_attendance_records ON public.erp_attendance_records "
        "USING (tenant_id = public.current_tenant_id()) "
        "WITH CHECK (tenant_id = public.current_tenant_id())"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE public.erp_attendance_records DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_erp_attendance_records ON public.erp_attendance_records")

    op.drop_index("ix_erp_attendance_records_tenant_date", table_name="erp_attendance_records")
    op.drop_table("erp_attendance_records")
    op.execute("DROP TYPE IF EXISTS erp_attendance_status")
