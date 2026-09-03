"""mfa enforcement: encrypted totp secrets, backup codes, tenant policy flag

- Widen ``users.mfa_secret`` to VARCHAR(512) so TOTP secrets encrypted with
  Fernet (base64 tokens, ~120 chars) fit the column.
- Add ``users.mfa_backup_codes`` (TEXT[]) - ten Argon2id hashes; a consumed
  slot is set to NULL so the array keeps its position on regeneration.
- Add ``tenants.mfa_required_for_all_members`` - tenant-configurable MFA
  enforcement for all members (tenant owners are always forced).

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "mfa_secret",
        existing_type=sa.String(64),
        type_=sa.String(512),
        existing_nullable=True,
    )
    op.add_column(
        "users",
        sa.Column(
            "mfa_backup_codes",
            postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "mfa_required_for_all_members",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "mfa_secret",
        existing_type=sa.String(512),
        type_=sa.String(64),
        existing_nullable=True,
    )
    op.drop_column("tenants", "mfa_required_for_all_members")
    op.drop_column("users", "mfa_backup_codes")
