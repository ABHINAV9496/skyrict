from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invitations", sa.Column("role_name", sa.String(64), nullable=True))
    op.execute("UPDATE invitations SET role_name = 'standard_user' WHERE role_name IS NULL")
    op.alter_column(
        "invitations",
        "role_name",
        existing_type=sa.String(64),
        nullable=False,
        server_default="standard_user",
    )

    op.add_column("invitations", sa.Column("token_hash", sa.String(64), nullable=True))
    op.execute(
        "UPDATE invitations SET token_hash = encode(sha256(token::bytea), 'hex') "
        "WHERE token_hash IS NULL"
    )
    op.drop_column("invitations", "token")
    op.alter_column(
        "invitations",
        "token_hash",
        existing_type=sa.String(64),
        nullable=False,
    )
    op.create_index("uq_invitations_token_hash", "invitations", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_invitations_token_hash", table_name="invitations")
    op.add_column("invitations", sa.Column("token", sa.String(128), nullable=True))
    op.drop_column("invitations", "token_hash")
    op.drop_column("invitations", "role_name")
