"""Restock suggestion calculator - the v1 formula from spec §3.2.

Pure functions, no I/O: given a product's stock facts, produce the
suggestion draft (quantity, cost, reason, confidence).

Confidence note (v1 limitation): the spec's four-factor confidence table
(data quality 30%, demand stability 30%, proximity 20%, replenishment
recency 20%) requires movement/demand history that core does not expose
over HTTP yet. v1 therefore derives confidence ONLY from stock-level
proximity to the reorder point - the one computable factor - and caps it
at 0.95. This is a documented placeholder heuristic, not the spec's final
scoring; revisit when demand history becomes available.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid

    from ai_agent.features.nl_query.gateway import ProductRef

# v1 heuristic bounds: never claim certainty we cannot justify.
_CONFIDENCE_FLOOR = Decimal("0.50")
_CONFIDENCE_CEILING = Decimal("0.95")


@dataclass(frozen=True, slots=True)
class SuggestionDraft:
    """One computed restock proposal, ready for persistence."""

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    current_stock: Decimal
    reorder_point: Decimal
    suggested_qty: Decimal
    estimated_cost: Decimal | None
    reason: str
    confidence: Decimal


def compute_suggestion(
    *, product: ProductRef, warehouse_id: uuid.UUID, qty_on_hand: Decimal
) -> SuggestionDraft:
    """Apply the spec §3.2 v1 formula to one product/warehouse pair."""
    suggested_qty = product.reorder_point * Decimal(2)
    reason = f"Stock ({qty_on_hand}) below reorder point ({product.reorder_point})."
    # Cost prices are LOCAL-ONLY data (spec §5.5): they are used for the
    # estimate here and returned to the tenant - never sent to any LLM.
    estimated_cost = suggested_qty * product.cost_price if product.cost_price is not None else None
    return SuggestionDraft(
        product_id=product.id,
        warehouse_id=warehouse_id,
        current_stock=qty_on_hand,
        reorder_point=product.reorder_point,
        suggested_qty=suggested_qty,
        estimated_cost=estimated_cost,
        reason=reason,
        confidence=_proximity_confidence(qty_on_hand, product.reorder_point),
    )


def _proximity_confidence(qty_on_hand: Decimal, reorder_point: Decimal) -> Decimal:
    """v1 placeholder: deeper below reorder point => more confident suggestion.

    Maps the deficit ratio linearly onto [0.50, 0.95]. A deficit of one full
    reorder point or more hits the ceiling.
    """
    if reorder_point <= 0:
        return _CONFIDENCE_FLOOR
    deficit_ratio = (reorder_point - qty_on_hand) / reorder_point
    span = _CONFIDENCE_CEILING - _CONFIDENCE_FLOOR
    return min(_CONFIDENCE_CEILING, _CONFIDENCE_FLOOR + abs(deficit_ratio) * span)
