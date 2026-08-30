"""Canonical agent state contract (AGT-001, spec §3.1).

Every graph registered in ``agent_registry`` works on the SAME
``AgentState`` TypedDict so the orchestration runtime can start, interrupt,
and resume any agent uniformly. The dictionary is intentionally
``total=False``: early stages in a run may not yet have filled later keys,
and LangGraph treats missing keys as untouched channels.

Identity keys (tenant_id/user_id/agent_name/session_id) are ALWAYS seeded by
the runtime from the verified request context — never parsed from the
user prompt (prompt-injection defense, inventory-AI spec §5.6).

``intent`` records the routing decision (lookup/aggregate/narrative/
clarify); ``module_context`` carries feature-specific routing data from the
service's intent classifier; ``retrieved_docs``/``memory_context`` come from
the RAG + episodic-memory layer; ``tool_results`` accumulates outputs of the
agent's approved tool calls; ``status`` transitions
``running -> paused -> complete | abstained``; ``errors`` accumulates
recoverable failures instead of failing the whole run at once.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

AgentIntent = Literal["lookup", "aggregate", "narrative", "clarify"]
AgentStatus = Literal["running", "paused", "complete", "abstained"]


class AgentState(TypedDict, total=False):
    # --- identity / routing (always seeded by the runtime) -----------------
    tenant_id: str
    user_id: str
    agent_name: str
    session_id: str

    # --- input --------------------------------------------------------------
    user_query: str
    intent: AgentIntent
    cleaned_query: str
    module_context: dict[str, Any]

    # --- context -------------------------------------------------------------
    retrieved_docs: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    messages: list[Any]
    memory_context: dict[str, Any] | None

    # --- generation -----------------------------------------------------------
    llm_response: str
    citations: list[dict[str, Any]]
    confidence: float

    # --- control ---------------------------------------------------------------
    max_iterations: int
    current_step: int
    status: AgentStatus
    errors: list[str]
