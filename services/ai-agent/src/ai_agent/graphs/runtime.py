"""Agent runtime — executes LangGraph agents with checkpointing + HITL (SKY-59).

Entry points (all tenant-scoped through the request session + RLS):

  ``invoke(agent_name, input_payload, ...)``
      Resolve the agent_registry row (module + tool allowlist), resolve the
      caller's ERP grants into a :class:`ToolContext`, build the graph from the
      module's ``build_graph(deps)`` contract, and run it with the
      checkpointer under a fresh ``graph_run_id``. If the graph pauses at a
      human-in-the-loop interrupt, the runtime validates the interrupt's
      declared tool permission against the caller BEFORE opening a ledger row.

  ``resume(...)``
      Answer a pending interrupt (approve/deny). The decision is recorded on
      the ledger row FIRST (a decided row can never be decided twice — the
      double-approval hole), then the graph resumes through
      ``Command(resume={"decision": ...})``. A stale pending row is lazily
      auto-denied with an audit event (24h window, SKY-59 lazy expiry).

Security posture:
  - Delegation: the caller's JWT/tenant never travel as state — the graph is
    built from operator-managed registry data, and every tool decision flows
    through the ToolContext built from DB-resolved grants.
  - The interrupt value IS the tool contract: it declares the required
    permission so the generic runtime can authorize before persisting
    anything and again before resuming (defense in depth on top of the core
    proxy edge).
  - Execution failures inside the graph are captured into a ``failed``
    outcome — sanitized, never leaking provider/LLM internals.

Consistency note (decision-first ordering): recording the decision before the
resume means a graph crash mid-apply leaves an approved ledger row the
reviewer can investigate; it also cannot be double-approved. Node-side writes
share the request transaction, so a raised handler rolls them back together
with the decision. Graph modules should therefore capture their own write
errors into state (the demo does) instead of raising.
"""

from __future__ import annotations

import importlib
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import structlog
from langgraph.types import Command

from ai_agent.core.audit_events import (
    AI_AGENT_INTERRUPT_APPROVED,
    AI_AGENT_INTERRUPT_DENIED,
    AI_AGENT_INTERRUPT_EXPIRED,
)
from ai_agent.core.audit_service import AuditService
from ai_agent.core.config import Settings, settings
from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.db.agent_registry_repository import AgentRegistryRepository
from ai_agent.db.audit_repository import AiAuditLogRepository
from ai_agent.db.permission_repository import PermissionRepository
from ai_agent.db.suggestion_repository import SuggestionRepository
from ai_agent.graphs.checkpointer import config_for
from ai_agent.graphs.interrupts import InterruptRepository
from ai_agent.graphs.tools import ToolContext
from skyrict_common.exceptions import NotFoundError, PermissionDeniedError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.checkpoint.base import BaseCheckpointSaver
    from sqlalchemy.ext.asyncio import AsyncSession

    from ai_agent.models.agent_interrupt import AgentInterruptModel

logger = structlog.get_logger("ai_agent.runtime")

RunStatus = Literal["completed", "awaiting_decision", "failed"]


@dataclass(frozen=True, slots=True)
class AgentDeployment:
    """The operator-managed agent registration resolved for one run."""

    module: str
    tools: frozenset[str]


@dataclass(slots=True)
class AgentDeps:
    """What a graph builder receives to wire its nodes for ONE run.

    ``suggestions``/``audit`` are the injected persistence ports the runtime
    composes from the request session (RLS-tenanted) — feature slices must not
    import ``ai_agent.db`` directly (import-linter contract). The checkpointer
    sessions are independent by design (see checkpointer.py).
    ``tenant_id``/``user_id`` are the run identity — READ ONLY inside nodes;
    authorization always flows through ``tool_context``, never state.
    """

    tool_context: ToolContext
    allowlist: frozenset[str]
    settings: Settings
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    suggestions: SuggestionRepository
    audit: AuditService


