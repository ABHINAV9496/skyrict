"""Unit tests for the core -> ai-agent attrition scoring client (Commit 3).

Uses ``httpx.MockTransport`` (no network, no FastAPI client) to check the
request body, header hygiene, response parsing, abstention-drop and failure
mapping.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from core.core.exceptions import AiServiceUnavailableError
from core.features.ai_hr.attrition_client import score_features
from core.features.ai_hr.attrition_repository import FeatureVector

pytestmark = pytest.mark.unit

E1 = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
E2 = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
D1 = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ai.test")


def _features() -> list[FeatureVector]:
    return [
        FeatureVector(E1, D1, 1.0, 0.8, 18.0, 1.0),
        FeatureVector(E2, None, 8.0, 1.1, 2.0, 12.0),
    ]


def _score_response() -> dict:
    return {
        "model_version": "v1-gbc-2026-08",
        "model_source": "bundled",
        "considered": 2,
        "abstained": 1,
        "scored": [
            {
                "employee_ref": str(E1),
                "score": 0.91,
                "risk_band": "high",
                "confidence": 0.98,
                "factors": [
                    {"feature": "promotion gap", "contribution": 0.12, "direction": "increases"}
                ],
            }
        ],
    }


async def test_posts_anonymous_features_and_parses_scored_employees() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["slug"] = request.headers.get("x-tenant-slug")
        # Only anonymous numbers + opaque refs - never PII.
        seen["keys"] = sorted(body["employees"][0])
        return httpx.Response(200, json=_score_response())

    result = await score_features(
        _client(handler),
        authorization="Bearer tok",
        tenant_slug="acme",
        features=_features(),
    )

    assert seen["path"] == "/api/v1/ai/hr/attrition/score"
    assert seen["auth"] == "Bearer tok"
    assert seen["slug"] == "acme"
    # No name/email/number keys in the payload.
    assert seen["keys"] == [
        "activity_count",
        "compa_ratio",
        "employee_ref",
        "promotion_gap_months",
        "tenure_years",
    ]
    # Abstained E2 is dropped; only E1 returns, with dept carried through.
    assert [r.employee_id for r in result] == [E1]
    assert result[0].department_id == D1
    assert result[0].risk_band == "high"
    assert result[0].model_version == "v1-gbc-2026-08"
    assert result[0].factors == [
        {"feature": "promotion gap", "contribution": 0.12, "direction": "increases"}
    ]


async def test_non_2xx_upstream_raises_service_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"type": "about:blank/ai-unavailable"})

    with pytest.raises(AiServiceUnavailableError):
        await score_features(
            _client(handler),
            authorization="Bearer tok",
            tenant_slug="acme",
            features=_features(),
        )
