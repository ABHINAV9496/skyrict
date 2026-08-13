"""finance: the 7 erp_* Finance & Accounting tables, enums, CHECKs, RLS.

FIN-DATA-001 (ticket: migration 0004_finance). Follows the composite-FK RLS
convention established by 0001 and the enum/helper pattern from 0005:

- composite PRIMARY KEY ``(tenant_id, id)`` on every tenant table;
- ``tenant_id -> tenants(id)`` ON DELETE CASCADE; finance child FKs use
  RESTRICT (history is eternal) except invoice lines -> invoice (CASCADE);
- double-entry invariants as CHECK constraints: each journal line is exactly
  one of debit/credit (XOR), non-zero, non-negative;
- ``UNIQUE (tenant_id, source, source_ref)`` on journal entries and payments
  = the idempotency lock: a replayed request with the same stamp can never
  create a second row (NULL source_ref stays distinct, so unlimited manual
  entries are allowed);
- ``UNIQUE (tenant_id, code)`` COA, ``UNIQUE (tenant_id, name)`` fiscal
  periods, ``UNIQUE (tenant_id, invoice_number)`` / ``payment_number``;
- ``seq_erp_invoice_number`` / ``seq_erp_payment_number`` are the global
  counters the repository reads via nextval() to build INV-/PMT- numbers
  (format ``{prefix}-{year}-{seq:05d}``);
- RLS policy on every tenant-scoped table (docs section 2.3).

NUMBERING NOTE: the ticket calls this "0004" (original plan 0001 -> 0002 ->
0003_crm_sales -> 0004_finance). 0003 never landed and HR/Payroll merged as
revision 0005 with down_revision "0002". To honour the ticket's number while
keeping a single linear chain, this migration is revision "0004" with
down_revision "0005": 0001 -> 0002 -> 0005 -> 0004 (chain order, not numeric
order). ``alembic_version_core`` head = "0004".

Revision ID: 0004
Revises: 0005
Create Date: 2026-08-13
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0005"
branch_labels = None
depends_on = None

_TENANT_SCOPED_TABLES = (
    "erp_chart_of_accounts",
    "erp_fiscal_periods",
    "erp_journal_entries",
    "erp_journal_lines",
    "erp_invoices",
    "erp_invoice_lines",
    "erp_payments",
)

_ENUM_TYPES = (
    "erp_account_type",
    "erp_entry_status",
    "erp_invoice_status",
    "erp_payment_status",
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
    op.execute(
        "CREATE TYPE erp_account_type AS ENUM "
        "('asset', 'liability', 'equity', 'revenue', 'expense')"
    )
    op.execute("CREATE TYPE erp_entry_status AS ENUM ('draft', 'posted', 'voided')")
    op.execute(
        "CREATE TYPE erp_invoice_status AS ENUM ('draft', 'issued', 'approved', 'paid', 'voided')"
    )
    op.execute("CREATE TYPE erp_payment_status AS ENUM ('applied')")

    account_type = postgresql.ENUM(
        "asset",
        "liability",
        "equity",
        "revenue",
        "expense",
        name="erp_account_type",
        create_type=False,
    )
    entry_status = postgresql.ENUM(
        "draft", "posted", "voided", name="erp_entry_status", create_type=False
    )
    invoice_status = postgresql.ENUM(
        "draft",
        "issued",
        "approved",
        "paid",
        "voided",
        name="erp_invoice_status",
        create_type=False,
    )
    payment_status = postgresql.ENUM("applied", name="erp_payment_status", create_type=False)

    # --- Global numbering sequences (consumed by nextval() in the repository) ---
    op.execute("CREATE SEQUENCE seq_erp_invoice_number")
    op.execute("CREATE SEQUENCE seq_erp_payment_number")

    # --- erp_chart_of_accounts (created first: referenced by every other table) ---
    op.create_table(
        "erp_chart_of_accounts",
        *_tenant_scoped_pk(),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("account_type", account_type, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("tenant_id", "code", name="uq_erp_chart_of_accounts_tenant_code"),
    )

    # --- erp_fiscal_periods ---
    op.create_table(
        "erp_fiscal_periods",
        *_tenant_scoped_pk(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_erp_fiscal_periods_tenant_name"),
        sa.CheckConstraint("end_date >= start_date", name="ck_erp_fiscal_periods_date_range"),
    )

    # --- erp_journal_entries ---
    op.create_table(
        "erp_journal_entries",
        *_tenant_scoped_pk(),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("memo", sa.String(500), nullable=True),
        sa.Column("status", entry_status, nullable=False, server_default=sa.text("'draft'")),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(64), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint(
            "tenant_id", "source", "source_ref", name="uq_erp_journal_entries_source_ref"
        ),
    )
    op.create_index(
        "ix_erp_journal_entries_tenant_entry_date",
        "erp_journal_entries",
        ["tenant_id", "entry_date"],
    )
    op.create_index(
        "ix_erp_journal_entries_tenant_status",
        "erp_journal_entries",
        ["tenant_id", "status"],
    )

    # --- erp_journal_lines (double-entry invariants as CHECKs) ---
    op.create_table(
        "erp_journal_lines",
        *_tenant_scoped_pk(),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("debit", sa.Numeric(18, 4), nullable=True),
        sa.Column("credit", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'USD'")),
        sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=False, server_default=sa.text("1")),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "entry_id"],
            ["erp_journal_entries.tenant_id", "erp_journal_entries.id"],
            name="fk_erp_journal_lines_entry",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["erp_chart_of_accounts.tenant_id", "erp_chart_of_accounts.id"],
            name="fk_erp_journal_lines_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["currency"], ["erp_currencies.code"], name="fk_erp_journal_lines_currency"
        ),
        sa.CheckConstraint(
            "(debit IS NOT NULL AND credit IS NULL) OR (debit IS NULL AND credit IS NOT NULL)",
            name="ck_erp_journal_lines_debit_xor_credit",
        ),
        sa.CheckConstraint(
            "(debit IS NULL OR debit <> 0) AND (credit IS NULL OR credit <> 0)",
            name="ck_erp_journal_lines_amount_nonzero",
        ),
        sa.CheckConstraint(
            "(debit IS NULL OR debit >= 0) AND (credit IS NULL OR credit >= 0)",
            name="ck_erp_journal_lines_amount_non_negative",
        ),
    )
    op.create_index(
        "ix_erp_journal_lines_tenant_entry", "erp_journal_lines", ["tenant_id", "entry_id"]
    )
    op.create_index(
        "ix_erp_journal_lines_tenant_account", "erp_journal_lines", ["tenant_id", "account_id"]
    )

    # --- erp_invoices ---
    op.create_table(
        "erp_invoices",
        *_tenant_scoped_pk(),
        sa.Column("invoice_number", sa.String(32), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", invoice_status, nullable=False, server_default=sa.text("'draft'")),
        sa.Column("total", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("tenant_id", "invoice_number", name="uq_erp_invoices_tenant_number"),
        sa.CheckConstraint("due_date >= invoice_date", name="ck_erp_invoices_due_date_range"),
        sa.CheckConstraint("total >= 0", name="ck_erp_invoices_total_non_negative"),
    )
    op.create_index("ix_erp_invoices_tenant_status", "erp_invoices", ["tenant_id", "status"])
    op.create_index("ix_erp_invoices_tenant_customer", "erp_invoices", ["tenant_id", "customer_id"])

    # --- erp_invoice_lines ---
    op.create_table(
        "erp_invoice_lines",
        *_tenant_scoped_pk(),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["erp_invoices.tenant_id", "erp_invoices.id"],
            name="fk_erp_invoice_lines_invoice",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["erp_chart_of_accounts.tenant_id", "erp_chart_of_accounts.id"],
            name="fk_erp_invoice_lines_account",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_erp_invoice_lines_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_erp_invoice_lines_unit_price_non_negative"),
        sa.CheckConstraint("amount >= 0", name="ck_erp_invoice_lines_amount_non_negative"),
        sa.CheckConstraint(
            "amount = quantity * unit_price", name="ck_erp_invoice_lines_amount_consistent"
        ),
    )
    op.create_index(
        "ix_erp_invoice_lines_tenant_invoice", "erp_invoice_lines", ["tenant_id", "invoice_id"]
    )

    # --- erp_payments ---
    op.create_table(
        "erp_payments",
        *_tenant_scoped_pk(),
        sa.Column("payment_number", sa.String(32), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", payment_status, nullable=False, server_default=sa.text("'applied'")),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(64), nullable=True),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["erp_invoices.tenant_id", "erp_invoices.id"],
            name="fk_erp_payments_invoice",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "payment_number", name="uq_erp_payments_tenant_number"),
        sa.UniqueConstraint("tenant_id", "source", "source_ref", name="uq_erp_payments_source_ref"),
        sa.CheckConstraint("amount > 0", name="ck_erp_payments_amount_positive"),
    )
    op.create_index("ix_erp_payments_tenant_invoice", "erp_payments", ["tenant_id", "invoice_id"])

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

    # Reverse dependency order.
    op.drop_table("erp_payments")
    op.drop_table("erp_invoice_lines")
    op.drop_table("erp_invoices")
    op.drop_table("erp_journal_lines")
    op.drop_table("erp_journal_entries")
    op.drop_table("erp_fiscal_periods")
    op.drop_table("erp_chart_of_accounts")

    op.execute("DROP SEQUENCE IF EXISTS seq_erp_payment_number")
    op.execute("DROP SEQUENCE IF EXISTS seq_erp_invoice_number")

    for enum_type in _ENUM_TYPES:
        op.execute(f"DROP TYPE IF EXISTS {enum_type}")
