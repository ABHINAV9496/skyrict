"""Version-counter race regression (B10) - real Postgres.

Two concurrent ``create_draft`` calls for the SAME (resource_type) family
must produce distinct versions: the definition family is guarded by
``uq_erp_approval_workflow_definitions_tenant_resource_version``, so a
``max(version) + 1`` race would fail one of the two inserts with a unique
violation (500). The family lock serializes allocation per family.

Skipped automatically when Postgres is unreachable (``migrated_schema``).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from core.db.session import async_session_factory
from core.features.approval_workflow.definition_repository import (
    ApprovalWorkflowDefinitionRepository,
)
from core.models.tenant import TenantModel

pytestmark = pytest.mark.integration


@pytest.fixture
async def def_world(migrated_schema: None) -> dict[str, object]:
    tenant = uuid.uuid4()
    async with async_session_factory() as session:
        session.add(
            TenantModel(
                id=tenant,
                name="Versioning Tenant",
                slug=f"ver-{str(tenant)[:8]}",
                plan_tier="free",
                is_active=True,
            )
        )
        await session.commit()
    return {"tenant_id": tenant}


async def test_concurrent_draft_versions_do_not_collide(
    def_world: dict[str, object],
) -> None:
    tenant_id = def_world["tenant_id"]
    assert isinstance(tenant_id, uuid.UUID)
    resource_type = "trip-budget"

    async def create_draft() -> int:
        async with async_session_factory() as session:
            repo = ApprovalWorkflowDefinitionRepository(session)
            version = await repo.next_version(tenant_id, resource_type)
            await repo.create_draft(
                tenant_id=tenant_id,
                name="Trip Budget Policy",
                resource_type=resource_type,
                definition={"steps": [{"actor": "role:finance", "action": "approve"}]},
            )
            await session.commit()
            return version

    versions = await asyncio.gather(create_draft(), create_draft())

    assert versions[0] != versions[1]
    assert sorted(versions) == [1, 2]

    async with async_session_factory() as session:
        repo = ApprovalWorkflowDefinitionRepository(session)
        next_version = await repo.next_version(tenant_id, resource_type)
    assert next_version == 3


async def test_concurrent_activations_leave_single_active(
    def_world: dict[str, object],
) -> None:
    """Two drafts for one resource_type, activated concurrently.

    Without the family lock both would see an empty ``status='active'`` set,
    both seal their draft, and the engine ends up with two active versions to
    route on. The lock serializes activation per family so exactly one remains
    active; the loser's draft retires the winner's active version instead."
    """
    tenant_id = def_world["tenant_id"]
    assert isinstance(tenant_id, uuid.UUID)
    resource_type = "purchase-order"

    async def make_draft() -> uuid.UUID:
        async with async_session_factory() as session:
            repo = ApprovalWorkflowDefinitionRepository(session)
            draft = await repo.create_draft(
                tenant_id=tenant_id,
                name="PO Policy",
                resource_type=resource_type,
                definition={"steps": [{"actor": "role:procurement", "action": "approve"}]},
            )
            draft_id = draft.id
            await session.commit()
            return draft_id

    ids = await asyncio.gather(make_draft(), make_draft())

    async def activate(draft_id: uuid.UUID) -> None:
        async with async_session_factory() as session:
            repo = ApprovalWorkflowDefinitionRepository(session)
            await repo.activate(tenant_id, draft_id)
            await session.commit()

    await asyncio.gather(activate(ids[0]), activate(ids[1]))

    async with async_session_factory() as session:
        repo = ApprovalWorkflowDefinitionRepository(session)
        active = await repo.get_active(tenant_id, resource_type)
        all_defs = await repo.list(tenant_id, resource_type=resource_type)
        active_count = sum(1 for d in all_defs if d.status == "active")

    assert active is not None
    assert active_count == 1
    assert [d for d in all_defs if d.id != active.id]  # the loser still exists (retired)