@dataclass(frozen=True, slots=True)
class _ToolCallRequest:
    """The interrupt value contract: tool + permission + payload."""

    tool: str
    required_permission: str
    payload: dict[str, object]

    @classmethod
    def from_value(cls, value: Any) -> _ToolCallRequest:
        """Parse and validate an interrupt value (fails closed on shape)."""
        if not isinstance(value, dict):
            raise ValueError("interrupt value must be a mapping")
        tool = value.get("tool")
        required = value.get("required_permission")
        payload = value.get("payload")
        if not isinstance(tool, str) or not tool:
            raise ValueError("interrupt value missing tool name")
        if not isinstance(required, str) or not required:
            raise ValueError("interrupt value missing required_permission")
        if not isinstance(payload, dict):
            raise ValueError("interrupt value missing payload mapping")
        return cls(tool=tool, required_permission=required, payload=payload)

    def as_dict(self) -> dict[str, object]:
        """The lossless ledger payload (tool + permission + payload)."""
        return {
            "tool": self.tool,
            "required_permission": self.required_permission,
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """The result of one invoke/resume step, ready for the API schema."""

    graph_run_id: uuid.UUID
    agent_name: str
    status: RunStatus
    output: dict[str, object] | None = None
    interrupt: AgentInterruptModel | None = None


class AgentRuntime:
    """Executes registered agents under the caller's resolved identity."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        checkpointer: BaseCheckpointSaver[int],
        resolve_deployment: Callable[[str], Awaitable[AgentDeployment]] | None = None,
        resolve_permissions: Callable[[uuid.UUID, uuid.UUID], Awaitable[list[str]]] | None = None,
        build_graph: Callable[[AgentDeps, str], Any] | None = None,
        interrupts: InterruptRepository | None = None,
        audit: AuditService | None = None,
        suggestions: SuggestionRepository | None = None,
    ) -> None:
        self._session = session
        self._checkpointer = checkpointer
        self._resolve_deployment = resolve_deployment or self._default_deployment
        self._resolve_permissions = resolve_permissions or self._default_permissions
        self._build_graph = build_graph or self._default_graph_builder
        self._interrupts = interrupts or InterruptRepository(session)
        self._audit = audit or AuditService(AiAuditLogRepository(session))
        self._suggestions = suggestions or SuggestionRepository(session)

    # --- public API ---------------------------------------------------------

    async def invoke(
        self,
        *,
        agent_name: str,
        input_payload: dict[str, object],
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> RunOutcome:
        """Start one agent run; returns completed / awaiting_decision / failed."""
        deployment = await self._resolve_deployment(agent_name)
        context = await self._tool_context(user_id, tenant_id)
        graph = self._build_graph(
            AgentDeps(
                tool_context=context,
                allowlist=deployment.tools,
                settings=settings,
                tenant_id=tenant_id,
                user_id=user_id,
                suggestions=self._suggestions,
                audit=self._audit,
            ),
            deployment.module,
        ).compile(checkpointer=self._checkpointer)

        run_id = uuid.uuid4()
        try:
            result = await graph.ainvoke(input_payload, config=config_for(str(run_id)))
        except Exception as exc:
            logger.exception("agent.invoke_failed", agent_name=agent_name)
            return RunOutcome(
                graph_run_id=run_id,
                agent_name=agent_name,
                status="failed",
                output={"error": _sanitize_failure(exc)},
            )

        interrupt = _first_interrupt_value(result)
        if interrupt is not None:
            try:
                request = _ToolCallRequest.from_value(interrupt)
            except ValueError:
                return RunOutcome(
                    graph_run_id=run_id,
                    agent_name=agent_name,
                    status="failed",
                    output={"error": "invalid_interrupt"},
                )
            self._require_tool_access(request, context)
            ledger = await self._interrupts.create_pending(
                tenant_id=tenant_id,
                graph_run_id=run_id,
                agent_name=agent_name,
                tool=request.tool,
                payload=request.as_dict(),
            )
            return RunOutcome(
                graph_run_id=run_id,
                agent_name=agent_name,
                status="awaiting_decision",
                output=None,
                interrupt=ledger,
            )

        return RunOutcome(
            graph_run_id=run_id,
            agent_name=agent_name,
            status="completed",
            output=result if isinstance(result, dict) else {"result": result},
        )

    async def resume(
        self,
        *,
        agent_name: str,
        interrupt_id: uuid.UUID,
        decision: Literal["approved", "denied"],
        decided_by: uuid.UUID,
        note: str | None,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> RunOutcome:
        """Answer a pending interrupt and continue the paused graph run."""
        deployment = await self._resolve_deployment(agent_name)
        context = await self._tool_context(user_id, tenant_id)
        ledger = await self._interrupts.get_for_decision(
            tenant_id=tenant_id, interrupt_id=interrupt_id
        )
        # The path agent must match the row's agent — belt on top of tenant RLS.
        if ledger.agent_name != agent_name:
            raise NotFoundError("Interrupt not found for this run")
        graph_run_id = ledger.graph_run_id

        # Lazy expiry (SKY-59): a stale pending row auto-denies on any touch.
        if await self._interrupts.expire_if_stale(ledger):
            await self._audit.log(
                action=AI_AGENT_INTERRUPT_EXPIRED,
                tenant_id=tenant_id,
                user_id=user_id,
                input_payload={
                    "graph_run_id": str(graph_run_id),
                    "interrupt_id": str(interrupt_id),
                },
            )
            return RunOutcome(
                graph_run_id=ledger.graph_run_id,
                agent_name=agent_name,
                status="failed",
                output={"error": "interrupt_expired"},
            )

        request = _ToolCallRequest.from_value(ledger.payload)
        # Re-authorize at decision time: the deciding caller must ALSO hold the
        # tool's required permission (defense in depth beyond the core edge).
        self._require_tool_access(request, context)

        # Decision first — a decided row can never be decided twice.
        await self._interrupts.record_decision(ledger, decision=decision, decided_by=decided_by)
        await self._audit.log(
            action=(
                AI_AGENT_INTERRUPT_APPROVED if decision == "approved" else AI_AGENT_INTERRUPT_DENIED
            ),
            tenant_id=tenant_id,
            user_id=decided_by,
            input_payload={"graph_run_id": str(graph_run_id), "interrupt_id": str(interrupt_id)},
        )

        graph = self._build_graph(
            AgentDeps(
                tool_context=context,
                allowlist=deployment.tools,
                settings=settings,
                tenant_id=tenant_id,
                user_id=user_id,
                suggestions=self._suggestions,
                audit=self._audit,
            ),
            deployment.module,
        ).compile(checkpointer=self._checkpointer)
        resume_value: dict[str, object] = {
            "decision": decision,
            "decided_by": str(decided_by),
            "note": note,
        }
        try:
            result = await graph.ainvoke(
                Command(resume=resume_value),
                config=config_for(str(ledger.graph_run_id)),
            )
        except Exception as exc:
            logger.exception("agent.resume_failed", agent_name=agent_name)
            return RunOutcome(
                graph_run_id=ledger.graph_run_id,
                agent_name=agent_name,
                status="failed",
                output={"error": _sanitize_failure(exc)},
            )

        next_interrupt = _first_interrupt_value(result)
        if next_interrupt is not None:
            try:
                next_request = _ToolCallRequest.from_value(next_interrupt)
            except ValueError:
                return RunOutcome(
                    graph_run_id=ledger.graph_run_id,
                    agent_name=agent_name,
                    status="failed",
                    output={"error": "invalid_interrupt"},
                )
            self._require_tool_access(next_request, context)
            new_ledger = await self._interrupts.create_pending(
                tenant_id=tenant_id,
                graph_run_id=ledger.graph_run_id,
                agent_name=agent_name,
                tool=next_request.tool,
                payload=next_request.as_dict(),
            )
            return RunOutcome(
                graph_run_id=ledger.graph_run_id,
                agent_name=agent_name,
                status="awaiting_decision",
                output=None,
                interrupt=new_ledger,
            )

        return RunOutcome(
            graph_run_id=ledger.graph_run_id,
            agent_name=agent_name,
            status="completed",
            output=result if isinstance(result, dict) else {"result": result},
        )

    async def list_pending(
        self, *, tenant_id: uuid.UUID, limit: int = 100
    ) -> list[AgentInterruptModel]:
        """The tenant's pending review queue (oldest expiry first)."""
        return await self._interrupts.list_pending(tenant_id=tenant_id, limit=limit)

    # --- internals ----------------------------------------------------------

    async def _tool_context(self, user_id: uuid.UUID, tenant_id: uuid.UUID) -> ToolContext:
        granted = await self._resolve_permissions(user_id, tenant_id)
        return ToolContext(user_id=user_id, granted_permissions=frozenset(granted))

    def _require_tool_access(self, request: _ToolCallRequest, context: ToolContext) -> None:
        if not context.permits(request.required_permission):
            raise PermissionDeniedError(
                f"permission required to invoke {request.tool}: {request.required_permission}"
            )

    async def _default_deployment(self, name: str) -> AgentDeployment:
        row = await AgentRegistryRepository(self._session).get_deployable(name)
        return AgentDeployment(module=row.module, tools=frozenset(row.tools or []))

    async def _default_permissions(self, user_id: uuid.UUID, tenant_id: uuid.UUID) -> list[str]:
        return await PermissionRepository(self._session).resolve_user_permissions(
            user_id=user_id, tenant_id=tenant_id
        )

    def _default_graph_builder(self, deps: AgentDeps, module: str) -> Any:
        """Import the registry module and build its state graph (pre-compile)."""
        graph_module = importlib.import_module(module)
        build = getattr(graph_module, "build_graph", None)
        if build is None or not callable(build):
            raise NotFoundError(f"Agent module has no build_graph: {module}")
        return build(deps)


def _first_interrupt_value(result: Any) -> Any | None:
    """The first interrupt value from a graph result, or None."""
    if not isinstance(result, dict):
        return None
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    return first.value if first is not None else None


def _sanitize_failure(exc: Exception) -> str:
    """Map an execution failure to a non-leaking error key."""
    if isinstance(exc, AiUnavailableError):
        return "ai_unavailable"
    if isinstance(exc, PermissionDeniedError):
        return "permission_denied"
    return "agent_execution_failed"
