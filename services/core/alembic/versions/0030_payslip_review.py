"""Payslip review queue — versioned approval with delivery-gate (HR-AUT-001, Commit 2).

``erp_payslip_reviews`` is the persistent, versioned payslip review table that
replaces the previously read-only projection (``list_run_payslips``). Each row
represents one employee's computed payslip in a specific run, with an approval
lifecycle: ``draft`` -> ``approved`` or ``draft`` -> ``rejected``. A re-approval
after correction creates a new version row (unique constraint on tenant +
run + employee + version).

``status`` has a CHECK constraint rather than a native enum so a future
ticket can add intermediate states (e.g. ``under_review``) without a
migration.

``version`` increments per (tenant, run, employee) on re-approval, enabling
the notification delivery-gate to fire only once per approved version.

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erp_payslip_reviews",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("employee_number", sa.String(32), nullable=False),
        sa.Column("employee_name", sa.String(128), nullable=False),
        sa.Column("gross", sa.Numeric(18, 4), nullable=False),
        sa.Column("deductions", sa.Numeric(18, 4), nullable=False),
        sa.Column("net", sa.Numeric(18, 4), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("rejected_reason", sa.String(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.Uuid(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["erp_payroll_runs.tenant_id", "erp_payroll_runs.id"],
            name="fk_erp_payslip_reviews_run",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_payslip_reviews_employee",
        ),
    )

    op.create_check_constraint(
        "ck_erp_payslip_reviews_status",
        "erp_payslip_reviews",
        "status IN ('draft', 'approved', 'rejected')",
    )

    op.create_index(
        "ix_erp_payslip_reviews_tenant_status",
        "erp_payslip_reviews",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_erp_payslip_reviews_tenant_run",
        "erp_payslip_reviews",
        ["tenant_id", "run_id"],
    )
    op.create_unique_constraint(
        "uq_erp_payslip_reviews_run_employee_version",
        "erp_payslip_reviews",
        ["tenant_id", "run_id", "employee_id", "version"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_erp_payslip_reviews_run_employee_version",
        "erp_payslip_reviews",
        type_="unique",
    )
    op.drop_index("ix_erp_payslip_reviews_tenant_run", "erp_payslip_reviews")
    op.drop_index("ix_erp_payslip_reviews_tenant_status", "erp_payslip_reviews")
    op.drop_constraint("ck_erp_payslip_reviews_status", "erp_payslip_reviews", type_="check")
    op.drop_table("erp_payslip_reviews")
