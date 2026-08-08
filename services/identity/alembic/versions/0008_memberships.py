"""Memberships: user<->tenant relationship with a lifecycle status.

Adds the ``memberships`` table (invited/active/suspended), enables Row-Level
Security on it, and backfills one active membership per existing user so the
table is consistent from day one. ``user_id`` is NULL while INVITED — no
placeholder users; ``invited_email`` reserves the email within the tenant.
``users.tenant_id`` stays as-is for RLS simplicity; membership becomes the
single source of truth as the auth pipeline lands.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the memberships table with enum, backfill, and RLS."""
    membership_status = postgresql.ENUM("invited", "active", "suspended", name="membership_status")

    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("invited_email", sa.String(320), nullable=True),
        sa.Column(
            "role_id", sa.Uuid(), sa.ForeignKey("roles.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "status",
            membership_status,
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "invited_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_memberships_user_tenant"),
        sa.UniqueConstraint("tenant_id", "invited_email", name="uq_memberships_tenant_email"),
        sa.CheckConstraint(
            "user_id IS NOT NULL OR invited_email IS NOT NULL",
            name="ck_memberships_user_or_email",
        ),
    )
    op.create_index("ix_memberships_tenant_id", "memberships", ["tenant_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_role_id", "memberships", ["role_id"])

    # Backfill: every existing user is an active member of their tenant.
    op.execute(
        "INSERT INTO memberships (user_id, tenant_id, invited_email, status, joined_at) "
        "SELECT u.id, u.tenant_id, u.email, 'active', u.created_at FROM users u "
        "ON CONFLICT (user_id, tenant_id) DO NOTHING"
    )

    # Row-Level Security: tenant-scoped like the other identity tables.
    op.execute("ALTER TABLE public.memberships ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_memberships ON public.memberships "
        "USING (tenant_id = public.current_tenant_id()) "
        "WITH CHECK (tenant_id = public.current_tenant_id())"
    )


def downgrade() -> None:
    """Drop memberships (RLS policy first)."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation_memberships ON public.memberships")
    op.execute("ALTER TABLE public.memberships DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_memberships_role_id", table_name="memberships")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_index("ix_memberships_tenant_id", table_name="memberships")
    op.drop_table("memberships")

    op.execute("DROP TYPE IF EXISTS membership_status")
