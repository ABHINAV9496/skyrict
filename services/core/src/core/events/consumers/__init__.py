"""Event consumers — route inbound ``skyrict_events`` envelopes to handlers.

Phase 1: Kafka is NOT wired (see ``core.events.producers`` for the stub
producer). There is therefore no broker consumer loop yet; ``handle_event``
executes the same dispatch the future Kafka consumer will call, so CLI runs,
tests, and the real bus share one code path.
"""

from __future__ import annotations

from typing import Any

import structlog

from core.events.consumers.rbac import RbacProvisionResult, provision_tenant_rbac
from skyrict_events.schemas import (
    RBAC_ROLE_GRANTED_EVENT_TYPE,
    TENANT_PROVISIONED_EVENT_TYPE,
    RbacRoleGranted,
    TenantProvisioned,
)

logger = structlog.get_logger("core.events.consumers")


async def handle_event(payload: dict[str, Any]) -> RbacProvisionResult | None:
    """Dispatch one serialized event envelope to its handler (idempotent).

    Returns the provisioning result when the event was handled, ``None`` for
    unknown event types (logged, not an error — the bus may carry events core
    does not care about).
    """
    event_type = payload.get("event_type")
    if event_type == TENANT_PROVISIONED_EVENT_TYPE:
        provisioned = TenantProvisioned.model_validate(payload)
        return await provision_tenant_rbac(
            tenant_id=provisioned.tenant_id,
            role_grants=[grant.model_dump() for grant in provisioned.role_grants],
        )
    if event_type == RBAC_ROLE_GRANTED_EVENT_TYPE:
        granted = RbacRoleGranted.model_validate(payload)
        return await provision_tenant_rbac(
            tenant_id=granted.tenant_id,
            role_grants=[granted.grant.model_dump()],
        )
    logger.warning("events.unhandled_type", event_type=event_type)
    return None
