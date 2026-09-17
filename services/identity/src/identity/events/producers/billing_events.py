"""Billing event producers - plan changes.

Emits ``skyrict_events`` envelopes through the process-wide producer, which in
Phase 1 is a logging-only stub (see ``identity.events.producers``). The schema
class defines the exact payload the real Kafka producer will carry, so swapping
the stub in later changes no call sites.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from identity.events.producers import publish_event
from skyrict_events.schemas import PlanChanged

if TYPE_CHECKING:
    import uuid
    from datetime import datetime


async def emit_plan_changed(
    *,
    tenant_id: str | uuid.UUID,
    previous_tier: str,
    new_tier: str,
    subscription_status: str,
    trial_ends_at: datetime | None = None,
) -> None:
    """Publish a plan-tier change for a tenant."""
    event = PlanChanged(
        tenant_id=str(tenant_id),
        previous_tier=previous_tier,
        new_tier=new_tier,
        subscription_status=subscription_status,
        trial_ends_at=trial_ends_at,
    )
    await publish_event(event.event_type, str(tenant_id), event.to_dict())
