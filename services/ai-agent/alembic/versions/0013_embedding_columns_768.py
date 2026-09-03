"""embedding columns 512 -> 768 (SKY-70 / SKY-58 providers on one schema).

All supported embedding providers emit 768-dim vectors:
- OpenAI ``text-embedding-3-small`` via Matryoshka ``dimensions: 768``
- Gemini ``gemini-embedding-2`` via ``output_dimensionality`` (OpenAI-compatible
  surface, free tier)
- Ollama ``nomic-embed-text`` natively (768-dim)

This widens ``ai_rag_chunks.embedding`` and ``ai_inv_item_embeddings.embedding``
from ``vector(512)`` to ``vector(768)`` so a provider switch is a one-variable
config change. The embedding ivfflat indexes must be dropped before the ALTER
and recreated afterwards (pgvector forbids an in-place dimension change on an
indexed column).

The two snapshot/RAG tables are regenerable (``inventory reindex`` / RAG
ingest), so any pre-existing 512-dim rows should be cleared before upgrading.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_EMBEDDING_INDEXES = (
    ("idx_rag_chunks_embedding", "ai_rag_chunks"),
    ("idx_ai_inv_item_embeddings_embedding", "ai_inv_item_embeddings"),
)

_EMBEDDING_COLUMNS = (
    ("ai_rag_chunks", "embedding"),
    ("ai_inv_item_embeddings", "embedding"),
)

_DIMS_COLUMNS = (
    ("ai_rag_chunks", "embedding_dims"),
    ("ai_inv_item_embeddings", "embedding_dims"),
)


def _drop_indexes() -> None:
    for index, _table in _EMBEDDING_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {index}")


def _create_indexes() -> None:
    for index, table in _EMBEDDING_INDEXES:
        op.execute(
            f"CREATE INDEX {index} ON {table} "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )


def _resize(dimensions: int) -> None:
    for table, column in _EMBEDDING_COLUMNS:
        op.alter_column(table, column, type_=Vector(dimensions), existing_nullable=False)


def _server_default(dimensions: str) -> None:
    for table, column in _DIMS_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Integer(),
            nullable=False,
            server_default=sa.text(dimensions),
        )


def upgrade() -> None:
    _drop_indexes()
    _resize(768)
    _create_indexes()
    _server_default("768")


def downgrade() -> None:
    # NOTE: only safe when no 768-dim rows exist - casting a 768-dim vector to
    # vector(512) raises a "different vector dimensions" error from pgvector.
    _drop_indexes()
    _resize(512)
    _create_indexes()
    _server_default("512")
