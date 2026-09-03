"""finance: seed erp.finance.* permission keys; invoice source/source_ref.

FIN-BE-002. Builds on the 0004 finance schema:

- seeds the three ``erp.finance.{read,write,approve}`` permission keys into
  ``core_permissions`` (the runtime catalog that ``require_permission``
  resolves against - see core/core/permissions.py); the legacy ``erp.invoice.*``
  keys stay untouched so existing role grants remain portable;
- adds ``erp_invoices.source`` / ``erp_invoices.source_ref`` and
  ``UNIQUE (tenant_id, source, source_ref)`` = the idempotency lock for
  ``InvoicePort.create_from_order`` (source = 'sales_order', source_ref =
  order_id): a replayed CRM handoff can never create a second invoice. NULL
  source_ref stays distinct, so unlimited manual invoices are allowed (same
  Postgres semantics as journal entries and payments).

Revision ID: 0006
Revises: 0004
Create Date: 2026-08-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0004"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# ERP permission seed (must match core/core/permissions.py CATALOG)
# ---------------------------------------------------------------------------
FINANCE_PERMISSION_CATALOG: tuple[tuple[str, str], ...] = (
    ("erp.finance.read", "View chart of accounts, journal entries, invoices, and payments"),
    ("erp.finance.write", "Create and update journal entries, invoices, and payments"),
    ("erp.finance.approve", "Post journal entries and approve invoices"),
)


def upgrade() -> None:
    # --- Invoice provenance (idempotency for create-from-order) ---
    op.add_column(
        "erp_invoices",
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
    )
    op.add_column("erp_invoices", sa.Column("source_ref", sa.String(128), nullable=True))
    op.create_unique_constraint(
        "uq_erp_invoices_source_ref",
        "erp_invoices",
        ["tenant_id", "source", "source_ref"],
    )

    # --- Seed the finance permission keys ---
    permission_rows = ", ".join(
        f"('{key}', '{description}')" for key, description in FINANCE_PERMISSION_CATALOG
    )
    op.execute(
        # ``permission_rows`` is built solely from the compile-time literal
        # ``FINANCE_PERMISSION_CATALOG`` above - no user input, so this f-string
        # SQL is not an injection vector.
        "INSERT INTO core_permissions (key, description) VALUES "
        f"{permission_rows} ON CONFLICT (key) DO NOTHING"  # nosec B608
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM core_permissions WHERE key IN "
        "('erp.finance.read', 'erp.finance.write', 'erp.finance.approve')"
    )

    op.drop_constraint("uq_erp_invoices_source_ref", "erp_invoices", type_="unique")
    op.drop_column("erp_invoices", "source_ref")
    op.drop_column("erp_invoices", "source")
