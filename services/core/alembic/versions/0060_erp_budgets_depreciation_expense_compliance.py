"""Finance automation wave 4 (FIN-AUT-004, SKY-85): budgets, depreciation,
expense policy & compliance calendar.

Creates eight ``erp_*`` tables:

- ``erp_budgets`` / ``erp_budget_lines`` (B21) - fiscal-year operating
  budgets keyed by account_code, with ``draft -> active -> closed`` lifecycle.
- ``erp_fixed_assets`` / ``erp_depreciation_entries`` (B13/B28) - the asset
  register plus per-period accruals. Each accrual stamps a DRAFT journal entry
  (source ``depreciation``) so the journal entries source-ref lock keeps the
  monthly run exactly-once.
- ``erp_expense_policies`` / ``erp_expense_claims`` /
  ``erp_expense_policy_violations`` (B16) - per-category expense rules, the
  claims ledger (row only exists once evaluation allows it), and persisted
  breaches with machine reason codes.
- ``erp_compliance_items`` (B27) - recurring compliance obligations driving
  the upcoming-deadline list and notification-center reminders.

Ten permission keys are seeded (mirroring identity's catalog) so role grants
stay portable: ``erp.budget.*``, ``erp.asset.*`` (incl. ``erp.asset.run``),
``erp.expense.*`` (incl. ``erp.expense.approve``), ``erp.compliance.*``.

Follows core's tenancy convention: composite ``(tenant_id, id)`` PKs,
``created_at``/``updated_at``, RLS on every table via
``public.current_tenant_id()``.

Revision ID: 0060
Revises: 0059
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0060"
down_revision = "0059"
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


_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("erp.budget.read", "Budgets - read budgets and variance reports"),
    ("erp.budget.write", "Budgets - create/activate/close operating budgets"),
    ("erp.asset.read", "Fixed assets - read the asset register and depreciation"),
    ("erp.asset.write", "Fixed assets - manage assets and disposals"),
    ("erp.asset.run", "Fixed assets - run the monthly depreciation accrual"),
    ("erp.expense.read", "Expense policy - read policies and claims"),
    ("erp.expense.write", "Expense policy - manage policies and submit claims"),
    ("erp.expense.approve", "Expense policy - approve/reject expense claims"),
    ("erp.compliance.read", "Compliance calendar - read obligations and deadlines"),
    ("erp.compliance.write", "Compliance calendar - manage obligations"),
)


def upgrade() -> None:
    # ---- Budgets (B21) -------------------------------------------------
    op.create_table(
        "erp_budgets",
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
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'USD'")),
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
    )
    op.create_index("ix_erp_budgets_tenant_status", "erp_budgets", ["tenant_id", "status"])
    op.create_index("ix_erp_budgets_tenant_year", "erp_budgets", ["tenant_id", "fiscal_year"])

    op.create_table(
        "erp_budget_lines",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "budget_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column("account_code", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_erp_budget_lines_tenant_budget", "erp_budget_lines", ["tenant_id", "budget_id"]
    )
    op.create_unique_constraint(
        "uq_erp_budget_lines_tenant_budget_code",
        "erp_budget_lines",
        ["tenant_id", "budget_id", "account_code"],
    )

    # ---- Depreciation (B13/B28) -----------------------------------------
    op.create_table(
        "erp_fixed_assets",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("cost", sa.Numeric(20, 2), nullable=False),
        sa.Column("acquisition_date", sa.Date(), nullable=False),
        sa.Column("useful_life_years", sa.Integer(), nullable=False),
        sa.Column(
            "depreciation_method",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'straight_line'"),
        ),
        sa.Column("salvage_value", sa.Numeric(20, 2), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "accumulated_depreciation",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'active'")),
        sa.Column("disposed_at", sa.Date(), nullable=True),
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
    )
    op.create_index(
        "ix_erp_fixed_assets_tenant_status", "erp_fixed_assets", ["tenant_id", "status"]
    )
    op.create_unique_constraint(
        "uq_erp_fixed_assets_tenant_name", "erp_fixed_assets", ["tenant_id", "name"]
    )

    op.create_table(
        "erp_depreciation_entries",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("journal_entry_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_erp_depreciation_entries_tenant_period",
        "erp_depreciation_entries",
        ["tenant_id", "period"],
    )
    op.create_unique_constraint(
        "uq_erp_depreciation_entries_tenant_asset_period",
        "erp_depreciation_entries",
        ["tenant_id", "asset_id", "period"],
    )

    # ---- Expense policy (B16) --------------------------------------------
    op.create_table(
        "erp_expense_policies",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("cap_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column(
            "requires_receipt", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("advance_limit", sa.Numeric(20, 2), nullable=True),
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
    )
    op.create_unique_constraint(
        "uq_erp_expense_policies_tenant_category",
        "erp_expense_policies",
        ["tenant_id", "category"],
    )

    op.create_table(
        "erp_expense_claims",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("receipt_url", sa.String(500), nullable=True),
        sa.Column("advance_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'submitted'")),
        sa.Column("source_ref", sa.String(64), nullable=True),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
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
    )
    op.create_index(
        "ix_erp_expense_claims_tenant_status", "erp_expense_claims", ["tenant_id", "status"]
    )
    op.create_unique_constraint(
        "uq_erp_expense_claims_source_ref", "erp_expense_claims", ["tenant_id", "source_ref"]
    )

    op.create_table(
        "erp_expense_policy_violations",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("message", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_erp_expense_policy_violations_tenant_code",
        "erp_expense_policy_violations",
        ["tenant_id", "reason_code"],
    )
    op.create_index(
        "ix_erp_expense_policy_violations_tenant_claim",
        "erp_expense_policy_violations",
        ["tenant_id", "claim_id"],
    )

    # ---- Compliance calendar (B27) ---------------------------------------
    op.create_table(
        "erp_compliance_items",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("obligation_type", sa.String(64), nullable=True),
        sa.Column("recurrence", sa.String(16), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("lead_days", sa.Integer(), nullable=False, server_default=sa.text("7")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'open'")),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.Uuid(), nullable=True),
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
    )
    op.create_index(
        "ix_erp_compliance_items_tenant_due",
        "erp_compliance_items",
        ["tenant_id", "status", "due_on"],
    )

    all_tables = (
        "erp_budgets",
        "erp_budget_lines",
        "erp_fixed_assets",
        "erp_depreciation_entries",
        "erp_expense_policies",
        "erp_expense_claims",
        "erp_expense_policy_violations",
        "erp_compliance_items",
    )
    for table in all_tables:
        _enable_rls(table)

    for key, description in _PERMISSIONS:
        op.execute(
            "INSERT INTO core_permissions (key, description) VALUES "
            f"('{key}', '{description}') ON CONFLICT (key) DO NOTHING"  # nosec B608
        )


def downgrade() -> None:
    for key, _ in _PERMISSIONS:
        op.execute(f"DELETE FROM core_permissions WHERE key = '{key}'")  # nosec B608

    all_tables = (
        "erp_compliance_items",
        "erp_expense_policy_violations",
        "erp_expense_claims",
        "erp_expense_policies",
        "erp_depreciation_entries",
        "erp_fixed_assets",
        "erp_budget_lines",
        "erp_budgets",
    )
    for table in all_tables:
        _disable_rls(table)

    op.drop_table("erp_compliance_items")
    op.drop_table("erp_expense_policy_violations")
    op.drop_table("erp_expense_claims")
    op.drop_table("erp_expense_policies")
    op.drop_table("erp_depreciation_entries")
    op.drop_table("erp_fixed_assets")
    op.drop_table("erp_budget_lines")
    op.drop_table("erp_budgets")
