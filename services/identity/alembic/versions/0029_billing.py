"""billing data model: trial/subscription columns + plan_tier canonicalization

Adds the columns needed for trials, subscriptions, and Stripe integration
to the shared ``tenants`` table (SKY-33 / BILLING-DATA-001).

New columns:

* ``tenants.trial_ends_at``            - nullable DateTime
* ``tenants.subscription_status``      - String(20), default 'none'
* ``tenants.stripe_customer_id``       - unique nullable String
* ``tenants.stripe_subscription_id``   - nullable String
* ``tenants.billing_email``            - nullable String

Also normalizes the ``plan_tier`` CHECK constraint to use canonical DB
values (``pro`` instead of ``professional``) and backfills existing rows
accordingly.  The frontend ``planId`` ``professional`` is mapped to
``pro`` at write time by the catalog layer (see ADR-009).

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- new billing columns ------------------------------------------------
    op.add_column(
        "tenants",
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "subscription_status",
            sa.String(20),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "stripe_customer_id",
            sa.String(),
            nullable=True,
            unique=True,
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("billing_email", sa.String(), nullable=True),
    )

    # --- plan_tier canonicalization: professional → pro ----------------------
    # Drop the old constraint FIRST (it only allows 'professional', not 'pro'),
    # then backfill, then lock in the new constraint.
    op.drop_constraint("ck_tenants_plan_tier", "tenants", type_="check")
    op.execute("UPDATE tenants SET plan_tier = 'pro' WHERE plan_tier = 'professional'")
    op.create_check_constraint(
        "ck_tenants_plan_tier",
        "tenants",
        "plan_tier IN ('free', 'starter', 'pro', 'business', 'enterprise')",
    )


def downgrade() -> None:
    # reverse canonicalization: pro → professional
    # Drop the new constraint first (it only allows 'pro', not 'professional'),
    # backfill, then restore the old constraint.
    op.drop_constraint("ck_tenants_plan_tier", "tenants", type_="check")
    op.execute("UPDATE tenants SET plan_tier = 'professional' WHERE plan_tier = 'pro'")
    op.create_check_constraint(
        "ck_tenants_plan_tier",
        "tenants",
        "plan_tier IN ('free', 'starter', 'professional', 'business', 'enterprise')",
    )

    op.drop_column("tenants", "billing_email")
    op.drop_column("tenants", "stripe_subscription_id")
    op.drop_column("tenants", "stripe_customer_id")
    op.drop_column("tenants", "subscription_status")
    op.drop_column("tenants", "trial_ends_at")
