"""ai_conversations — durable conversation storage for the Agents shell (SKY-60).

Replaces the in-memory mock store with PostgreSQL-backed persistence so
conversations survive server restarts.  Two tables:

  * ``ai_conversations`` — one row per chat session (title, pin state, owner).
  * ``ai_conversation_messages`` — ordered message log per conversation.

Both use the repo-wide composite ``(tenant_id, id)`` primary key and
row-level security against ``public.current_tenant_id()`` (same pattern as
migration 0001).  Messages cascade-delete when a conversation is removed.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # ai_conversations
    # ------------------------------------------------------------------
    op.create_table(
        "ai_conversations",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Owner of the conversation",
        ),
        sa.Column(
            "title",
            sa.Text(),
            nullable=False,
            server_default="''",
            comment="Auto-derived from first user message",
        ),
        sa.Column(
            "pinned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        comment="Agent-shell conversation sessions",
    )

    op.create_index(
        "idx_conversations_tenant_user",
        "ai_conversations",
        ["tenant_id", "user_id"],
    )
    op.create_index(
        "idx_conversations_tenant_pinned_updated",
        "ai_conversations",
        ["tenant_id", "pinned", "updated_at"],
        postgresql_using="btree",
    )

    op.execute("ALTER TABLE ai_conversations ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_ai_conversations ON ai_conversations
            USING (tenant_id = public.current_tenant_id())
            WITH CHECK (tenant_id = public.current_tenant_id());
        """
    )

    # ------------------------------------------------------------------
    # ai_conversation_messages
    # ------------------------------------------------------------------
    op.create_table(
        "ai_conversation_messages",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(16),
            nullable=False,
            comment="'user' or 'agent'",
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "agent_name",
            sa.String(128),
            nullable=True,
            comment="Module agent that answered (e.g. inventory_monitor)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Parent PK is composite (tenant_id, id) — the FK must be composite
        # too; a single-column FK to id alone would fail DDL on Postgres.
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["ai_conversations.tenant_id", "ai_conversations.id"],
            ondelete="CASCADE",
        ),
        comment="Ordered message log per conversation",
    )

    op.create_index(
        "idx_conversation_messages_tenant_conv",
        "ai_conversation_messages",
        ["tenant_id", "conversation_id", "created_at"],
    )

    op.execute("ALTER TABLE ai_conversation_messages ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_ai_conversation_messages ON ai_conversation_messages
            USING (tenant_id = public.current_tenant_id())
            WITH CHECK (tenant_id = public.current_tenant_id());
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_ai_conversation_messages ON ai_conversation_messages"
    )
    op.execute("ALTER TABLE ai_conversation_messages DISABLE ROW LEVEL SECURITY")
    op.drop_table("ai_conversation_messages")

    op.execute("DROP POLICY IF EXISTS tenant_isolation_ai_conversations ON ai_conversations")
    op.execute("ALTER TABLE ai_conversations DISABLE ROW LEVEL SECURITY")
    op.drop_table("ai_conversations")
