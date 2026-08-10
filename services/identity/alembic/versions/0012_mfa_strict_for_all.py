"""mfa strict for all: drop tenant-level mfa policy toggle

MFA is now mandatory for every account in every tenant, so the
``tenants.mfa_required_for_all_members`` flag has no effect. Drop it.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("tenants", "mfa_required_for_all_members")


def downgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "mfa_required_for_all_members",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
