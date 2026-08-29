"""Pure value objects for the inventory-AI demand layer (INV-AI-002).

``DemandStats`` is the rolling per-product+warehouse demand profile. It lives
in the domain layer (not the feature slice) because both the feature-side
computation (features.restock.demand_stats) and the persistence side
(db.restock_stats_repository) consume it, and the architecture forbids either
from importing the other. Stdlib types only - no framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid
    from datetime import datetime
    from decimal import Decimal


@dataclass(frozen=True, slots=True)
class DemandStats:
    """One product+warehouse's rolling demand profile (value object)."""

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    avg_daily_demand: Decimal
    demand_cv: Decimal
    window_days: int
    last_receipt_at: datetime | None
    eligible: bool
