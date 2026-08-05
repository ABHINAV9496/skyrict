from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users: phone fields ---
    op.add_column("users", sa.Column("phone_country", sa.String(4), nullable=True))
    op.add_column("users", sa.Column("phone_number", sa.String(24), nullable=True))

    # --- users: resolve cross-tenant duplicate emails (keep the newest) ---
    # Row-wise comparison keeps the row maximal in (created_at, id) and deletes
    # every older duplicate for the same email. Cascade rules handle dependents:
    # user_roles/sessions/invitations cascade, audit_logs actor FKs go NULL.
    op.execute(
        """
        DELETE FROM users AS u
        USING users AS keeper
        WHERE u.email = keeper.email
          AND (u.created_at, u.id) < (keeper.created_at, keeper.id)
        """
    )

    # --- users: global unique email ---
    op.create_index(
        "uq_users_email", "users", ["email"], unique=True, postgresql_where=sa.text("email IS NOT NULL")
    )

    # --- tenants: plan tiers, backfill legacy 'pro' ---
    op.execute("UPDATE tenants SET plan_tier = 'professional' WHERE plan_tier = 'pro'")
    op.drop_constraint("ck_tenants_plan_tier", "tenants", type_="check")
    op.create_check_constraint(
        "ck_tenants_plan_tier",
        "tenants",
        "plan_tier IN ('free', 'starter', 'professional', 'business', 'enterprise')",
    )

    # --- tenants: industry + billing address ---
    op.add_column("tenants", sa.Column("industry", sa.String(120), nullable=True))
    op.add_column(
        "tenants",
        sa.Column("billing_address", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    # --- tenants ---
    op.drop_column("tenants", "billing_address")
    op.drop_column("tenants", "industry")
    op.drop_constraint("ck_tenants_plan_tier", "tenants", type_="check")
    op.create_check_constraint(
        "ck_tenants_plan_tier",
        "tenants",
        "plan_tier IN ('free', 'starter', 'pro', 'enterprise')",
    )
    op.execute("UPDATE tenants SET plan_tier = 'pro' WHERE plan_tier = 'professional'")

    # --- users ---
    op.drop_index("uq_users_email", table_name="users")
    op.drop_column("users", "phone_number")
    op.drop_column("users", "phone_country")
