"""Entity resolution - match user-mentioned names to real catalog rows.

Spec §2.4: "Parsed intent validated against actual product/warehouse names
before execution". A mention that matches nothing or ambiguously produces a
clarification response, never a guessed query. Matching is case-insensitive
exact first, then unique substring - deliberately dumb and predictable.
Product/warehouse names are DATA (spec §5.6): they are echoed back verbatim,
never interpreted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from ai_agent.features.nl_query.gateway import ProductRef, WarehouseRef


@dataclass(frozen=True, slots=True)
class MatchOutcome:
    """Result of resolving one mentioned name against a catalog."""

    entity_id: uuid.UUID | None
    status: str  # "matched" | "unknown" | "ambiguous"
    # The canonical catalog name when matched; the raw user text otherwise.
    display_name: str


def _match_name(mentioned: str, candidates: Sequence[tuple[uuid.UUID, str]]) -> MatchOutcome:
    lowered = mentioned.strip().lower()
    if not lowered:
        return MatchOutcome(None, "unknown", mentioned)

    exact = [(eid, name) for eid, name in candidates if name.lower() == lowered]
    if len(exact) == 1:
        return MatchOutcome(exact[0][0], "matched", exact[0][1])

    partial = [(eid, name) for eid, name in candidates if lowered in name.lower()]
    if len(partial) == 1:
        return MatchOutcome(partial[0][0], "matched", partial[0][1])
    if len(partial) > 1:
        return MatchOutcome(None, "ambiguous", mentioned)
    return MatchOutcome(None, "unknown", mentioned)


def resolve_product(mentioned: str | None, products: Sequence[ProductRef]) -> MatchOutcome | None:
    """Resolve a product mention; ``None`` when the question named no product."""
    if mentioned is None:
        return None
    return _match_name(mentioned, [(p.id, p.name) for p in products])


def resolve_warehouse(
    mentioned: str | None, warehouses: Sequence[WarehouseRef]
) -> MatchOutcome | None:
    """Resolve a warehouse mention; ``None`` when none was named."""
    if mentioned is None:
        return None
    return _match_name(mentioned, [(w.id, w.name) for w in warehouses])
