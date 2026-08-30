"""Unit tests for the product-embedding repository (SKY-70).

The repository is pure orchestration over the SQLAlchemy session, so a fake
session records the emitted statements instead of hitting Postgres: upserts
must be idempotent (``ON CONFLICT``), deletes must be tenant+product scoped,
and semantic search must filter the tenant and order by cosine distance.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy
from sqlalchemy.dialects.postgresql import dialect as pg_dialect

from ai_agent.db.inventory_embedding_repository import InventoryEmbeddingRepository
from ai_agent.models.ai_inv_item_embedding import AiInvItemEmbeddingModel

TENANT_ID = uuid.uuid4()
PRODUCT_ID = uuid.uuid4()


class _FakeSession:
    """Records executed statements — no real SQL."""

    def __init__(self) -> None:
        self.executed: list[object] = []

    async def execute(self, statement: object) -> None:
        self.executed.append(statement)
        return None


class _Cursor:
    """Minimal result cursor for the retrieval-path queries."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows

    def scalars(self) -> _Cursor:
        return self


class _RetrievalFakeSession:
    """Session that returns queued cursors from ``execute``."""

    def __init__(self, cursors: list[_Cursor]) -> None:
        self._cursors = list(cursors)
        self.executed: list[object] = []

    async def execute(self, statement: object) -> _Cursor:
        self.executed.append(statement)
        return self._cursors.pop(0) if self._cursors else _Cursor([])


def _compile(statement: object) -> str:
    return str(statement.compile(dialect=pg_dialect(), compile_kwargs={"literal_binds": True}))


class TestUpsert:
    async def test_inserts_with_on_conflict_update_and_full_snapshot(self) -> None:
        session = _FakeSession()
        repo = InventoryEmbeddingRepository(session)  # type: ignore[arg-type]
        await repo.upsert(
            tenant_id=TENANT_ID,
            product_id=PRODUCT_ID,
            sku="LAP-65W",
            name="Laptop Charger",
            category="Accessories",
            unit="unit",
            embedding=[0.1, 0.2, 0.3, 0.4],
            embedding_model="text-embedding-3-small",
            dims=4,
        )

        assert len(session.executed) == 1
        statement = session.executed[0]
        assert getattr(statement, "table", None) is not None
        compiled = _compile(statement)
        assert "INSERT INTO ai_inv_item_embeddings" in compiled
        assert "ON CONFLICT" in compiled
        assert "LAP-65W" in compiled
        assert "text-embedding-3-small" in compiled

    async def test_nullable_fields_round_trip(self) -> None:
        session = _FakeSession()
        repo = InventoryEmbeddingRepository(session)  # type: ignore[arg-type]
        await repo.upsert(
            tenant_id=TENANT_ID,
            product_id=PRODUCT_ID,
            sku="NOCAT-1",
            name="No Category Product",
            category=None,
            unit=None,
            embedding=[0.0] * 4,
            embedding_model="m",
            dims=4,
        )
        compiled = _compile(session.executed[0])
        assert "NOCAT-1" in compiled

    async def test_dimension_mismatch_raises(self) -> None:
        session = _FakeSession()
        repo = InventoryEmbeddingRepository(session)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="dimension"):
            await repo.upsert(
                tenant_id=TENANT_ID,
                product_id=PRODUCT_ID,
                sku="S",
                name="x",
                category=None,
                unit=None,
                embedding=[0.1],  # dim 1 != 512
                embedding_model="m",
                dims=512,
            )


class TestDelete:
    async def test_delete_scoped_to_tenant_and_product(self) -> None:
        session = _FakeSession()
        repo = InventoryEmbeddingRepository(session)  # type: ignore[arg-type]
        await repo.delete(tenant_id=TENANT_ID, product_id=PRODUCT_ID)

        assert len(session.executed) == 1
        statement = session.executed[0]
        assert isinstance(statement, sqlalchemy.Delete)
        compiled = str(statement.compile(dialect=pg_dialect()))
        assert "DELETE FROM ai_inv_item_embeddings" in compiled
        assert "ai_inv_item_embeddings.tenant_id" in compiled
        assert "ai_inv_item_embeddings.product_id" in compiled

    async def test_delete_all_scoped_to_tenant(self) -> None:
        session = _FakeSession()
        repo = InventoryEmbeddingRepository(session)  # type: ignore[arg-type]
        await repo.delete_all(tenant_id=TENANT_ID)

        compiled = str(session.executed[0].compile(dialect=pg_dialect()))
        assert "DELETE FROM ai_inv_item_embeddings" in compiled
        assert "ai_inv_item_embeddings.tenant_id" in compiled


class TestExactSearch:
    async def test_empty_terms_returns_without_query(self) -> None:
        session = _FakeSession()
        repo = InventoryEmbeddingRepository(session)  # type: ignore[arg-type]
        assert await repo.exact_search(tenant_id=TENANT_ID, terms=[], limit=10) == []
        assert session.executed == []

    async def test_any_term_any_field_tenant_scoped_with_limit(self) -> None:
        session = _RetrievalFakeSession([_Cursor([])])
        repo = InventoryEmbeddingRepository(session)  # type: ignore[arg-type]
        await repo.exact_search(tenant_id=TENANT_ID, terms=["rack", "charger"], limit=5)

        compiled = str(session.executed[0].compile(dialect=pg_dialect()))
        assert "ai_inv_item_embeddings.tenant_id" in compiled
        assert "lower(coalesce(" in compiled.lower()
        assert "LIKE" in compiled.upper()
        assert "LIMIT" in compiled
        for column in ("sku", "name", "category", "unit"):
            assert column in compiled

    async def test_returns_parsed_hits(self) -> None:
        model = AiInvItemEmbeddingModel(
            tenant_id=TENANT_ID,
            product_id=PRODUCT_ID,
            sku="LAP-65W",
            name="Laptop Charger",
            category="Accessories",
            unit="unit",
        )
        session = _RetrievalFakeSession([_Cursor([model])])
        repo = InventoryEmbeddingRepository(session)  # type: ignore[arg-type]

        hits = await repo.exact_search(tenant_id=TENANT_ID, terms=["charger"], limit=10)

        assert len(hits) == 1
        assert hits[0].product_id == PRODUCT_ID
        assert hits[0].sku == "LAP-65W"
        assert hits[0].category == "Accessories"


class TestSemanticSearch:
    async def test_filters_tenant_and_orders_by_cosine_distance_with_limit(self) -> None:
        model = AiInvItemEmbeddingModel(
            tenant_id=TENANT_ID,
            product_id=PRODUCT_ID,
            sku="LAP-65W",
            name="Laptop Charger",
        )
        session = _RetrievalFakeSession([_Cursor([(model, 0.15)])])
        repo = InventoryEmbeddingRepository(session)  # type: ignore[arg-type]

        hits = await repo.semantic_search(tenant_id=TENANT_ID, query_vector=[0.1, 0.2], top_k=20)

        assert len(hits) == 1
        assert hits[0].product_id == PRODUCT_ID
        assert hits[0].sku == "LAP-65W"
        assert hits[0].name == "Laptop Charger"
        assert hits[0].cosine_distance == pytest.approx(0.15)
        compiled = str(session.executed[0].compile(dialect=pg_dialect()))
        assert "ai_inv_item_embeddings.tenant_id" in compiled
        assert "ai_inv_item_embeddings.embedding <=>" in compiled
        assert "LIMIT" in compiled
