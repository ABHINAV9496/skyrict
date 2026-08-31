"""Unit tests for the core -> ai-agent account-code suggestion client.

Uses httpx.MockTransport — no network. Covers the relayed upstream path,
Authorization + tenant-slug header hygiene, 2xx parsing, no-match -> None,
non-2xx -> AiServiceUnavailableError, and invalid JSON -> AiServiceUnavailableError.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from core.core.exceptions import AiServiceUnavailableError
from core.domain.entities import ChartOfAccount
from core.domain.value_objects import AccountType
from core.features.finance.ai_suggester import suggest_account_code_with_ai


def _accounts():
    return [
        ChartOfAccount(
            tenant_id=object(), code="1000", name="Cash", account_type=AccountType.ASSET
        ),  # type: ignore[arg-type]
        ChartOfAccount(
            tenant_id=object(), code="1500", name="Equipment", account_type=AccountType.ASSET
        ),  # type: ignore[arg-type]
    ]


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ai.test")


async def test_success_parses_suggestion() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/ai/finance/account-suggest"
        assert request.headers["authorization"] == "Bearer tok"
        assert request.headers["x-tenant-slug"] == "acme-inc"
        return httpx.Response(
            200,
            json={
                "suggested_code": "1500",
                "suggested_name": "Equipment",
                "confidence": 0.9,
                "reasoning": "Furniture is a fixed asset.",
            },
        )

    async with _client(handler) as client:
        result = await suggest_account_code_with_ai(
            client,
            authorization="Bearer tok",
            tenant_slug="acme-inc",
            description="buy furniture",
            accounts=_accounts(),
        )
    assert result is not None
    assert result.suggested_code == "1500"
    assert result.confidence == Decimal("0.9")
    assert result.reasoning == "Furniture is a fixed asset."


async def test_reasoning_defaults_empty_when_absent() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"suggested_code": "1500", "suggested_name": "Equipment", "confidence": 0.9}
        )

    async with _client(handler) as client:
        result = await suggest_account_code_with_ai(
            client, authorization=None, tenant_slug=None, description="x", accounts=_accounts()
        )
    assert result is not None
    assert result.reasoning == ""


async def test_no_match_returns_none() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"suggested_code": "", "suggested_name": "", "confidence": 0}
        )

    async with _client(handler) as client:
        result = await suggest_account_code_with_ai(
            client, authorization=None, tenant_slug=None, description="x", accounts=_accounts()
        )
    assert result is None


async def test_non_2xx_raises() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    async with _client(handler) as client:
        with pytest.raises(AiServiceUnavailableError):
            await suggest_account_code_with_ai(
                client, authorization=None, tenant_slug=None, description="x", accounts=_accounts()
            )


async def test_invalid_json_raises() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    async with _client(handler) as client:
        with pytest.raises(AiServiceUnavailableError):
            await suggest_account_code_with_ai(
                client, authorization=None, tenant_slug=None, description="x", accounts=_accounts()
            )
