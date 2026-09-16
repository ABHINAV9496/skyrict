"""Backfill the default chart of accounts for pre-existing tenants (SKY-94/SKY-96).

Before this migration, only the demo tenant had a chart of accounts: every
other tenant hit ``NotFoundError`` during sales order fulfilment because
finance/service.py cannot resolve the COGS or revenue account code by code
(``post_cogs_for_order`` / ``create_from_order``).

This is the additive, idempotent backfill:

  - cross-joins the 9 mandatory account codes with every tenant;
  - inserts only the codes a tenant does not already have
    (``ON CONFLICT (tenant_id, code) DO NOTHING``) so custom per-tenant
    charts and any manually-created account with the same code are never
    overwritten;
  - ``account_type`` is cast to the native ``erp_account_type`` enum;
  - ``id`` comes from ``gen_random_uuid()`` (there is no server default).

New tenants are provisioned by ``core.seed.seed_tenant_finance_defaults``
instead; this migration only reconciles tenants that already exist.  The
catalog here is a frozen snapshot of that seed catalog - keep both in sync
when adding mandatory accounts.

Downgrade is a deliberate no-op: accounts backfilled by this migration are
real tenant data by the time it could roll back, and deleting rows here could
strand journal/invoice history that references them.

Revision ID: 0062
Revises: 0061
Create Date: 2026-09-16
"""

from alembic import op
from sqlalchemy import text

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None

# Frozen snapshot of core.seed.DEFAULT_CHART_ACCOUNTS at the time of writing.
# (code, name, account_type)
_DEFAULT_ACCOUNTS = (
    ("1100", "Accounts Receivable", "asset"),
    ("1200", "Cash", "asset"),
    ("1300", "Inventory Asset", "asset"),
    ("2010", "Accrued Salaries", "liability"),
    ("2020", "Tax Payable", "liability"),
    ("2110", "Accounts Payable", "liability"),
    ("4000", "Sales Revenue", "revenue"),
    ("5000", "Cost of Goods Sold", "expense"),
    ("5010", "Salaries Expense", "expense"),
)

_VALUES = ", ".join(f"('{code}', '{name}', '{kind}')" for code, name, kind in _DEFAULT_ACCOUNTS)


def upgrade() -> None:
    op.execute(
        text(
            "INSERT INTO erp_chart_of_accounts "
            "(tenant_id, id, code, name, account_type, is_active) "
            f"SELECT t.id, gen_random_uuid(), v.code, v.name, "
            f"v.account_type::erp_account_type, TRUE "
            f"FROM tenants t "
            f"CROSS JOIN (VALUES {_VALUES}) AS v(code, name, account_type) "
            f"ON CONFLICT (tenant_id, code) DO NOTHING"
        )
    )


def downgrade() -> None:
    # Deliberate no-op: additive, data-preserving backfill (see module docstring).
    pass
