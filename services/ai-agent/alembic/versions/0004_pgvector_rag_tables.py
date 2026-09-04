"""pgvector extension + RAG tables (SKY-58 / AI-RAG-001).

Creates the vector-search foundation for the AI agent:

- ``pgvector`` extension (``CREATE EXTENSION IF NOT EXISTS vector``)
- ``ai_rag_parents`` - parent chunks (~2000 tokens, not embedded, returned to
  LLM for generation context)
- ``ai_rag_chunks`` - child chunks (~400 tokens, embedded with 512-dim vectors,
  searched via cosine similarity)
- ``ai_episodic_memory`` - query-response pairs with 90-day TTL (embeddings
  deferred to SKY-60)
- ``ai_query_cache`` - hot/cold query cache (Redis hot path + DB persistence)
- ``ai_eval_runs`` - RAGAS evaluation run results (nightly CI)

Tenant-scoped tables use the repo-wide composite ``(tenant_id, id)`` primary
key and row-level security against ``public.current_tenant_id()`` (same pattern
as migration 0001). The vector index uses ``ivfflat`` with ``lists=100``
suitable for corpora under 100k chunks; bump to ``lists=200`` above that
threshold.

Renumbered from 0002 to 0004 on 2026-08-29 after dev merged SKY-72
(0002_hr_copilot) and SKY-68 (0003_forecast_abc_inventory_monitor) while this
branch was in flight; both expected the next free id. Final ai-agent chain:
0001 (foundation) -> 0002 (hr copilot) -> 0003 (forecast/abc/monitor) ->
0004 (this RAG work) -> 0005 (query-cache unique fix).

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# Tenant-scoped tables get RLS; ai_eval_runs is global (cross-tenant metrics).
_TENANT_SCOPED_TABLES = (
    "ai_rag_parents",
    "ai_rag_chunks",
    "ai_episodic_memory",
    "ai_query_cache",
)


# ---------------------------------------------------------------------------
# Schema helpers (same idiom as migration 0001)
# ---------------------------------------------------------------------------
def _tenant_scoped_pk(fk: bool) -> list[Any]:
    """Composite (tenant_id, id) PK so no generated PK column leaks."""
    columns: list[Any] = [
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        )
        if fk
        else sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    ]
    return columns


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def _updated_at() -> sa.Column[Any]:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


# ---------------------------------------------------------------------------
# Row-level security helpers (idempotent)
# ---------------------------------------------------------------------------
def _create_rls_policy(table: str) -> None:
    """Enable RLS and create the tenant-isolation policy for a tenant table."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON public.{table} "
        "USING (tenant_id = public.current_tenant_id()) "
        "WITH CHECK (tenant_id = public.current_tenant_id())"
    )


def _drop_rls_policy(table: str) -> None:
    """Disable RLS and drop the tenant-isolation policy for a tenant table."""
    op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON public.{table}")


def _ensure_current_tenant_id() -> None:
    """Pins the current-tenant-id function that RLS policies reference."""
    op.execute(
        "CREATE OR REPLACE FUNCTION public.current_tenant_id() RETURNS uuid "
        "LANGUAGE sql STABLE AS $$ "
        "SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid $$"
    )


def upgrade() -> None:
    # --- pgvector extension ---------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- ai_rag_parents: parent chunks (~2000t, not embedded, for LLM) --------
    op.create_table(
        "ai_rag_parents",
        *_tenant_scoped_pk(fk=True),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("module", sa.String(100), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        _created_at(),
    )

    # --- ai_rag_chunks: child chunks (~400t, embedded, searched) --------------
    op.create_table(
        "ai_rag_chunks",
        *_tenant_scoped_pk(fk=True),
        sa.Column("parent_id", sa.Uuid(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        # pgvector vector column - dimensions match the embedding model config.
        # Using 512 for Matryoshka-reduced text-embedding-3-small (3x storage
        # savings vs 1536d with ~2% quality drop, well within noise for ERP).
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column("module", sa.String(100), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column("embedding_dims", sa.Integer(), nullable=False, server_default=sa.text("512")),
        _created_at(),
        # Parent PK is composite (tenant_id, id) - the FK must be composite
        # too; a single-column FK to id alone would fail DDL on Postgres.
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["ai_rag_parents.tenant_id", "ai_rag_parents.id"],
            ondelete="CASCADE",
        ),
    )

    # --- ai_episodic_memory: query-response pairs (90-day TTL, no embeddings) -
    op.create_table(
        "ai_episodic_memory",
        *_tenant_scoped_pk(fk=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("response_summary", sa.Text(), nullable=False),
        sa.Column("module", sa.String(100), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=True),
        sa.Column("tokens_output", sa.Integer(), nullable=True),
        _created_at(),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now() + interval '90 days'"),
        ),
    )

    # --- ai_query_cache: hot (Redis) + cold (DB) query cache -----------------
    op.create_table(
        "ai_query_cache",
        *_tenant_scoped_pk(fk=True),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        _created_at(),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now() + interval '1 hour'"),
        ),
        sa.UniqueConstraint("query_hash", name="uq_ai_query_cache_hash"),
    )

    # --- ai_eval_runs: RAGAS evaluation results (global, not tenant-scoped) --
    op.create_table(
        "ai_eval_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "run_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("faithfulness", sa.Numeric(5, 4), nullable=True),
        sa.Column("answer_relevancy", sa.Numeric(5, 4), nullable=True),
        sa.Column("context_precision", sa.Numeric(5, 4), nullable=True),
        sa.Column("context_recall", sa.Numeric(5, 4), nullable=True),
    )

    # --- Indexes -------------------------------------------------------------
    op.create_index(
        "idx_rag_chunks_embedding",
        "ai_rag_chunks",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_with={"lists": "100"},
    )
    op.create_index(
        "idx_rag_chunks_module",
        "ai_rag_chunks",
        ["tenant_id", "module"],
    )
    op.create_index(
        "idx_rag_chunks_source",
        "ai_rag_chunks",
        ["tenant_id", "source_ref"],
    )
    op.create_index(
        "idx_rag_parents_source",
        "ai_rag_parents",
        ["tenant_id", "source_ref"],
    )
    op.create_index(
        "idx_episodic_memory_tenant_created",
        "ai_episodic_memory",
        ["tenant_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_episodic_memory_expires",
        "ai_episodic_memory",
        ["expires_at"],
    )
    op.create_index(
        "idx_query_cache_tenant_hash",
        "ai_query_cache",
        ["tenant_id", "query_hash"],
    )
    op.create_index(
        "idx_query_cache_expires",
        "ai_query_cache",
        ["expires_at"],
    )
    op.create_index(
        "idx_eval_runs_run_at",
        "ai_eval_runs",
        [sa.text("run_at DESC")],
    )

    # --- Row-level security ---------------------------------------------------
    _ensure_current_tenant_id()
    for table in _TENANT_SCOPED_TABLES:
        _create_rls_policy(table)


def downgrade() -> None:
    # 1) drop RLS policies
    for table in _TENANT_SCOPED_TABLES:
        _drop_rls_policy(table)

    # 2) drop tables (indexes/constraints go with them)
    op.drop_table("ai_eval_runs")
    op.drop_table("ai_query_cache")
    op.drop_table("ai_episodic_memory")
    op.drop_table("ai_rag_chunks")
    op.drop_table("ai_rag_parents")
