"""Unit tests for the finance AI-docs core->ai-agent relay serialization.

The relay must serialize the ORM-shaped snapshot (UUID/date/datetime/Decimal
values straight from ``posted_entries_snapshot``) before ``json.dumps``, or
every non-empty call 500s with ``TypeError: Object of type ... is not JSON
serializable``. Regression guard for the serialization default.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal

import httpx

from core.features.ai_docs import ai_client


def _capturing_client(captured: list[bytes]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.content)
        return httpx.Response(
            200,
            json={"categories": [], "total_input": 0.0, "total_output": 0.0, "model_used": ""},
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ai.test")


class TestRelaySerialization:
    async def test_tax_summary_payload_with_orm_shaped_entries_is_json_dumps_safe(self) -> None:
        captured: list[bytes] = []
        payload = {
            "period": {
                "id": str(uuid.uuid4()),
                "name": "2026-01",
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "is_closed": False,
            },
            "snapshot": {
                "entries": [
                    {
                        "id": uuid.uuid4(),
                        "entry_date": date(2026, 1, 15),
                        "posted_at": datetime(2026, 1, 16, 9, 30),
                        "memo": "Sale",
                        "source": "manual",
                        "source_ref": None,
                        "amount": Decimal("1200.50"),
                        "lines": [{"code": "1000", "debit": Decimal("1200.50"), "credit": None}],
                    }
                ]
            },
        }

        result = await ai_client.generate_tax_summary_with_ai(
            _capturing_client(captured),
            authorization="Bearer test-token",
            tenant_slug="acme-inc",
            period=payload["period"],
            snapshot=payload["snapshot"],
        )

        assert result is None  # upstream said no categories -> abstention
        assert len(captured) == 1
        body = json.loads(captured[0].decode("utf-8"))
        entry = body["snapshot"]["entries"][0]
        assert entry["id"] == str(payload["snapshot"]["entries"][0]["id"])
        assert entry["entry_date"] == "2026-01-15"
        assert entry["amount"] == "1200.50"
        uuid.UUID(entry["id"])


def _request_capturing_client(captured: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "source_ref": body["source_ref"],
                "module": "finance-docs",
                "parents": 1,
                "children": 2,
                "tokens_embedded": 5,
                "model_used": "test-model",
            },
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ai.test")


class TestIndexRelay:
    async def test_index_finance_doc_posts_rendered_text_to_upstream(self) -> None:
        captured: list[httpx.Request] = []
        ok = await ai_client.index_finance_doc_in_rag(
            _request_capturing_client(captured),
            authorization="Bearer test-token",
            tenant_slug="acme-inc",
            source_ref="finance-doc/9e1f5e84/rev1",
            text="# Profit & Loss\n\nPeriod: Q3 2026",
            page_title="Profit & Loss",
        )

        assert ok is True
        assert len(captured) == 1
        assert str(captured[0].url).endswith("/api/v1/ai/rag/index-finance-doc")
        body = json.loads(captured[0].content.decode("utf-8"))
        assert body["source_ref"] == "finance-doc/9e1f5e84/rev1"
        assert body["page_title"] == "Profit & Loss"
        assert "Period: Q3 2026" in body["text"]

    async def test_index_finance_doc_returns_false_on_upstream_refusal(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(400, json={"detail": "refused"})

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://ai.test"
        )
        ok = await ai_client.index_finance_doc_in_rag(
            client,
            authorization="Bearer test-token",
            tenant_slug="acme-inc",
            source_ref="tax-summary/abc",
            text="a body long enough to index",
        )

        assert ok is False
        assert len(captured) == 1
