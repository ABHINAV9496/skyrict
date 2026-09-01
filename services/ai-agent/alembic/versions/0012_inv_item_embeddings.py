"""inv_item_embeddings - per-product semantic search snapshot (SKY-70).

One row per ``(tenant_id, product_id)`` with a 512-dimension pgvector
embedding of the product's *existing* catalog text (``"{sku} {name}
{category} {unit}"`` — concatenated, no glue tokens). Embedding whole-item
text keeps the snapshot independent of core's schema, at the cost that a
hit cannot be attributed to a single field; the search layer therefore
carries per-field ``matched_fields``/highlight only for EXACT (ILIKE) hits
and surfaces ``score`` + ``source="semantic"`` for vector hits (spec §2.3).

The table is a snapshot mirror of core-owned ``erp_products`` maintained by
``inventory.product.upserted``/``.removed`` events + post-commit HTTP sync
and the ``inventory reindex`` CLI — it is never written by any request path.
The composite ``(tenant_id, product_id)`` FK into ``erp_products`` mirrors
the SKY-68 cross-service idiom (migration 0006); RLS bounds every row to
the session tenant via ``current_tenant_id()``.

``embedding_model``/``embedding_dims`` record which model produced the vector
so future model/dimension upgrades know what must be re-embedded.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _enable_rls(table: str) -> None:
    """Enable RLS and the tenant-isolation policy (0001/0006 convention)."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON {table} "
        "USING (tenant_id = public.current_tenant_id()) "
        "WITH CHECK (tenant_id = public.current_tenant_id())"
    )


def upgrade() -> None:
    op.create_table(
        "ai_inv_item_embeddings",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("product_id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        # Column widths mirror core's erp_products (String(100) / String(32)).
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column(
            "embedding_dims",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("512"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["erp_products.tenant_id", "erp_products.id"],
            ondelete="CASCADE",
            name="fk_ai_inv_item_embeddings_product_tenant",
        ),
    )
    op.create_index(
        "idx_ai_inv_item_embeddings_embedding",
        "ai_inv_item_embeddings",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_with={"lists": "100"},
    )
    _enable_rls("ai_inv_item_embeddings")


def downgrade() -> None:
    op.execute("ALTER TABLE ai_inv_item_embeddings DISABLE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_ai_inv_item_embeddings ON ai_inv_item_embeddings"
    )
    op.drop_table("ai_inv_item_embeddings")
