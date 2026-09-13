"""Unit tests for SKY-92: payroll run approval routing.

Covers :class:`PayrollRunApprovalCoordinator` and the
``PayrollService.approve_run`` seam:

- flag OFF => the existing direct APPROVED transition runs unchanged (no
  workflow instance is ever created);
- flag ON + no active definition => ``ApprovalDefinitionMissingError`` and the
  run NEVER transitions (no silent fallback direct approval);
- below-threshold total-NET amounts auto-approve (system actor) and
  transition immediately;
- at-or-above-threshold amounts land on the human queue and the run is
  returned still COMPUTED - the APPROVED transition happens only on a later
  human decision;
- AI routing is advisory, only on an AI-assisted step, and the eligible
  approver set is passed for validation; an AI failure never blocks the run.

The engine's own decision/escalation behavior is covered by the approval
workflow engine suite; these tests exercise the payroll-side orchestration
with fake repositories (the repo fake-session convention).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pytest import mark

from core.core.audit_service import AuditService
from core.core.constants import PayrollRunStatus
from core.core.exceptions import ApprovalDefinitionMissingError
from core.core.permissions import ERP_PAYROLL_APPROVE
from core.domain import entities as ent
from core.domain.value_objects import Money
from core.features.approval_workflow.ai_routing import ApprovalRoutingSuggestion
from core.features.approval_workflow.delegation_repository import (
    ApprovalDelegationRepository,
)
from core.features.approval_workflow.dsl import (
    AmountBelowCondition,
    AutoApprovalRule,
    PermissionAssignee,
    RoutingStrategy,
    SlaPolicy,
    WorkflowDefinition,
    WorkflowStep,
)
from core.features.payroll.approval import (
    RESOURCE_TYPE,
    PayrollRunApprovalCoordinator,
)
from core.features.payroll.service import PayrollService

pytestmark = mark.unit

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
RUN_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
INSTANCE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
APPROVER = uuid.UUID("aaaa0000-0000-4000-8000-000000000001")
OTHER_USER = uuid.UUID("bbbb0000-0000-4000-8000-000000000002")
FIXED_NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)

THRESHOLD = Decimal("10000.00")


# --------------------------------------------------------------------- fakes


class _FakeSession:
    """Never touched by the coordinator paths under test (flag is mocked)."""


class FakeDefinitionStore:
    def __init__(self, definition_doc: dict | None) -> None:
        self._doc = definition_doc

    async def get_active(self, tenant_id: uuid.UUID, resource_type: str) -> SimpleNamespace | None:
        if self._doc is None:
            return None
        return SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            resource_type=resource_type,
            version=1,
            definition=self._doc,
        )


class FakeInstanceRepo:
    """Records instances/steps/transitions; resolves assignees from maps."""

    def __init__(self) -> None:
        self.instances: list[SimpleNamespace] = []
        self.steps: list[SimpleNamespace] = []
        self.transitions: list[dict] = []
        self.permission_members: dict[str, list[uuid.UUID]] = {}
        self.role_members: dict[str, list[uuid.UUID]] = {}

    async def create_instance(self, **kw: object) -> SimpleNamespace:
        instance = SimpleNamespace(
            id=INSTANCE_ID,
            tenant_id=kw["tenant_id"],
            definition_id=kw["definition_id"],
            definition_version=kw["definition_version"],
            resource_type=kw["resource_type"],
            resource_id=kw["resource_id"],
            status="pending",
            current_step_index=0,
            submitted_by=kw["submitted_by"],
            submitted_at=kw["now"],
        )
        self.instances.append(instance)
        for index, step_info in enumerate(kw["steps"]):  # type: ignore[arg-type]
            self.steps.append(
                SimpleNamespace(
                    id=uuid.uuid4(),
                    instance_id=instance.id,
                    step_index=index,
                    step_key=step_info["step_key"],  # type: ignore[index]
                    assignee_kind=step_info["assignee_kind"],  # type: ignore[index]
                    assignee_value=step_info["assignee_value"],  # type: ignore[index]
                    status="pending",
                    sla_due_at=step_info.get("sla_due_at"),  # type: ignore[union-attr]
                )
            )
        return instance

    async def get_instance(
        self, tenant_id: uuid.UUID, instance_id: uuid.UUID
    ) -> SimpleNamespace | None:
        for instance in self.instances:
            if instance.id == instance_id:
                return instance
        return None

    async def list_steps(
        self, tenant_id: uuid.UUID, instance_id: uuid.UUID
    ) -> list[SimpleNamespace]:
        return [s for s in self.steps if s.instance_id == instance_id]

    async def update_step_decision(self, **kw: object) -> SimpleNamespace | None:
        for step in self.steps:
            if step.id == kw["step_id"]:  # type: ignore[union-attr]
                step.status = kw["status"]  # type: ignore[assignment]
                step.decided_by = kw["decided_by"]  # type: ignore[assignment]
                step.decided_at = kw["decided_at"]  # type: ignore[assignment]
                return step
        return None

    async def update_instance_status(self, **kw: object) -> SimpleNamespace | None:
        instance = await self.get_instance(
            kw["tenant_id"],  # type: ignore[arg-type]
            kw["instance_id"],  # type: ignore[arg-type]
        )
        if instance is None:
            return None
        instance.status = kw["status"]  # type: ignore[assignment]
        instance.current_step_index = kw["current_step_index"]  # type: ignore[assignment]
        instance.updated_by = kw["updated_by"]  # type: ignore[assignment]
        return instance

    async def record_transition(self, **kw: object) -> None:
        self.transitions.append(kw)

    async def resolve_role_members(self, tenant_id: uuid.UUID, role_name: str) -> list[uuid.UUID]:
        return self.role_members.get(role_name, [])

    async def resolve_permission_members(
        self, tenant_id: uuid.UUID, permission: str
    ) -> list[uuid.UUID]:
        return self.permission_members.get(permission, [])


class FakeSuggestionService:
    def __init__(self, suggestion: ApprovalRoutingSuggestion | None = None) -> None:
        self.suggestion = suggestion
        self.calls: list[dict] = []

    async def suggest_and_record(self, **kw: object) -> ApprovalRoutingSuggestion | None:
        self.calls.append(kw)
        if self.suggestion is None:
            return None
        return self.suggestion


class FakeApprover:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def complete_approval(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        approved_by: uuid.UUID | None,
        actor_user_id: uuid.UUID | None,
        approved_at: datetime,
    ) -> SimpleNamespace:
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "run_id": run_id,
                "approved_by": approved_by,
                "actor_user_id": actor_user_id,
                "approved_at": approved_at,
            }
        )
        return SimpleNamespace(id=run_id, tenant_id=tenant_id, status="approved")


class FakePayrollRepo:
    def __init__(self, run: ent.PayrollRun | None = None) -> None:
        self.run = run
        self.transition_calls: list[dict] = []

    async def get_run(self, run_id: uuid.UUID, tenant_id: uuid.UUID) -> ent.PayrollRun | None:
        return self.run if self.run is not None and self.run.id == run_id else None

    async def transition_run_status(
        self,
        run_id: uuid.UUID,
        from_status: str,
        to_status: str,
        **kw: object,
    ) -> ent.PayrollRun | None:
        self.transition_calls.append(
            {"run_id": run_id, "from_status": from_status, "to_status": to_status, **kw}
        )
        if self.run is None or self.run.status.value != from_status:
            return None
        self.run = dataclasses.replace(
            self.run,
            status=PayrollRunStatus(to_status),
            approved_by=kw.get("approved_by"),  # type: ignore[arg-type]
            approved_at=kw.get("approved_at"),
        )
        return self.run

    async def list_entries(self, run_id: uuid.UUID, *, tenant_id: uuid.UUID):
        return []


class FakeAuditRepository:
    def __init__(self) -> None:
        self.added: list[ent.AuditLogEntry] = []

    async def add(self, entry: ent.AuditLogEntry) -> ent.AuditLogEntry:
        self.added.append(entry)
        return entry


class FakeLeaveLedger:
    async def approved_unpaid_days(
        self, employee_id: uuid.UUID, *, tenant_id: uuid.UUID, period_start: date, period_end: date
    ) -> int:
        return 0

    async def list_accrual_leave_types(self, tenant_id: uuid.UUID) -> list[str]:
        return []

    async def accrue(self, **kw: object) -> None:
        return None


# ------------------------------------------------------------------- helpers


def _definition_doc(*, routing: RoutingStrategy = RoutingStrategy.AI_ASSISTED) -> dict:
    return WorkflowDefinition(
        name="Payroll run approval",
        resource_type=RESOURCE_TYPE,
        version=1,
        steps=[
            WorkflowStep(
                key="payroll_approval",
                assignee=PermissionAssignee(permission=ERP_PAYROLL_APPROVE),
                routing=routing,
                auto_approval=AutoApprovalRule(when=AmountBelowCondition(amount=THRESHOLD)),
                sla=SlaPolicy(hours=24, reminder_before_hours=4),
            )
        ],
    ).model_dump(mode="json")


def _make_coordinator(
    *,
    flag_enabled: bool,
    definition_doc: dict | None,
    inst_repo: FakeInstanceRepo | None = None,
    suggestion_service: FakeSuggestionService | None = None,
    ai_client: object = None,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[PayrollRunApprovalCoordinator, FakeApprover, FakeInstanceRepo]:
    session = _FakeSession()
    approver = FakeApprover()
    repo = inst_repo or FakeInstanceRepo()
    coordinator = PayrollRunApprovalCoordinator(
        db=session,  # type: ignore[arg-type]
        definitions=FakeDefinitionStore(definition_doc),  # type: ignore[arg-type]
        instances=repo,  # type: ignore[arg-type]
        delegations=ApprovalDelegationRepository(session),  # type: ignore[arg-type]
        now=lambda: FIXED_NOW,
        ai_client=ai_client,  # type: ignore[arg-type]
        ai_authorization=None,
        ai_tenant_slug="acme-inc",
        complete_verified=approver.complete_approval,
        suggestion_service=suggestion_service,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        "core.features.payroll.approval.payroll_approval_engine_enabled",
        _flag(flag_enabled),
    )
    return coordinator, approver, repo


def _flag(enabled: bool):
    async def _impl(session: object, tenant_id: uuid.UUID) -> bool:
        return enabled

    return _impl


def _run(amount: str = "12000.00") -> ent.PayrollRun:
    return ent.PayrollRun(
        tenant_id=TENANT,
        run_code="RN-2026-09",
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        status=PayrollRunStatus.COMPUTED,
        total_net=Money(Decimal(amount), "USD"),
        id=RUN_ID,
    )


# ------------------------------------------------------- coordinator: flag OFF


async def test_flag_off_approves_directly_without_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator, approver, repo = _make_coordinator(
        flag_enabled=False, definition_doc=_definition_doc(), monkeypatch=monkeypatch
    )

    run = _run(amount="8000.00")
    result = await coordinator.submit_for_approval(
        tenant_id=TENANT,
        user_id=OTHER_USER,
        actor_user_id=OTHER_USER,
        run=run,
        total_net=Decimal("8000.00"),
    )

    assert result.status == "approved"
    assert len(approver.calls) == 1
    assert approver.calls[0]["approved_by"] == OTHER_USER
    assert approver.calls[0]["actor_user_id"] == OTHER_USER
    assert approver.calls[0]["approved_at"] == FIXED_NOW
    # The engine was never involved.
    assert repo.instances == []


# -------------------------------------------------- coordinator: missing def


async def test_flag_on_without_definition_raises_and_never_approves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator, approver, repo = _make_coordinator(
        flag_enabled=True, definition_doc=None, monkeypatch=monkeypatch
    )

    with pytest.raises(ApprovalDefinitionMissingError):
        await coordinator.submit_for_approval(
            tenant_id=TENANT,
            user_id=OTHER_USER,
            run=_run(),
            total_net=Decimal("8000.00"),
        )

    assert approver.calls == []
    assert repo.instances == []


# ------------------------------------------------------- coordinator: auto-approve


async def test_below_threshold_auto_approves_and_transitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeInstanceRepo()
    repo.permission_members = {ERP_PAYROLL_APPROVE: [APPROVER]}
    coordinator, approver, inst_repo = _make_coordinator(
        flag_enabled=True,
        definition_doc=_definition_doc(),
        inst_repo=repo,
        monkeypatch=monkeypatch,
    )

    result = await coordinator.submit_for_approval(
        tenant_id=TENANT,
        user_id=OTHER_USER,
        run=_run(amount="8000.00"),
        total_net=Decimal("8000.00"),
    )

    # System actor approval: no human id.
    assert result.status == "approved"
    assert len(approver.calls) == 1
    assert approver.calls[0]["approved_by"] is None
    assert approver.calls[0]["actor_user_id"] is None
    assert approver.calls[0]["run_id"] == RUN_ID

    instance = inst_repo.instances[0]
    assert instance.status == "auto_approved"
    states = [t["new_state"] for t in inst_repo.transitions]
    assert states == ["submitted", "auto_approved"]


# ------------------------------------------------------ coordinator: human queue


async def test_over_threshold_waits_in_human_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeInstanceRepo()
    repo.permission_members = {ERP_PAYROLL_APPROVE: [APPROVER]}
    suggestions = FakeSuggestionService(
        suggestion=ApprovalRoutingSuggestion(
            recommendation="approve",
            confidence=Decimal("0.90"),
            reasoning="Fits the payroll desk.",
            model_used="gpt-4.1",
            suggested_approver_id=APPROVER,
        )
    )
    coordinator, approver, inst_repo = _make_coordinator(
        flag_enabled=True,
        definition_doc=_definition_doc(),
        inst_repo=repo,
        suggestion_service=suggestions,
        ai_client=object(),
        monkeypatch=monkeypatch,
    )

    run = _run(amount="12000.00")
    result = await coordinator.submit_for_approval(
        tenant_id=TENANT,
        user_id=OTHER_USER,
        run=run,
        total_net=Decimal("12000.00"),
    )

    # Run stays COMPUTED; the APPROVED transition is deferred to the human decision.
    assert result is run
    assert result.status == PayrollRunStatus.COMPUTED
    assert approver.calls == []
    instance = inst_repo.instances[0]
    assert instance.status == "pending"
    assert instance.current_step_index == 0

    # Advisory AI suggestion fired with the validated eligible set.
    assert len(suggestions.calls) == 1
    call = suggestions.calls[0]
    assert call["allowed_approver_ids"] == {APPROVER}
    assert call["description"] == "payroll run RN-2026-09"
    assert call["tenant_id"] == TENANT
    assert call["amount"] == Decimal("12000.00")


async def test_human_queue_ai_failure_does_not_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeInstanceRepo()
    repo.permission_members = {ERP_PAYROLL_APPROVE: [APPROVER]}
    suggestions = FakeSuggestionService(suggestion=None)
    coordinator, approver, inst_repo = _make_coordinator(
        flag_enabled=True,
        definition_doc=_definition_doc(),
        inst_repo=repo,
        suggestion_service=suggestions,
        ai_client=object(),
        monkeypatch=monkeypatch,
    )

    run = _run(amount="12000.00")
    result = await coordinator.submit_for_approval(
        tenant_id=TENANT,
        user_id=OTHER_USER,
        run=run,
        total_net=Decimal("12000.00"),
    )

    assert result is run
    assert result.status == PayrollRunStatus.COMPUTED
    assert approver.calls == []
    assert inst_repo.instances[0].status == "pending"


async def test_deterministic_step_never_asks_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeInstanceRepo()
    repo.permission_members = {ERP_PAYROLL_APPROVE: [APPROVER]}
    suggestions = FakeSuggestionService(suggestion=None)
    coordinator, approver, inst_repo = _make_coordinator(
        flag_enabled=True,
        definition_doc=_definition_doc(routing=RoutingStrategy.DETERMINISTIC),
        inst_repo=repo,
        suggestion_service=suggestions,
        ai_client=object(),
        monkeypatch=monkeypatch,
    )

    run = _run(amount="12000.00")
    result = await coordinator.submit_for_approval(
        tenant_id=TENANT,
        user_id=OTHER_USER,
        run=run,
        total_net=Decimal("12000.00"),
    )

    assert result is run
    assert suggestions.calls == []
    assert approver.calls == []
    assert inst_repo.instances[0].status == "pending"


# ------------------------------------------------- PayrollService seam (SKY-92)


class FakeApprovalPort:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def submit_for_approval(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        run: ent.PayrollRun,
        total_net: Decimal,
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.PayrollRun:
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "run": run,
                "total_net": total_net,
                "actor_user_id": actor_user_id,
            }
        )
        return run


def _service(repo: FakePayrollRepo) -> PayrollService:
    return PayrollService(
        repository=repo,  # type: ignore[arg-type]
        leave_ledger=FakeLeaveLedger(),  # type: ignore[arg-type]
        audit=AuditService(FakeAuditRepository()),  # type: ignore[arg-type]
    )


async def test_approve_run_routes_through_approval_seam() -> None:
    repo = FakePayrollRepo(run=_run(amount="12000.00"))
    port = FakeApprovalPort()
    service = _service(repo)
    service.attach_approval(port)  # type: ignore[arg-type]

    result = await service.approve_run(
        run_id=RUN_ID, tenant_id=TENANT, approved_by=OTHER_USER, actor_user_id=OTHER_USER
    )

    # Gates still ran, then the workflow port owns routing; the direct
    # transition is skipped.
    assert result is repo.run
    assert len(port.calls) == 1
    assert port.calls[0]["total_net"] == Decimal("12000.00")
    assert port.calls[0]["run"] is repo.run
    assert port.calls[0]["actor_user_id"] == OTHER_USER
    assert repo.transition_calls == []


async def test_approve_run_without_approval_transitions_directly(monkeypatch) -> None:
    from core.features.payroll import service as payroll_service_module

    captured: dict[str, object] = {}

    async def _capture_approved(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(payroll_service_module, "emit_run_approved", _capture_approved)

    repo = FakePayrollRepo(run=_run(amount="8000.00"))
    service = _service(repo)

    result = await service.approve_run(
        run_id=RUN_ID, tenant_id=TENANT, approved_by=OTHER_USER, actor_user_id=OTHER_USER
    )

    assert result.status == PayrollRunStatus.APPROVED
    assert len(repo.transition_calls) == 1
    assert repo.transition_calls[0]["approved_by"] == OTHER_USER
    assert captured["run_id"] == RUN_ID
