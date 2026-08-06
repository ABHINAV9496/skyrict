"""Link invitations to their memberships.

Adds ``invitations.membership_id`` (FK -> memberships, SET NULL) so an
invitation owns the INVITED membership that reserves the invited email. Every
pending invitation is backfilled into an INVITED membership (role resolved by
name) and linked, keeping membership the canonical source of truth.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the invitations.membership_id link and backfill pending invites."""
    op.add_column("invitations", sa.Column("membership_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_invitations_membership_id",
        "invitations",
        "memberships",
        ["membership_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Backfill: materialize an INVITED membership for every pending invitation
    # (role resolved by name from the tenant's role table) and link it.
    op.execute(
        """
        INSERT INTO memberships
            (tenant_id, invited_email, status, role_id, invited_by_user_id, invited_at)
        SELECT i.tenant_id, i.email, 'invited', r.id, i.created_by_user_id, i.created_at
        FROM invitations i
        JOIN roles r ON r.tenant_id = i.tenant_id AND r.name = i.role_name
        WHERE i.used_at IS NULL
        ON CONFLICT (tenant_id, invited_email) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE invitations i
        SET membership_id = m.id
        FROM memberships m
        WHERE m.tenant_id = i.tenant_id
          AND m.invited_email = i.email
          AND i.used_at IS NULL
          AND i.membership_id IS NULL
        """
    )


def downgrade() -> None:
    """Drop the invitations.membership_id link (memberships stay)."""
    op.drop_constraint("fk_invitations_membership_id", "invitations", type_="foreignkey")
    op.drop_column("invitations", "membership_id")
