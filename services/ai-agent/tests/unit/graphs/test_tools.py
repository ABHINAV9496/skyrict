"""Unit tests for the scoped tool registry (SKY-59).

The registry is the runtime's single authorize/invoke gate: unregistered tools,
tools outside the agent's registry allowlist, and callers missing the required
permission are all refused BEFORE any handler runs. Handlers are only reachable
through ``invoke``.
"""

from __future__ import annotations

import uuid

import pytest

from ai_agent.graphs.security import (
    PERM_AI_INVOKE,
    PERM_INVENTORY_AI_APPROVE,
    PERM_INVENTORY_READ,
    WILDCARD,
)
from ai_agent.graphs.tools import ToolContext, ToolRegistry, ToolSpec
from skyrict_common.exceptions import PermissionDeniedError

USER_ID = uuid.uuid4()


def _ctx(*permissions: str) -> ToolContext:
    return ToolContext(user_id=USER_ID, granted_permissions=frozenset(permissions))


async def _handler(**_: object) -> dict[str, object]:
    return {"ok": True}


def _registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolSpec(name="query_stock", required_permission=PERM_INVENTORY_READ, handler=_handler),
            ToolSpec(name="draft_suggestion", required_permission=PERM_AI_INVOKE, handler=_handler),
            ToolSpec(
                name="apply_suggestion",
                required_permission=PERM_INVENTORY_AI_APPROVE,
                handler=_handler,
            ),
        ]
    )


class TestRegistryCatalog:
    def test_names_and_permissions_are_public(self) -> None:
        registry = _registry()
        assert registry.names() == {
            "query_stock",
            "draft_suggestion",
            "apply_suggestion",
        }
        assert registry.required_permission("query_stock") == PERM_INVENTORY_READ
        assert registry.required_permission("apply_suggestion") == PERM_INVENTORY_AI_APPROVE
        assert registry.required_permission("nope") is None

    def test_registry_rejects_duplicate_names(self) -> None:
        tools = [
            ToolSpec(name="query_stock", required_permission=PERM_INVENTORY_READ, handler=_handler),
            ToolSpec(name="query_stock", required_permission=PERM_AI_INVOKE, handler=_handler),
        ]
        # A duplicate registration must fail fast - a silently shadowed tool
        # would be an un-auditable permission change.
        with pytest.raises(ValueError, match="duplicate tool registration"):
            ToolRegistry(tools)


class TestAuthorize:
    def test_granted_exact_key_passes(self) -> None:
        _registry().authorize(
            "query_stock", context=_ctx(PERM_INVENTORY_READ), allowlist=["query_stock"]
        )

    def test_owner_wildcard_passes_any_tool(self) -> None:
        registry = _registry()
        for name in registry.names():
            registry.authorize(name, context=_ctx(WILDCARD), allowlist=registry.names())

    def test_unregistered_tool_is_refused(self) -> None:
        with pytest.raises(PermissionDeniedError, match="not registered"):
            _registry().authorize(
                "query_missing", context=_ctx(WILDCARD), allowlist=["query_missing"]
            )

    def test_registered_but_not_in_agent_allowlist_is_refused(self) -> None:
        with pytest.raises(PermissionDeniedError, match="not allowed for this agent"):
            _registry().authorize(
                "query_stock", context=_ctx(PERM_INVENTORY_READ), allowlist=["apply_suggestion"]
            )

    def test_missing_permission_is_refused_even_when_allowlisted(self) -> None:
        with pytest.raises(PermissionDeniedError, match="permission required"):
            _registry().authorize(
                "apply_suggestion",
                context=_ctx(PERM_INVENTORY_READ),
                allowlist=["apply_suggestion"],
            )

    def test_empty_allowlist_refuses_everything(self) -> None:
        with pytest.raises(PermissionDeniedError):
            _registry().authorize("query_stock", context=_ctx(WILDCARD), allowlist=[])


class TestInvoke:
    async def test_invoke_runs_handler_after_gate(self) -> None:
        result = await _registry().invoke(
            "query_stock", context=_ctx(PERM_INVENTORY_READ), allowlist=["query_stock"]
        )
        assert result == {"ok": True}

    async def test_invoke_refuses_without_permission(self) -> None:
        with pytest.raises(PermissionDeniedError):
            await _registry().invoke(
                "query_stock", context=_ctx(PERM_AI_INVOKE), allowlist=["query_stock"]
            )

    async def test_invoke_passes_kwargs_to_handler(self) -> None:
        seen: list[dict[str, object]] = []

        async def capture(product_id: object) -> dict[str, object]:
            seen.append({"product_id": product_id})
            return {"captured": True}

        registry = ToolRegistry(
            [ToolSpec(name="query_stock", required_permission=PERM_INVENTORY_READ, handler=capture)]
        )
        await registry.invoke(
            "query_stock",
            context=_ctx(PERM_INVENTORY_READ),
            allowlist=["query_stock"],
            product_id="p1",
        )
        assert seen == [{"product_id": "p1"}]
