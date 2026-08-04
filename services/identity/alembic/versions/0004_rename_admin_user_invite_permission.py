"""Replace admin.user.invite with invitations:send in role permission arrays

The legacy ``admin.user.invite`` key (dot-separated) was superseded by the
catalogued ``invitations:send`` key (colon-separated). Existing seeded roles
still reference the old key, so update any role arrays in the database to keep
system roles consistent with the platform-fixed catalog.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-04
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE roles SET permissions = array_replace(permissions, "
        "'admin.user.invite', 'invitations:send') "
        "WHERE 'admin.user.invite' = ANY(permissions)"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE roles SET permissions = array_replace(permissions, "
        "'invitations:send', 'admin.user.invite') "
        "WHERE 'invitations:send' = ANY(permissions)"
    )
