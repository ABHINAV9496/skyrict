"""Unit tests for the canonical AgentState contract (AGT-001, §3.1).

The TypedDict is the single state schema every registered graph shares, so
its contract is pinned here: every key the runtime seeds and every optional
late-stage key must exist, and nothing may be required at type level that
early stages cannot yet provide.
"""

from __future__ import annotations

import typing

from ai_agent.graphs.state import AgentIntent, AgentState, AgentStatus


class TestAgentStateContract:
    def test_runtime_seeded_identity_keys_present(self) -> None:
        state: AgentState = {
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "agent_name": "restock_advisor",
            "session_id": "session-1",
        }
        assert state["tenant_id"] == "tenant-1"
        assert state["user_id"] == "user-1"
        assert state["agent_name"] == "restock_advisor"
        assert state["session_id"] == "session-1"

    def test_full_state_shape_is_assignable(self) -> None:
        state: AgentState = {
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "agent_name": "restock_advisor",
            "session_id": "session-1",
            "user_query": "reorder the laptop chargers",
            "intent": "aggregate",
            "cleaned_query": "reorder laptop chargers",
            "module_context": {"product_ids": ["p1"]},
            "retrieved_docs": [{"id": "d1"}],
            "tool_results": [{"tool": "query_stock", "rows": 3}],
            "messages": [],
            "memory_context": None,
            "llm_response": "order 25 units",
            "citations": [{"doc_id": "d1"}],
            "confidence": 0.9,
            "max_iterations": 5,
            "current_step": 2,
            "status": "paused",
            "errors": [],
        }
        assert state["intent"] == "aggregate"
        assert state["status"] == "paused"

    def test_partial_state_is_allowed(self) -> None:
        # total=False means an early node may return only the keys it owns.
        state: AgentState = {"user_query": "hi"}
        assert state == {"user_query": "hi"}

    def test_status_and_intent_literals(self) -> None:
        assert typing.get_args(AgentStatus) == ("running", "paused", "complete", "abstained")
        assert typing.get_args(AgentIntent) == ("lookup", "aggregate", "narrative", "clarify")
