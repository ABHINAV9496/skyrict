"""sessions refresh-token reuse grace window

Adds the two nullable columns that back the benign-race tolerance in the
refresh path (SKY-105 follow-up): a just-rotated-out refresh token is
re-accepted within ``credentials.previous_token_valid_until`` instead of
arming family chain-kill, which revokes the user's whole session family.

New columns (all nullable, so existing rows need no backfill):

* ``sessions.previous_refresh_token_hash`` - String(128)
* ``sessions.previous_token_valid_until``   - nullable DateTime

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("previous_refresh_token_hash", sa.String(128), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "previous_token_valid_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "previous_token_valid_until")
    op.drop_column("sessions", "previous_refresh_token_hash")
