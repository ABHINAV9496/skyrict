"""Audit event catalog consistency tests (Appendix B of the spec).

Guards the canonical vocabulary: exact string values, no duplicates, and
ALL_AI_AUDIT_EVENTS covering exactly the documented constants. The set is
Appendix B PLUS ai.anomaly.escalated (workflow §4.4 defines escalation;
the appendix omits its event - see the constant's docstring).
"""

from __future__ import annotations

from ai_agent.core import audit_events
from ai_agent.core.audit_events import (
    AI_ANOMALY_DETECTED,
    AI_ANOMALY_DISMISSED,
    AI_ANOMALY_ESCALATED,
    AI_ANOMALY_RESOLVED,
    AI_HR_COPILOT_EXCHANGE,
    AI_NARRATOR_GENERATED,
    AI_NARRATOR_REFRESHED,
    AI_QUERY_EXECUTED,
    AI_SUGGESTION_APPROVED,
    AI_SUGGESTION_CREATED,
    AI_SUGGESTION_REJECTED,
    ALL_AI_AUDIT_EVENTS,
)


class TestAppendixBVocabulary:
    def test_exact_constant_values(self) -> None:
        # docs/modules/skyrict-ai/inventory-ai-features.md, Appendix B.
        assert AI_QUERY_EXECUTED == "ai.query.executed"
        assert AI_SUGGESTION_CREATED == "ai.suggestion.created"
        assert AI_SUGGESTION_APPROVED == "ai.suggestion.approved"
        assert AI_SUGGESTION_REJECTED == "ai.suggestion.rejected"
        assert AI_ANOMALY_DETECTED == "ai.anomaly.detected"
        assert AI_ANOMALY_RESOLVED == "ai.anomaly.resolved"
        assert AI_ANOMALY_DISMISSED == "ai.anomaly.dismissed"
        # Documented spec-gap addition (see module docstring).
        assert AI_ANOMALY_ESCALATED == "ai.anomaly.escalated"
        # HR-AI-001 feature 5 (spec §9).
        assert AI_HR_COPILOT_EXCHANGE == "ai.hr.copilot.exchange"
        # SKY-63 cross-module narrator events.
        assert AI_NARRATOR_GENERATED == "ai.narrator.generated"
        assert AI_NARRATOR_REFRESHED == "ai.narrator.refreshed"

    def test_all_events_covers_exactly_the_documented_constants(self) -> None:
        expected = {
            audit_events.AI_QUERY_EXECUTED,
            audit_events.AI_SUGGESTION_CREATED,
            audit_events.AI_SUGGESTION_APPROVED,
            audit_events.AI_SUGGESTION_REJECTED,
            audit_events.AI_ANOMALY_DETECTED,
            audit_events.AI_ANOMALY_RESOLVED,
            audit_events.AI_ANOMALY_DISMISSED,
            audit_events.AI_ANOMALY_ESCALATED,
            audit_events.AI_HR_COPILOT_EXCHANGE,
            audit_events.AI_NARRATOR_GENERATED,
            audit_events.AI_NARRATOR_REFRESHED,
        }
        assert set(ALL_AI_AUDIT_EVENTS) == expected

    def test_vocabulary_is_ai_namespaced_and_lowercase(self) -> None:
        for event in ALL_AI_AUDIT_EVENTS:
            assert event.startswith("ai."), event
            assert event == event.lower(), event
