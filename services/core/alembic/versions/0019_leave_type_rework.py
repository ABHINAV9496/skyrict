"""Leave type rework: replace annual with policy-driven casual+sick.

One-time hard-reset migration:
  1. Delete all annual movements, balances, and requests
  2. Remove the ``annual`` leave type from ``erp_leave_types``
  3. Update ``sick`` to be accrual (is_accrual=True, accrual_days_per_year=8)
  4. Create ``erp_leave_policies`` table
  5. Seed one default policy row per tenant (casual=12, sick=8, effective_from=today)

Balances are NOT bulk-inserted here — the lazy accrual mechanism (service layer)
creates them on the first balance read per employee per year.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-26
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Step 1: Delete all annual data (movements, balances, requests) ---

    # Disable the append-only trigger so we can delete legacy annual rows
    op.execute(
        "ALTER TABLE public.erp_leave_movements DISABLE TRIGGER erp_leave_movements_append_only"
    )
    op.execute("DELETE FROM public.erp_leave_movements WHERE leave_type = 'annual'")
    # Re-enable the trigger for all future writes
    op.execute(
        "ALTER TABLE public.erp_leave_movements ENABLE TRIGGER erp_leave_movements_append_only"
    )

    op.execute("DELETE FROM public.erp_leave_balances WHERE leave_type = 'annual'")
    op.execute("DELETE FROM public.erp_leave_requests WHERE leave_type = 'annual'")

    # --- Step 2: Remove the ``annual`` leave type ---

    op.execute("DELETE FROM public.erp_leave_types WHERE code = 'annual'")

    # --- Step 3: Update sick to accrual (8 days/year) ---

    op.execute(
        "UPDATE public.erp_leave_types "
        "SET is_accrual = TRUE, accrual_days_per_year = 8 "
        "WHERE code = 'sick'"
    )

    # --- Step 4: Create erp_leave_policies table ---

    op.create_table(
        "erp_leave_policies",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("casual_days_per_year", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("sick_days_per_year", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("last_accrual_year", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", name="uq_erp_leave_policies_tenant"),
    )

    # --- Step 5: Seed default policy rows for existing tenants ---

    op.execute(
        "INSERT INTO public.erp_leave_policies "
        "(tenant_id, id, casual_days_per_year, sick_days_per_year, effective_from) "
        "SELECT t.id, gen_random_uuid(), 12, 8, CURRENT_DATE "
        "FROM public.tenants t "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM public.erp_leave_policies p WHERE p.tenant_id = t.id"
        ")"
    )


def downgrade() -> None:
    # --- Reverse step 5+4: Drop policy table ---
    op.drop_table("erp_leave_policies")

    # --- Reverse step 3: Restore sick to non-accrual ---
    op.execute(
        "UPDATE public.erp_leave_types "
        "SET is_accrual = FALSE, accrual_days_per_year = NULL "
        "WHERE code = 'sick'"
    )

    # --- Reverse step 2: Re-insert annual leave type ---
    op.execute(
        "INSERT INTO public.erp_leave_types "
        "(tenant_id, id, code, name, is_accrual, accrual_days_per_year) "
        "SELECT t.id, gen_random_uuid(), 'annual', 'Annual Leave', TRUE, 20 "
        "FROM public.tenants t "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM public.erp_leave_types lt "
        "  WHERE lt.tenant_id = t.id AND lt.code = 'annual'"
        ")"
    )

    # Note: annual movements/balances/requests are not restored from backup.
