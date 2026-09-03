"""onboarding state: user dismiss + tenant completion timestamps

The onboarding wizard needs to track two lifecycle markers:

* ``users.onboarding_dismissed_at`` - set when a user dismisses the wizard.
* ``tenants.onboarding_completed_at`` - set when the organization finishes
  the wizard (idempotent: the repository only stamps it once).

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("onboarding_dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "onboarding_completed_at")
    op.drop_column("users", "onboarding_dismissed_at")
