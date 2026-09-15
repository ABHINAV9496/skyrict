"""Concurrent-decision race regression (approvals) - real Postgres.

Two actors deciding the SAME step at the same time must never both land:
``update_step_decision`` is a status-guarded atomic UPDATE, so the loser
matches zero rows and the engine raises ``ConflictError`` instead of
double-approving the resource and firing ``on_approved`` twice.

Skipped automatically when Postgres is unreachable (``migrated_schema``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from core.db.session import async_session_factory
from core.features.approval_workflow.engine import ApprovalEngine
from core.features.approval_workflow.instance_repository import (
    ApprovalWorkflowInstanceRepository,
)
from core.features.approval_workflow.ports import ApprovalResourcePort
from core.models.tenant import TenantModel
from skyrict_common.exceptions import ConflictError

pytestmark = pytest.mark.integration

FIXED_NOW = datetime(2026, 9, 14, 9, 0, 0, tzinfo=UTC)
USER_APPROVER = uuid.UUID("33333333-3333-3333-3333-333333333333")


class FakeResourcePort(ApprovalResourcePort):
    def __init__(self) -> None:
        self.on_approved_calls: list[dict[str, object]] = []

    async def submit_for_approval(self, **kwargs: object) -> None:
        return None

    async def on_approved(self, **kwargs: object) -> None:
        self.on_approved_calls.append(kwargs)

    async def on_rejected(self, **kwargs: object) -> None:
        return None

    async def on_request_changes(self, **kwargs: object) -> None:
        return None

    async def on_cancelled(self, **kwargs: object) -> None:
        return None


@pytest.fixture
async def pending_instance(migrated_schema: None) -> tuple[uuid.UUID, uuid.UUID]:
    tenant = uuid.uuid4()
    async with async_session_factory() as session:
        session.add(
            TenantModel(
                id=tenant,
                name="Concurrent Decide Tenant",
                slug=f"dec-{str(tenant)[:8]}",
                plan_tier="free",
                is_active=True,
            )
        )
        await session.commit()

    resource_id = uuid.uuid4()
    async with async_session_factory() as session:
        repo = ApprovalWorkflowInstanceRepository(session)
        instance = await repo.create_instance(
            tenant_id=tenant,
            definition_id=uuid.uuid4(),
            definition_version=1,
            resource_type="journal_entry",
            resource_id=resource_id,
            submitted_by=USER_APPROVER,
            now=FIXED_NOW,
            steps=[
                {
                    "step_key": "approve",
                    "assignee_kind": "users",
                    "assignee_value": str(USER_APPROVER),
                }
            ],
        )
        instance_id = instance.id
        await session.commit()
        return tenant, instance_id


async def test_concurrent_decide_lands_exactly_once(
    pending_instance: tuple[uuid.UUID, uuid.UUID],
) -> None:
    tenant_id, instance_id = pending_instance
    port = FakeResourcePort()

    async def decide() -> str:
        async with async_session_factory() as session:
            engine = ApprovalEngine(
                ApprovalWorkflowInstanceRepository(session),
                now=lambda: FIXED_NOW,
                resource_port=port,
            )
            await engine.decide(
                tenant_id=tenant_id,
                instance_id=instance_id,
                actor_id=USER_APPROVER,
                decision="approved",
            )
            await session.commit()
        return "ok"

    outcomes = await asyncio.gather(decide(), decide(), return_exceptions=True)
    winners = [o for o in outcomes if o == "ok"]
    losers = [o for o in outcomes if isinstance(o, ConflictError)]

    assert len(winners) == 1
    assert len(losers) == 1
    assert len(port.on_approved_calls) == 1

    async with async_session_factory() as session:
        repo = ApprovalWorkflowInstanceRepository(session)
        instance = await repo.get_instance(tenant_id, instance_id)
        steps = await repo.list_steps(tenant_id, instance_id)
        transitions = await repo.list_transitions(tenant_id, instance_id)
    assert instance is not None and instance.status == "approved"
    assert len(steps) == 1 and steps[0].status == "approved"
    assert len(transitions) == 1
