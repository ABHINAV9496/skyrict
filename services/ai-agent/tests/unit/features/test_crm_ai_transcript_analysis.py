"""Unit tests for the CRM transcript analysis engine + service (SKY-91).

The engine tests prove the deterministic sanitization contract: the LLM's
output is parsed leniently and clamped/coerced by deterministic logic (score
0-100, sentiment enum, capped lists), and unusable output raises
``AiInvalidResponseError`` instead of being persisted. The service tests prove
persistence + audit wiring and the no-provider fail-closed behavior.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from ai_agent.core.exceptions import AiInvalidResponseError, AiUnavailableError
from ai_agent.core.providers.base import LlmCompletion
from ai_agent.features.crm.service import CrmAiService
from ai_agent.features.crm.transcript_analysis import (
    TranscriptAnalysis,
    analyze_transcript,
)

TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
ACTIVITY_ID = uuid.uuid4()

_VALID_ANALYSIS = {
    "summary": "The customer asked about pricing and the timeline.",
    "objection_score": 45,
    "objections": ["price is too high", "timeline is too aggressive"],
    "next_best_action": "send a revised quote with a phased rollout",
    "sentiment": "mixed",
    "key_topics": ["pricing", "timeline", "implementation"],
    "confidence": 0.7,
}


# ---- fakes ----------------------------------------------------------------


class FakeRouter:
    """Stand-in for LlmRouter: returns a canned completion or raises."""

    def __init__(self, *, text: str | None = None, error: Exception | None = None) -> None:
        self._text = text
        self._error = error
        self.requests: list[Any] = []

    async def complete(self, request: Any) -> LlmCompletion:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return LlmCompletion(text=self._text or "{}", model_used="fake", latency_ms=1)


class FakeGateway:
    """Structural stub for CrmGatewayPort - not used by transcript analysis."""

    async def get_lead(self, *, lead_id: uuid.UUID) -> Any:
        raise NotImplementedError

    async def get_opportunity(self, *, opportunity_id: uuid.UUID) -> Any:
        raise NotImplementedError

    async def list_activities_for_entity(
        self, *, entity_type: str, entity_id: uuid.UUID
    ) -> list[Any]:
        raise NotImplementedError

    async def list_leads(self, *, page: int = 1) -> list[Any]:
        raise NotImplementedError

    async def list_opportunities(self, *, page: int = 1) -> list[Any]:
        raise NotImplementedError

    async def query(
        self,
        *,
        resource: str,
        filters: dict[str, str] | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, object]:
        raise NotImplementedError


class FakeRepo:
    def __init__(self) -> None:
        self._saved: list[Any] = []

    async def save_transcript_analysis(self, row: Any) -> None:
        self._saved.append(row)


class FakeAudit:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def log(
        self,
        *,
        action: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        input_payload: dict[str, Any] | None = None,
        output_payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        self.calls.append(
            {
                "action": action,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "input_payload": input_payload,
                "output_payload": output_payload,
            }
        )
        return None


def _make_service(router: Any = None, repo: Any = None, audit: Any = None) -> CrmAiService:
    return CrmAiService(
        gateway=FakeGateway(),  # type: ignore[arg-type]
        repo=repo or FakeRepo(),  # type: ignore[arg-type]
        audit=audit or FakeAudit(),  # type: ignore[arg-type]
        llm_router=router,  # type: ignore[arg-type]
    )


# ---- engine: happy path -----------------------------------------------------


class TestAnalyzeTranscriptEngine:
    async def test_parses_valid_json_into_typed_result(self) -> None:
        router = FakeRouter(text=json.dumps(_VALID_ANALYSIS))
        result = await analyze_transcript(transcript="Hello, we need a quote.", llm=router)

        assert isinstance(result, TranscriptAnalysis)
        assert result.summary == _VALID_ANALYSIS["summary"]
        assert result.objection_score == 45
        assert result.objections == ["price is too high", "timeline is too aggressive"]
        assert result.next_best_action == "send a revised quote with a phased rollout"
        assert result.sentiment == "mixed"
        assert result.key_topics == ["pricing", "timeline", "implementation"]
        assert result.confidence == 0.7
        assert router.requests[0].json_mode is True

    async def test_strips_markdown_fence_before_parsing(self) -> None:
        fenced = f"```json\n{json.dumps(_VALID_ANALYSIS)}\n```"
        router = FakeRouter(text=fenced)
        result = await analyze_transcript(transcript="quote request", llm=router)
        assert result.summary == _VALID_ANALYSIS["summary"]

    async def test_clamps_objection_score(self) -> None:
        payload = {**_VALID_ANALYSIS, "objection_score": 180}
        router = FakeRouter(text=json.dumps(payload))
        result = await analyze_transcript(transcript="quote request", llm=router)
        assert result.objection_score == 100

    async def test_clamps_low_objection_score(self) -> None:
        payload = {**_VALID_ANALYSIS, "objection_score": -30}
        router = FakeRouter(text=json.dumps(payload))
        result = await analyze_transcript(transcript="quote request", llm=router)
        assert result.objection_score == 0

    async def test_coerces_unknown_sentiment_to_neutral(self) -> None:
        payload = {**_VALID_ANALYSIS, "sentiment": "ecstatic"}
        router = FakeRouter(text=json.dumps(payload))
        result = await analyze_transcript(transcript="quote request", llm=router)
        assert result.sentiment == "neutral"

    async def test_clamps_confidence(self) -> None:
        payload = {**_VALID_ANALYSIS, "confidence": 1.5}
        router = FakeRouter(text=json.dumps(payload))
        result = await analyze_transcript(transcript="quote request", llm=router)
        assert result.confidence == 1.0

    async def test_cleans_string_lists(self) -> None:
        payload = {
            **_VALID_ANALYSIS,
            "objections": ["price", "price", 42, "", "price"],
            "key_topics": [],
        }
        router = FakeRouter(text=json.dumps(payload))
        result = await analyze_transcript(transcript="quote request", llm=router)
        assert result.objections == ["price", "42"]
        assert result.key_topics == []

    async def test_missing_optional_fields_default(self) -> None:
        payload = {"summary": "They want a demo.", "objection_score": 10}
        router = FakeRouter(text=json.dumps(payload))
        result = await analyze_transcript(transcript="demo request", llm=router)
        assert result.objections == []
        assert result.next_best_action is None
        assert result.sentiment == "neutral"
        assert result.key_topics == []
        assert result.confidence == 0.0

    async def test_empty_transcript_raises_without_calling_llm(self) -> None:
        router = FakeRouter()
        with pytest.raises(AiInvalidResponseError, match="empty"):
            await analyze_transcript(transcript="   \n  ", llm=router)
        assert router.requests == []

    async def test_garbage_output_raises_not_persisted(self) -> None:
        router = FakeRouter(text="sorry, I cannot help with that")
        with pytest.raises(AiInvalidResponseError):
            await analyze_transcript(transcript="quote request", llm=router)

    async def test_json_list_output_raises(self) -> None:
        router = FakeRouter(text=json.dumps(["not", "an", "object"]))
        with pytest.raises(AiInvalidResponseError):
            await analyze_transcript(transcript="quote request", llm=router)

    async def test_missing_summary_raises(self) -> None:
        router = FakeRouter(text=json.dumps({"objection_score": 30}))
        with pytest.raises(AiInvalidResponseError, match="summary"):
            await analyze_transcript(transcript="quote request", llm=router)

    async def test_missing_score_raises(self) -> None:
        router = FakeRouter(text=json.dumps({"summary": "They want a demo."}))
        with pytest.raises(AiInvalidResponseError, match="objection score"):
            await analyze_transcript(transcript="quote request", llm=router)

    async def test_unavailable_llm_propagates(self) -> None:
        router = FakeRouter(error=AiUnavailableError("provider down"))
        with pytest.raises(AiUnavailableError):
            await analyze_transcript(transcript="quote request", llm=router)


# ---- service orchestration ---------------------------------------------------


class TestServiceAnalyzeTranscript:
    async def test_raises_when_no_provider_configured(self) -> None:
        service = _make_service(router=None)
        with pytest.raises(AiUnavailableError, match="No AI provider"):
            await service.analyze_transcript(
                tenant_id=TENANT_ID,
                activity_id=ACTIVITY_ID,
                user_id=USER_ID,
                transcript="Hello, we need a quote.",
            )

    async def test_persists_and_audits_sanitized_analysis(self) -> None:
        router = FakeRouter(text=json.dumps(_VALID_ANALYSIS))
        repo = FakeRepo()
        audit = FakeAudit()
        service = _make_service(router=router, repo=repo, audit=audit)

        result = await service.analyze_transcript(
            tenant_id=TENANT_ID,
            activity_id=ACTIVITY_ID,
            user_id=USER_ID,
            transcript="Hello, we need a quote.",
        )

        assert isinstance(result, TranscriptAnalysis)
        assert len(repo._saved) == 1
        row = repo._saved[0]
        assert row.tenant_id == TENANT_ID
        assert row.activity_id == ACTIVITY_ID
        assert row.summary == _VALID_ANALYSIS["summary"]
        assert row.objection_score == 45
        assert row.sentiment == "mixed"
        assert row.confidence == 0.7
        assert row.model_version == "v1"

        assert len(audit.calls) == 1
        assert audit.calls[0]["action"] == "ai.crm.transcript.analyzed"
        assert audit.calls[0]["tenant_id"] == TENANT_ID
        assert audit.calls[0]["user_id"] == USER_ID
        assert audit.calls[0]["input_payload"] == {"activity_id": str(ACTIVITY_ID)}
        assert audit.calls[0]["output_payload"]["objection_score"] == 45

    async def test_llm_failure_persists_nothing_and_audits_nothing(self) -> None:
        router = FakeRouter(error=AiInvalidResponseError("garbage"))
        repo = FakeRepo()
        audit = FakeAudit()
        service = _make_service(router=router, repo=repo, audit=audit)

        with pytest.raises(AiInvalidResponseError):
            await service.analyze_transcript(
                tenant_id=TENANT_ID,
                activity_id=ACTIVITY_ID,
                user_id=USER_ID,
                transcript="Hello, we need a quote.",
            )
        assert repo._saved == []
        assert audit.calls == []
