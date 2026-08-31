"""ai_semantic_memory — extracted facts from conversations (SKY-61 memory persistence).

Stores structured facts extracted from CRM chat exchanges (e.g. "User prefers
email over call", "Deal X was discussed on 2026-08-30"). Facts are extracted
by the LLM after each conversation turn and used to provide context in future
exchanges.

The table uses the repo-wide composite ``(tenant_id, id)`` primary key and
row-level security against ``public.current_tenant_id()`` (same pattern as
migration 0001). ``expires_at`` is indexed for efficient TTL cleanup; facts
expire after 90 days (matching episodic memory convention).

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "ai_semantic_memory",
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
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column(
            "category",
            sa.String(100),
            nullable=False,
            comment="preference | entity | context | instruction",
        ),
        sa.Column(
            "entity_type",
            sa.String(50),
            nullable=True,
            comment="lead | opportunity | customer | contact | null (general)",
        ),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default="0.8",
            comment="LLM-assigned confidence 0.0-1.0",
        ),
        sa.Column(
            "source",
            sa.String(50),
            nullable=False,
            server_default="'conversation'",
            comment="conversation | explicit | inferred",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now() + interval '90 days'"),
        ),
    )

    op.create_index(
        "idx_semantic_memory_tenant_user",
        "ai_semantic_memory",
        ["tenant_id", "user_id"],
    )
    op.create_index(
        "idx_semantic_memory_entity",
        "ai_semantic_memory",
        ["tenant_id", "entity_type", "entity_id"],
        postgresql_where=sa.text("entity_type IS NOT NULL AND entity_id IS NOT NULL"),
    )
    op.create_index(
        "idx_semantic_memory_expires",
        "ai_semantic_memory",
        ["expires_at"],
    )
    op.create_index(
        "idx_semantic_memory_category",
        "ai_semantic_memory",
        ["tenant_id", "user_id", "category"],
    )

    op.execute(
        """
        ALTER TABLE ai_semantic_memory ENABLE ROW LEVEL SECURITY;
        """
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation_ai_semantic_memory ON ai_semantic_memory
            USING (tenant_id = public.current_tenant_id())
            WITH CHECK (tenant_id = public.current_tenant_id());
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_ai_semantic_memory ON ai_semantic_memory")
    op.execute("ALTER TABLE ai_semantic_memory DISABLE ROW LEVEL SECURITY")
    op.drop_table("ai_semantic_memory")
