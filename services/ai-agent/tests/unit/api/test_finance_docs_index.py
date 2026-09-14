"""Unit tests for the /ai/rag/index-finance-doc endpoint (FIN-AI-004).

Core pushes every generated finance document here so the tenant's A12 Q&A
store can retrieve it. The endpoint composes the same chunk -> embed -> persist
pipeline as the ``ai-agent ingest`` runner; this test exercises the wire
contract with a stubbed session and fake embedding provider, so no DB/Redis
or app lifespan is required (same seam as ``test_supplier_risk.py``).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.core.embedding import EmbeddingResult
from ai_agent.main import create_app

if TYPE_CHECKING:
    import pytest

_TENANT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
_CALLER = {
    "user_id": uuid.UUID("11111111-1111-4111-8111-111111111111"),
    "tenant_id": _TENANT_ID,
    "token_payload": {"sub": "11111111-1111-4111-8111-111111111111"},
}


class _FakeEmbeddingProvider:
    model = "text-embedding-3-small"
    dims = 4

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        vectors = [[0.1 * i] * self.dims for i in range(len(texts))]
        return EmbeddingResult(vectors=vectors, model_used=self.model, dims=self.dims, latency_ms=5)


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    async def execute(self, _stmt: object, *args: object, **kwargs: object) -> None:
        return None

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def close(self) -> None:
        pass


def _client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, _FakeSession]:
    monkeypatch.setattr("ai_agent.api.middleware.is_tenant_required_path", lambda _path: False)
    monkeypatch.setattr(
        "ai_agent.api.v1.routers.finance_docs.build_embedding_provider",
        lambda _settings: _FakeEmbeddingProvider(),
    )
    app = create_app()
    session = _FakeSession()
    app.dependency_overrides[get_current_user] = lambda: _CALLER
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app, raise_server_exceptions=True), session


def test_index_finance_doc_stores_document_for_caller_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session = _client(monkeypatch)
    text = "Revenue - Sales: 1,200.50\n" * 60

    response = client.post(
        "/api/v1/ai/rag/index-finance-doc",
        json={
            "source_ref": "finance-doc/9e1f5e84/rev1",
            "text": text,
            "page_title": "Profit & Loss",
        },
        headers={"authorization": "Bearer t"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_ref"] == "finance-doc/9e1f5e84/rev1"
    assert body["module"] == "finance-docs"
    assert body["parents"] >= 1
    assert body["children"] >= 1
    assert body["tokens_embedded"] > 0
    assert body["model_used"] == "text-embedding-3-small"
    assert len(session.added) > 0


def test_index_finance_doc_rejects_too_short_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _session = _client(monkeypatch)

    response = client.post(
        "/api/v1/ai/rag/index-finance-doc",
        json={"source_ref": "finance-doc/x", "text": "short"},
        headers={"authorization": "Bearer t"},
    )

    assert response.status_code == 422
