"""Restock Advisor — the SKY-59 HITL demo agent (module contract).

Module contract (see runtime.py): the module exposes ``build_graph(deps)``
returning an UNCOMPILED ``StateGraph``; the runtime compiles it with the
tenant-scoped checkpointer and drives invoke/resume. The registry seed
(0008) wires ``restock_advisor -> ai_agent.features.restock_agent.graph``
with allowlist ``["query_stock", "draft_suggestion", "apply_suggestion"]``.

Flow::

    query_stock (read; caller must hold erp.inventory.read)
      -> draft_suggestion (deterministic formula; an LLM draft drops in here)
      -> apply_suggestion (interrupt; erased at resume with {"decision": ...})

The run input carries the stock snapshot (self-contained demo — the ERP read
is simulated), but the READ GATE is real: ``query_stock`` refuses to run
without ``erp.inventory.read`` on the caller's ToolContext. The WRITE gate is
the runtime's: an approved interrupt requires ``erp.inventory.ai.approve`` at
ledge-open AND resume, then the approved branch persists an ``ai_suggestions``
row via the SKY-68 repo + audits ``ai.suggestion.created``; denied is a clean
no-op.

Consistency: the ledger decision commits FIRST (runtime), then this node
runs once at resume. Write errors are captured into state — never raised —
so a mid-apply failure cannot roll back into an inconsistent checkpoint.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from functools import partial
from typing import TYPE_CHECKING, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ai_agent.core.audit_events import AI_SUGGESTION_CREATED
from ai_agent.core.audit_service import AuditService
from ai_agent.db.audit_repository import AiAuditLogRepository
from ai_agent.db.suggestion_repository import SuggestionRepository
from ai_agent.graphs.security import PERM_INVENTORY_AI_APPROVE, PERM_INVENTORY_READ
from skyrict_common.exceptions import PermissionDeniedError

if TYPE_CHECKING:
    from ai_agent.graphs.runtime import AgentDeps

__all__ = ["build_graph"]


class RestockState(TypedDict, total=False):
    """Run-local state for the demo; no identity or permissions live here."""

    product_id: str
    warehouse_id: str
    current_stock: int
    reorder_point: int
    suggested_qty: int
    reason: str
    applied: bool
    outcome: str


def build_graph(deps: AgentDeps) -> StateGraph[RestockState]:
    """Build the demo's uncompiled state graph (runtime compiles it).

    Nodes are bound to ``deps`` here via ``functools.partial`` — LangGraph
    does not inject extra kwargs into plain-function nodes (verified against
    the installed 0.6.x runtime), so the graph hands each node exactly the
    state it declares.
    """
    builder = StateGraph(RestockState)
    builder.add_node("query_stock", partial(_query_stock_node, deps=deps))
    builder.add_node("draft_suggestion", _draft_suggestion_node)
    builder.add_node("apply_suggestion", partial(_apply_suggestion_node, deps=deps))
    builder.add_edge(START, "query_stock")
    builder.add_edge("query_stock", "draft_suggestion")
    builder.add_edge("draft_suggestion", "apply_suggestion")
    builder.add_edge("apply_suggestion", END)
    return builder


def _query_stock_node(state: RestockState, deps: AgentDeps) -> dict[str, object]:
    """Real read gate over a simulated ERP snapshot (self-contained demo)."""
    if not deps.tool_context.permits(PERM_INVENTORY_READ):
        raise PermissionDeniedError(f"permission required to read stock: {PERM_INVENTORY_READ}")
    return {}


def _draft_suggestion_node(state: RestockState) -> dict[str, object]:
    """Deterministic reorder draft (an LLM draft replaces this formula node).

    Suggested quantity tops the stock back above 2x the reorder point; the
    formula mirrors the SKY-68 scan heuristic so review UIs read the same
    shape without a provider round-trip.
    """
    current = Decimal(str(state["current_stock"]))
    reorder = Decimal(str(state["reorder_point"]))
    suggested = max(reorder * 2 - current, reorder)
    return {
        "suggested_qty": int(suggested),
        "reason": f"stock {state['current_stock']} below 2x reorder point {state['reorder_point']}",
    }


async def _apply_suggestion_node(state: RestockState, deps: AgentDeps) -> dict[str, object]:
    """The HITL gate: pause for review, then apply only on approval.

    ``interrupt()`` raises ``GraphInterrupt`` on the first pass; the runtime
    opens the ledger row from its returned value. On resume it returns the
    decision dict, the node runs ONCE, and the checkpoint advances.
    """
    decision = interrupt(
        {
            "tool": "apply_suggestion",
            "required_permission": PERM_INVENTORY_AI_APPROVE,
            "payload": {
                "product_id": state["product_id"],
                "warehouse_id": state["warehouse_id"],
                "current_stock": state["current_stock"],
                "reorder_point": state["reorder_point"],
                "suggested_qty": state["suggested_qty"],
                "reason": state["reason"],
            },
        }
    )
    if not isinstance(decision, dict) or decision.get("decision") != "approved":
        return {"applied": False, "outcome": "denied"}

    try:
        await _persist_suggestion(deps, state)
    except Exception:
        return {"applied": False, "outcome": "write_failed"}
    return {"applied": True, "outcome": "applied"}


async def _persist_suggestion(deps: AgentDeps, state: RestockState) -> None:
    """Approve-side write: one ai_suggestions row + the created audit event."""
    tenant_id = deps.tenant_id
    row = await SuggestionRepository(deps.session).create_pending(
        tenant_id=tenant_id,
        product_id=uuid.UUID(state["product_id"]),
        warehouse_id=uuid.UUID(state["warehouse_id"]),
        current_stock=Decimal(str(state["current_stock"])),
        reorder_point=Decimal(str(state["reorder_point"])),
        suggested_qty=Decimal(str(state["suggested_qty"])),
        estimated_cost=None,
        reason=state["reason"],
        confidence=None,
    )
    await AuditService(AiAuditLogRepository(deps.session)).log(
        action=AI_SUGGESTION_CREATED,
        tenant_id=tenant_id,
        user_id=deps.user_id,
        input_payload={"suggestion_id": str(row.id), "product_id": state["product_id"]},
    )
