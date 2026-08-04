"""Add invitations:send permission to catalog

Adds the invitations:send permission key to the permissions table so it can be
assigned to custom roles. This permission controls access to the invitation
creation endpoint.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-04
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Insert the new permission into the catalog
    op.execute(
        "INSERT INTO permissions (key, description) VALUES ('invitations:send', 'Invite users to the tenant') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    # Remove the permission from the catalog
    op.execute("DELETE FROM permissions WHERE key = 'invitations:send'")
