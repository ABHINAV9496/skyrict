"""CRM event producers — structured domain events for the CRM feature.

Follows the HR event pattern (docs/modules/sales-crm.md §2.5): each
``emit_*`` function builds the shared ``skyrict_events.BaseEvent`` envelope
and publishes it via ``apublish`` — which buffers the event while a request
transaction is open and drains it on the session's ``after_commit`` hook
(core/db/session.py), so a consumer can never observe CRM state that did not
actually commit.

One event per transition (the catalog is exactly the topics in §2.5):
``won``/``lost`` are the terminal announcements and fire INSTEAD of
``stage_changed`` for those transitions — ``stage_changed`` covers the
non-terminal pipeline movement (``prospecting -> qualified -> proposal ->
negotiation``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.events.producers import apublish
from skyrict_events.base import BaseEvent

if TYPE_CHECKING:
    import uuid


async def emit_lead_created(
    *,
    lead_id: uuid.UUID,
    tenant_id: uuid.UUID,
    source: str | None,
    email: str | None,
) -> None:
    """Emit ``crm.lead.created`` (lead inserted)."""
    metadata: dict[str, object] = {"lead_id": str(lead_id)}
    if source is not None:
        metadata["source"] = source
    if email is not None:
        metadata["email"] = email
    event = BaseEvent(
        event_type="crm.lead.created",
        tenant_id=str(tenant_id),
        metadata=metadata,
    )
    await apublish("crm.lead.created", event, key=str(tenant_id))


async def emit_lead_status_changed(
    *,
    lead_id: uuid.UUID,
    tenant_id: uuid.UUID,
    from_status: str,
    to_status: str,
) -> None:
    """Emit ``crm.lead.status_changed`` (lead status transition)."""
    event = BaseEvent(
        event_type="crm.lead.status_changed",
        tenant_id=str(tenant_id),
        metadata={
            "lead_id": str(lead_id),
            "from_status": from_status,
            "to_status": to_status,
        },
    )
    await apublish("crm.lead.status_changed", event, key=str(tenant_id))


async def emit_opportunity_stage_changed(
    *,
    opportunity_id: uuid.UUID,
    tenant_id: uuid.UUID,
    from_stage: str | None,
    to_stage: str,
) -> None:
    """Emit ``crm.opportunity.stage_changed`` (non-terminal stage move)."""
    metadata: dict[str, object] = {
        "opportunity_id": str(opportunity_id),
        "to_stage": to_stage,
    }
    if from_stage is not None:
        metadata["from_stage"] = from_stage
    event = BaseEvent(
        event_type="crm.opportunity.stage_changed",
        tenant_id=str(tenant_id),
        metadata=metadata,
    )
    await apublish("crm.opportunity.stage_changed", event, key=str(tenant_id))


async def emit_opportunity_won(
    *,
    opportunity_id: uuid.UUID,
    tenant_id: uuid.UUID,
    from_stage: str,
    amount: str | None = None,
) -> None:
    """Emit ``crm.opportunity.won`` (terminal won transition)."""
    metadata: dict[str, object] = {
        "opportunity_id": str(opportunity_id),
        "from_stage": from_stage,
    }
    if amount is not None:
        metadata["amount"] = amount
    event = BaseEvent(
        event_type="crm.opportunity.won",
        tenant_id=str(tenant_id),
        metadata=metadata,
    )
    await apublish("crm.opportunity.won", event, key=str(tenant_id))


async def emit_opportunity_lost(
    *,
    opportunity_id: uuid.UUID,
    tenant_id: uuid.UUID,
    from_stage: str,
    lost_reason: str | None,
) -> None:
    """Emit ``crm.opportunity.lost`` (terminal lost transition)."""
    metadata: dict[str, object] = {
        "opportunity_id": str(opportunity_id),
        "from_stage": from_stage,
    }
    if lost_reason is not None:
        metadata["lost_reason"] = lost_reason
    event = BaseEvent(
        event_type="crm.opportunity.lost",
        tenant_id=str(tenant_id),
        metadata=metadata,
    )
    await apublish("crm.opportunity.lost", event, key=str(tenant_id))


async def emit_customer_created(
    *,
    customer_id: uuid.UUID,
    customer_code: str,
    tenant_id: uuid.UUID,
    name: str,
) -> None:
    """Emit ``crm.customer.created`` (customer inserted)."""
    event = BaseEvent(
        event_type="crm.customer.created",
        tenant_id=str(tenant_id),
        metadata={
            "customer_id": str(customer_id),
            "customer_code": customer_code,
            "name": name,
        },
    )
    await apublish("crm.customer.created", event, key=str(tenant_id))


async def emit_contact_created(
    *,
    contact_id: uuid.UUID,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    email: str | None,
) -> None:
    """Emit ``crm.contact.created`` (contact inserted)."""
    metadata: dict[str, object] = {"contact_id": str(contact_id), "customer_id": str(customer_id)}
    if email is not None:
        metadata["email"] = email
    event = BaseEvent(
        event_type="crm.contact.created",
        tenant_id=str(tenant_id),
        metadata=metadata,
    )
    await apublish("crm.contact.created", event, key=str(tenant_id))


async def emit_activity_created(
    *,
    activity_id: uuid.UUID,
    tenant_id: uuid.UUID,
    kind: str,
    entity_type: str,
    entity_id: uuid.UUID,
) -> None:
    """Emit ``crm.activity.created`` (activity inserted)."""
    event = BaseEvent(
        event_type="crm.activity.created",
        tenant_id=str(tenant_id),
        metadata={
            "activity_id": str(activity_id),
            "kind": kind,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
        },
    )
    await apublish("crm.activity.created", event, key=str(tenant_id))


async def emit_activity_completed(
    *,
    activity_id: uuid.UUID,
    tenant_id: uuid.UUID,
    completed_by: uuid.UUID | None,
) -> None:
    """Emit ``crm.activity.completed`` (task/follow-up finished)."""
    metadata: dict[str, object] = {"activity_id": str(activity_id)}
    if completed_by is not None:
        metadata["completed_by"] = str(completed_by)
    event = BaseEvent(
        event_type="crm.activity.completed",
        tenant_id=str(tenant_id),
        metadata=metadata,
    )
    await apublish("crm.activity.completed", event, key=str(tenant_id))


async def emit_note_created(
    *,
    note_id: uuid.UUID,
    tenant_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
) -> None:
    """Emit ``crm.note.created`` (note inserted)."""
    event = BaseEvent(
        event_type="crm.note.created",
        tenant_id=str(tenant_id),
        metadata={
            "note_id": str(note_id),
            "entity_type": entity_type,
            "entity_id": str(entity_id),
        },
    )
    await apublish("crm.note.created", event, key=str(tenant_id))
