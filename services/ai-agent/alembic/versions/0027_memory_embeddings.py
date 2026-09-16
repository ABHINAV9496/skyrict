"""Memory embeddings - semantic recall over episodic + semantic rows (SKY-100).

Adds optional 768-dim pgvector embeddings to ``ai_episodic_memory`` and
``ai_semantic_memory`` so the CRM assistant can recall conversation memories
by semantic similarity (the configured embedding provider, default none)
instead of trigram-only lexical search.

Design notes:

- All three columns are NULLABLE: NULL means "this row has no embedding yet".
  Existing rows are NOT backfilled here - embeddings are written at store time
  going forward (fire-and-forget inside MemoryService.store_after_chat), so a
  deployment that never configures an embedding provider keeps NULL columns
  and today's trigram/recency recall behavior, byte for byte.
- The embedding index is PARTIAL (``WHERE embedding IS NOT NULL``): ivfflat
  cannot be built meaningfully over an all-NULL column, and the partial
  predicate lets the index come alive row-by-row as embeddings land. This
  mirrors the compacted_at partial-index precedent (migration for SKY-90).
- ``embedding_model``/``embedding_dims`` record which model produced each
  vector so future model/dimension upgrades know what must be re-embedded
  (same convention as migrations 0012/0013 for RAG/inventory snapshots).

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

_EMBEDDING_INDEXES = (
    ("idx_episodic_memory_embedding", "ai_episodic_memory"),
    ("idx_semantic_memory_embedding", "ai_semantic_memory"),
)


def upgrade() -> None:
    for table in ("ai_episodic_memory", "ai_semantic_memory"):
        op.add_column(table, sa.Column("embedding", Vector(768), nullable=True))
        op.add_column(
            table,
            sa.Column(
                "embedding_model",
                sa.String(100),
                nullable=True,
                comment="Embedding model that produced the vector; NULL means never embedded",
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "embedding_dims",
                sa.Integer(),
                nullable=True,
                comment="Dimension count of the embedding column; NULL means never embedded",
            ),
        )
    for index, table in _EMBEDDING_INDEXES:
        op.execute(
            f"CREATE INDEX {index} ON {table} "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100) "
            "WHERE embedding IS NOT NULL"
        )


def downgrade() -> None:
    for index, _table in _EMBEDDING_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {index}")
    for table in ("ai_semantic_memory", "ai_episodic_memory"):
        op.drop_column(table, "embedding_dims")
        op.drop_column(table, "embedding_model")
        op.drop_column(table, "embedding")
