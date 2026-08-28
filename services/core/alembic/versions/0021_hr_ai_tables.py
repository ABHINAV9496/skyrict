"""HR/Payroll AI tables (HR-AI-001, Commit 2).

Creates the tenant-scoped AI tables described in
``docs/modules/skyrict-ai/hr-payroll-ai-features.md`` §11, plus the compliance
source table ``erp_employee_documents``, and seeds the new ``erp.hr.ai.*``
permission keys into ``core_permissions`` (the runtime catalog that
``require_permission`` checks).

Tables:
  - ``erp_employee_documents``   source for document/training compliance rules
  - ``ai_hr_attrition_scores``   per-employee attrition score + top-3 factors
  - ``ai_payroll_anomaly_log``   payroll anomaly findings w/ severity + status
  - ``ai_compliance_checks``     compliance findings w/ owner routing + status

All AI tables use the ``ai_`` prefix, are tenant-scoped with RLS enabled, and
use composite ``(tenant_id, id)`` primary keys with composite FKs to
``erp_employees`` / ``erp_payroll_runs``.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021"
down_revision = "0020"
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
    doc_type = postgresql.ENUM(
        "work_permit",
        "visa",
        "national_id",
        "passport",
        "contract",
        "certification",
        "medical",
        "other",
        name="erp_document_type",
        create_type=False,
    )
    doc_type.create(op.get_bind(), checkfirst=True)

    # --- erp_employee_documents ---------------------------------------------
    op.create_table(
        "erp_employee_documents",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_employee_documents_employee",
        ),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("doc_type", doc_type, nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
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
            "status IN ('active', 'expired', 'archived')",
            name="ck_erp_employee_documents_status",
        ),
    )
    op.create_index(
        "ix_erp_employee_documents_tenant_employee",
        "erp_employee_documents",
        ["tenant_id", "employee_id"],
    )
    _enable_rls("erp_employee_documents")

    # --- ai_hr_attrition_scores ----------------------------------------------
    op.create_table(
        "ai_hr_attrition_scores",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_ai_hr_attrition_scores_employee",
        ),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        # Denormalized for L1 grouping; NO hard FK (department may be NULL/soft).
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("score", sa.Numeric(5, 4), nullable=False),
        sa.Column("risk_band", sa.String(8), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column(
            "factors", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "acknowledged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("acknowledged_by", sa.Uuid(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "risk_band IN ('low', 'medium', 'high')",
            name="ck_ai_hr_attrition_scores_risk_band",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "employee_id",
            "model_version",
            name="uq_ai_hr_attrition_scores_employee_model",
        ),
    )
    op.create_index(
        "ix_ai_hr_attrition_scores_dept_band",
        "ai_hr_attrition_scores",
        ["tenant_id", "department_id", "risk_band"],
    )
    op.create_index(
        "ix_ai_hr_attrition_scores_generated",
        "ai_hr_attrition_scores",
        ["tenant_id", "generated_at"],
    )
    op.create_index(
        "ix_ai_hr_attrition_scores_acknowledged",
        "ai_hr_attrition_scores",
        ["tenant_id", "acknowledged"],
    )
    _enable_rls("ai_hr_attrition_scores")

    # --- ai_payroll_anomaly_log ----------------------------------------------
    op.create_table(
        "ai_payroll_anomaly_log",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["erp_payroll_runs.tenant_id", "erp_payroll_runs.id"],
            name="fk_ai_payroll_anomaly_log_run",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_ai_payroll_anomaly_log_employee",
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column(
            "anomaly_type",
            sa.String(24),
            nullable=False,
        ),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column(
            "evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("status", sa.String(14), nullable=False, server_default="open"),
        sa.Column("acknowledged_by", sa.Uuid(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "anomaly_type IN ('net_pay_delta', 'duplicate_account', 'ghost_employee')",
            name="ck_ai_payroll_anomaly_log_type",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_ai_payroll_anomaly_log_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'dismissed', 'resolved')",
            name="ck_ai_payroll_anomaly_log_status",
        ),
    )
    op.create_index(
        "ix_ai_payroll_anomaly_log_run",
        "ai_payroll_anomaly_log",
        ["tenant_id", "run_id"],
    )
    _enable_rls("ai_payroll_anomaly_log")

    # --- ai_compliance_checks -------------------------------------------------
    op.create_table(
        "ai_compliance_checks",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_ai_compliance_checks_employee",
        ),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column(
            "check_type",
            sa.String(30),
            nullable=False,
        ),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("owner_rule", sa.String(64), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(14), nullable=False, server_default="open"),
        sa.Column(
            "evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "check_type IN ('document_expiry', 'training_overdue', 'contract_missing_field')",
            name="ck_ai_compliance_checks_type",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_ai_compliance_checks_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')",
            name="ck_ai_compliance_checks_status",
        ),
    )
    op.create_index(
        "ix_ai_compliance_checks_tenant_type",
        "ai_compliance_checks",
        ["tenant_id", "check_type"],
    )
    _enable_rls("ai_compliance_checks")

    # --- Seed erp.hr.ai.* keys into core_permissions (runtime catalog) -------
    _permissions = (
        ("erp.hr.ai.read", "View aggregate (L1) HR & Payroll AI panels"),
        ("erp.hr.ai.individual", "View individual (L2) attrition scores + factor explanations"),
        ("erp.hr.ai.acknowledge", "Acknowledge a team-risk item (audited)"),
        ("erp.hr.ai.copilot", "Use the HR Copilot agent"),
    )
    for key, description in _permissions:
        op.execute(
            "INSERT INTO core_permissions (key, description) VALUES "
            f"('{key}', '{description}') ON CONFLICT (key) DO NOTHING"
        )


def downgrade() -> None:
    for table in (
        "ai_compliance_checks",
        "ai_payroll_anomaly_log",
        "ai_hr_attrition_scores",
        "erp_employee_documents",
    ):
        _disable_rls(table)
    op.drop_index("ix_ai_compliance_checks_tenant_type", table_name="ai_compliance_checks")
    op.drop_table("ai_compliance_checks")
    op.drop_index("ix_ai_payroll_anomaly_log_run", table_name="ai_payroll_anomaly_log")
    op.drop_table("ai_payroll_anomaly_log")
    op.drop_index("ix_ai_hr_attrition_scores_dept_band", table_name="ai_hr_attrition_scores")
    op.drop_index("ix_ai_hr_attrition_scores_generated", table_name="ai_hr_attrition_scores")
    op.drop_index("ix_ai_hr_attrition_scores_acknowledged", table_name="ai_hr_attrition_scores")
    op.drop_table("ai_hr_attrition_scores")
    op.drop_index("ix_erp_employee_documents_tenant_employee", table_name="erp_employee_documents")
    op.drop_table("erp_employee_documents")
    op.execute("DROP TYPE IF EXISTS erp_document_type")

    for key in (
        "erp.hr.ai.read",
        "erp.hr.ai.individual",
        "erp.hr.ai.acknowledge",
        "erp.hr.ai.copilot",
    ):
        op.execute(f"DELETE FROM core_permissions WHERE key = '{key}'")
