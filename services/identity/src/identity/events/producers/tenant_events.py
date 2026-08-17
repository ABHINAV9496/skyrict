"""Tenant/RBAC event producers — tenant provisioning + role grants.

Emits ``skyrict_events`` envelopes through the process-wide producer, which in
Phase 1 is a logging-only stub (see ``identity.events.producers``). Identity
owns tenancy + roles; the core service consumes these events to mirror its
own ``core_roles`` / ``core_user_roles`` rows so ERP ``require_permission``
checks resolve at request time. The schema classes define the exact payload
the real Kafka producer will carry, so swapping the stub in later changes no
call sites.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from identity.events.producers import publish_event
from skyrict_events.schemas import RbacRoleGranted, RoleGrant, TenantProvisioned

if TYPE_CHECKING:
    import uuid


async def emit_tenant_provisioned(
    *,
    tenant_id: str | uuid.UUID,
    slug: str,
    role_grants: list[dict[str, Any]],
) -> None:
    """Publish the full role snapshot after a tenant is provisioned."""
    event = TenantProvisioned(
        tenant_id=str(tenant_id),
        slug=slug,
        role_grants=[RoleGrant(**grant) for grant in role_grants],
    )
    await publish_event(event.event_type, str(tenant_id), event.to_dict())


async def emit_rbac_role_granted(
    *,
    tenant_id: str | uuid.UUID,
    user_id: str | uuid.UUID,
    role_id: str | uuid.UUID,
    role_name: str,
    permissions: list[str],
    is_system_role: bool,
    scope_id: str | uuid.UUID | None = None,
) -> None:
    """Publish a single role grant (incremental, after the grant commits)."""
    event = RbacRoleGranted(
        tenant_id=str(tenant_id),
        grant=RoleGrant(
            role_id=str(role_id),
            role_name=role_name,
            permissions=permissions,
            is_system_role=is_system_role,
            user_id=str(user_id),
            scope_id=str(scope_id) if scope_id is not None else None,
        ),
    )
    await publish_event(event.event_type, str(tenant_id), event.to_dict())
