"""Unit tests for the agent permission gate (SKY-59 schema checks).

The gate must mirror core's grants semantics exactly (wildcard owner grant,
exact-key match, fail-closed) because tool authorization runs in this service
against core's permission strings - a drift would silently widen or narrow
access between the proxy edge and the runtime.
"""

from __future__ import annotations

from ai_agent.graphs.security import (
    PERM_AI_INVOKE,
    PERM_INVENTORY_AI_APPROVE,
    PERM_INVENTORY_READ,
    WILDCARD,
    grants_permission,
)


class TestGrantsPermission:
    def test_exact_key_match_passes(self) -> None:
        assert grants_permission([PERM_INVENTORY_READ], PERM_INVENTORY_READ)

    def test_wildcard_owner_grant_passes_every_key(self) -> None:
        granted = [WILDCARD]
        assert grants_permission(granted, PERM_INVENTORY_READ)
        assert grants_permission(granted, PERM_INVENTORY_AI_APPROVE)
        assert grants_permission(granted, PERM_AI_INVOKE)

    def test_unrelated_key_fails_closed(self) -> None:
        assert not grants_permission([PERM_INVENTORY_READ], PERM_INVENTORY_AI_APPROVE)

    def test_empty_grants_fail_closed(self) -> None:
        assert not grants_permission([], PERM_INVENTORY_READ)

    def test_duplicate_grants_do_not_matter(self) -> None:
        assert grants_permission([PERM_INVENTORY_READ, PERM_INVENTORY_READ], PERM_INVENTORY_READ)

    def test_partial_match_on_dotted_prefix_does_not_pass(self) -> None:
        # A grant of "erp.inventory" must NEVER satisfy "erp.inventory.read" -
        # only exact keys or the owner wildcard count.
        assert not grants_permission(["erp.inventory"], PERM_INVENTORY_READ)

    def test_any_iterable_source_works(self) -> None:
        assert grants_permission(["other", PERM_AI_INVOKE], PERM_AI_INVOKE)
        assert not grants_permission(("other",), PERM_AI_INVOKE)


class TestKeyContract:
    def test_keys_are_platform_literals(self) -> None:
        """The strings ARE the cross-service contract - pin them verbatim."""
        assert PERM_AI_INVOKE == "erp.ai.invoke"
        assert PERM_INVENTORY_READ == "erp.inventory.read"
        assert PERM_INVENTORY_AI_APPROVE == "erp.inventory.ai.approve"
        assert WILDCARD == "*"

    def test_invoke_is_distinct_from_domain_keys(self) -> None:
        # erp.ai.invoke is the base AI gate; domain keys scope individual tools.
        assert len({PERM_AI_INVOKE, PERM_INVENTORY_READ, PERM_INVENTORY_AI_APPROVE}) == 3

    def test_empty_required_key_does_not_pass_without_wildcard(self) -> None:
        # A tool must always declare a real permission key; an empty spec
        # string must never be trivially satisfied by a bare grant set.
        assert not grants_permission([PERM_INVENTORY_READ], "")
