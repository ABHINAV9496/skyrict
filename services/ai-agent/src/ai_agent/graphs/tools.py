"""Scoped tool registry — the runtime's permission gate for agent tools.

Each tool in the registry declares the ERP permission its invocation requires.
The runtime (``graphs/runtime.py``, SKY-59) builds a :class:`ToolContext` from
the caller's resolved grants (``db/permission_repository.py``) and refuses any
tool whose key is missing — or that the agent's ``agent_registry`` row does not
list — BEFORE calling the handler. That is defense in depth on top of the core
proxy edge checks (SKY-57: AI is a proxy, not a bypass).

Handlers are plain async callables returning a JSON-safe payload dict; the
registry never sees raw request bodies, provider keys, or anything the handler
did not already sanitize.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_agent.graphs.security import grants_permission
from skyrict_common.exceptions import PermissionDeniedError

if TYPE_CHECKING:
    import uuid
    from collections.abc import Awaitable, Callable, Iterable


@dataclass(frozen=True, slots=True)
class ToolContext:
    """The identity a tool invocation is authorized under.

    ``granted_permissions`` is the caller's resolved grant set for this tenant
    (from ``PermissionRepository``) — never derived from headers or claims.
    """

    user_id: uuid.UUID
    granted_permissions: frozenset[str]

    def permits(self, required: str) -> bool:
        """True when the caller's grants satisfy *required* (fail-closed)."""
        return grants_permission(self.granted_permissions, required)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One registered tool: its required permission and async handler."""

    name: str
    required_permission: str
    handler: Callable[..., Awaitable[dict[str, object]]]


class ToolRegistry:
    """Name-keyed tool catalog with a single authorize/invoke gate.

    Every tool declares a required permission, so the registry is the only
    place that maps tool name -> permission. The allowlist (the agent's
    ``agent_registry.tools`` row) is a second, operator-controlled gate: a
    registered tool is still refused for an agent that does not list it.
    """

    def __init__(self, tools: Iterable[ToolSpec]) -> None:
        registry: dict[str, ToolSpec] = {}
        for tool in tools:
            if tool.name in registry:
                # Fail fast instead of silently shadowing a tool: a duplicate
                # registration is a catalog bug, not a runtime decision.
                raise ValueError(f"duplicate tool registration: {tool.name}")
            registry[tool.name] = tool
        self._tools = registry

    def names(self) -> frozenset[str]:
        """All registered tool names (for startup catalog validation)."""
        return frozenset(self._tools)

    def required_permission(self, name: str) -> str | None:
        """The permission a tool demands; None when the tool is unregistered."""
        spec = self._tools.get(name)
        return spec.required_permission if spec is not None else None

    def authorize(self, name: str, *, context: ToolContext, allowlist: Iterable[str]) -> None:
        """Raise :class:`PermissionDeniedError` unless the tool is allowed.

        Fails closed on every axis: unregistered tool, tool not in the agent's
        allowlist, or a caller whose grants miss the required key.
        """
        spec = self._tools.get(name)
        if spec is None:
            raise PermissionDeniedError(f"tool not registered: {name}")
        if name not in set(allowlist):
            raise PermissionDeniedError(f"tool not allowed for this agent: {name}")
        if not context.permits(spec.required_permission):
            raise PermissionDeniedError(
                f"permission required to invoke {name}: {spec.required_permission}"
            )

    async def invoke(
        self,
        name: str,
        *,
        context: ToolContext,
        allowlist: Iterable[str],
        **kwargs: object,
    ) -> dict[str, object]:
        """Authorize then run the tool handler with *kwargs*.

        There is deliberately no unchecked path: handlers are only reachable
        through this method.
        """
        self.authorize(name, context=context, allowlist=allowlist)
        return await self._tools[name].handler(**kwargs)
