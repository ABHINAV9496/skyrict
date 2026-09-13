"""Unit tests for SKY-92: finance journal-entry approval routing.

Covers :class:`JournalEntryApprovalCoordinator` and the
``FinanceService.post_journal_entry`` seam:

- flag OFF => the existing direct-posting path runs unchanged (no workflow
  instance is ever created);
- flag ON + no active definition => ``ApprovalDefinitionMissingError`` and the
  entry NEVER posts (no silent fallback direct post);
- below-threshold amounts auto-approve (system actor) and post immediately;
- at-or-above-threshold amounts land on the human queue and the entry is
  returned still DRAFT - posting happens only on a later human decision;
- AI routing is advisory, only on an AI-assisted step, and the eligible
  approver set is passed for validation; an AI failure never blocks the entry.

The engine's own decision/escalation behavior is covered by the approval
workflow engine suite; these tests exercise the finance-side orchestration
with fake repositories (the repo fake-session convention).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pytest import mark

from core.core.exceptions import ApprovalDefinitionMissingError
from core.core.permissions import ERP_FINANCE_APPROVE
from core.domain.entities import JournalEntry, JournalLine
from core.domain.value_objects import EntryStatus
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
from core.features.finance.approval import (
    RESOURCE_TYPE,
    JournalEntryApprovalCoordinator,
)
from core.features.finance.service import FinanceService

pytestmark = mark.unit

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
ENTRY_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
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


class FakePoster:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def complete_posting(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None,
        entry_id: uuid.UUID,
        posted_at: datetime,
    ) -> SimpleNamespace:
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "entry_id": entry_id,
                "posted_at": posted_at,
            }
        )
        return SimpleNamespace(id=entry_id, tenant_id=tenant_id, status="posted")


# ------------------------------------------------------------------- helpers


def _definition_doc(*, routing: RoutingStrategy = RoutingStrategy.AI_ASSISTED) -> dict:
    return WorkflowDefinition(
        name="Journal entry approval",
        resource_type=RESOURCE_TYPE,
        version=1,
        steps=[
            WorkflowStep(
                key="finance_approval",
                assignee=PermissionAssignee(permission=ERP_FINANCE_APPROVE),
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
) -> tuple[JournalEntryApprovalCoordinator, FakePoster, FakeInstanceRepo]:
    session = _FakeSession()
    poster = FakePoster()
    repo = inst_repo or FakeInstanceRepo()
    coordinator = JournalEntryApprovalCoordinator(
        db=session,  # type: ignore[arg-type]
        definitions=FakeDefinitionStore(definition_doc),  # type: ignore[arg-type]
        instances=repo,  # type: ignore[arg-type]
        delegations=ApprovalDelegationRepository(session),  # type: ignore[arg-type]
        now=lambda: FIXED_NOW,
        ai_client=ai_client,  # type: ignore[arg-type]
        ai_authorization=None,
        ai_tenant_slug="acme-inc",
        post_verified=poster.complete_posting,
        suggestion_service=suggestion_service,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        "core.features.finance.approval.je_approval_engine_enabled",
        _flag(flag_enabled),
    )
    return coordinator, poster, repo


def _flag(enabled: bool):
    async def _impl(session: object, tenant_id: uuid.UUID) -> bool:
        return enabled

    return _impl


def _entry(amount: str = "12000.00") -> JournalEntry:
    return JournalEntry(
        tenant_id=TENANT,
        entry_date=date(2026, 9, 13),
        memo="Credit memo for vendor ACME",
        status=EntryStatus.DRAFT,
        source="manual",
        source_ref=None,
        lines=(
            JournalLine(account_id=uuid.uuid4(), debit=Decimal(amount), credit=None),
            JournalLine(account_id=uuid.uuid4(), debit=None, credit=Decimal(amount)),
        ),
        id=ENTRY_ID,
    )


# ------------------------------------------------------- coordinator: flag OFF


async def test_flag_off_posts_directly_without_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator, poster, repo = _make_coordinator(
        flag_enabled=False, definition_doc=_definition_doc(), monkeypatch=monkeypatch
    )

    result = await coordinator.submit_for_posting(
        tenant_id=TENANT, user_id=OTHER_USER, entry=_entry(), debit_total=Decimal("8000.00")
    )

    assert result.status == "posted"
    assert len(poster.calls) == 1
    assert poster.calls[0]["user_id"] == OTHER_USER
    assert poster.calls[0]["posted_at"] == FIXED_NOW
    # The engine was never involved.
    assert repo.instances == []


# -------------------------------------------------- coordinator: missing def


async def test_flag_on_without_definition_raises_and_never_posts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator, poster, repo = _make_coordinator(
        flag_enabled=True, definition_doc=None, monkeypatch=monkeypatch
    )

    with pytest.raises(ApprovalDefinitionMissingError):
        await coordinator.submit_for_posting(
            tenant_id=TENANT, user_id=OTHER_USER, entry=_entry(), debit_total=Decimal("8000.00")
        )

    assert poster.calls == []
    assert repo.instances == []


# ------------------------------------------------------- coordinator: auto-approve


async def test_below_threshold_auto_approves_and_posts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeInstanceRepo()
    repo.permission_members = {ERP_FINANCE_APPROVE: [APPROVER]}
    coordinator, poster, inst_repo = _make_coordinator(
        flag_enabled=True,
        definition_doc=_definition_doc(),
        inst_repo=repo,
        monkeypatch=monkeypatch,
    )

    result = await coordinator.submit_for_posting(
        tenant_id=TENANT,
        user_id=OTHER_USER,
        entry=_entry(amount="8000.00"),
        debit_total=Decimal("8000.00"),
    )

    # System actor posting: no human id.
    assert result.status == "posted"
    assert len(poster.calls) == 1
    assert poster.calls[0]["user_id"] is None
    assert poster.calls[0]["entry_id"] == ENTRY_ID

    instance = inst_repo.instances[0]
    assert instance.status == "auto_approved"
    states = [t["new_state"] for t in inst_repo.transitions]
    assert states == ["submitted", "auto_approved"]


# ------------------------------------------------------ coordinator: human queue


async def test_over_threshold_waits_in_human_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeInstanceRepo()
    repo.permission_members = {ERP_FINANCE_APPROVE: [APPROVER]}
    suggestions = FakeSuggestionService(
        suggestion=ApprovalRoutingSuggestion(
            recommendation="approve",
            confidence=Decimal("0.90"),
            reasoning="Fits the approval desk.",
            model_used="gpt-4.1",
            suggested_approver_id=APPROVER,
        )
    )
    coordinator, poster, inst_repo = _make_coordinator(
        flag_enabled=True,
        definition_doc=_definition_doc(),
        inst_repo=repo,
        suggestion_service=suggestions,
        ai_client=object(),
        monkeypatch=monkeypatch,
    )

    entry = _entry(amount="12000.00")
    result = await coordinator.submit_for_posting(
        tenant_id=TENANT, user_id=OTHER_USER, entry=entry, debit_total=Decimal("12000.00")
    )

    # Entry stays DRAFT; posting is deferred to the human decision.
    assert result is entry
    assert result.status == EntryStatus.DRAFT
    assert poster.calls == []
    instance = inst_repo.instances[0]
    assert instance.status == "pending"
    assert instance.current_step_index == 0

    # Advisory AI suggestion fired with the validated eligible set.
    assert len(suggestions.calls) == 1
    call = suggestions.calls[0]
    assert call["allowed_approver_ids"] == {APPROVER}
    assert call["description"] == "journal entry Credit memo for vendor ACME"
    assert call["tenant_id"] == TENANT
    assert call["amount"] == Decimal("12000.00")


async def test_human_queue_ai_failure_does_not_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeInstanceRepo()
    repo.permission_members = {ERP_FINANCE_APPROVE: [APPROVER]}
    suggestions = FakeSuggestionService(suggestion=None)
    coordinator, poster, inst_repo = _make_coordinator(
        flag_enabled=True,
        definition_doc=_definition_doc(),
        inst_repo=repo,
        suggestion_service=suggestions,
        ai_client=object(),
        monkeypatch=monkeypatch,
    )

    entry = _entry(amount="12000.00")
    result = await coordinator.submit_for_posting(
        tenant_id=TENANT, user_id=OTHER_USER, entry=entry, debit_total=Decimal("12000.00")
    )

    assert result is entry
    assert result.status == EntryStatus.DRAFT
    assert poster.calls == []
    assert inst_repo.instances[0].status == "pending"


async def test_deterministic_step_never_asks_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeInstanceRepo()
    repo.permission_members = {ERP_FINANCE_APPROVE: [APPROVER]}
    suggestions = FakeSuggestionService(suggestion=None)
    coordinator, poster, inst_repo = _make_coordinator(
        flag_enabled=True,
        definition_doc=_definition_doc(routing=RoutingStrategy.DETERMINISTIC),
        inst_repo=repo,
        suggestion_service=suggestions,
        ai_client=object(),
        monkeypatch=monkeypatch,
    )

    entry = _entry(amount="12000.00")
    result = await coordinator.submit_for_posting(
        tenant_id=TENANT, user_id=OTHER_USER, entry=entry, debit_total=Decimal("12000.00")
    )

    assert result is entry
    assert suggestions.calls == []
    assert poster.calls == []
    assert inst_repo.instances[0].status == "pending"


# ------------------------------------------------- FinanceService seam (SKY-92)


class StubFinanceRepo:
    def __init__(self, entry: JournalEntry) -> None:
        self.entry = entry
        self.post_calls: list[dict] = []

    async def get_journal_entry(self, entry_id: uuid.UUID, tenant_id: uuid.UUID) -> JournalEntry:
        return self.entry

    async def is_period_closed(self, entry_date: date, tenant_id: uuid.UUID) -> bool:
        return False

    async def post_journal_entry(
        self, entry_id: uuid.UUID, tenant_id: uuid.UUID, **kw: object
    ) -> JournalEntry:
        self.post_calls.append({"entry_id": entry_id, "tenant_id": tenant_id, **kw})
        return self.entry


class RecordingSinks:
    def __init__(self) -> None:
        self.audit: list[dict] = []
        self.events: list[tuple] = []

    async def log(self, *, tenant_id, user_id, action, target, details, **kwargs) -> None:
        self.audit.append(
            {"tenant_id": tenant_id, "action": action, "target": target, "details": details}
        )

    def journal_entry_posted(self, *, entry_id, tenant_id, correlation_id) -> None:
        self.events.append((entry_id, tenant_id, correlation_id))


class DefaultCurrency:
    async def get_default_currency(self, tenant_id: uuid.UUID) -> str:
        return "USD"


class FakeApprovalPort:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def submit_for_posting(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        entry: JournalEntry,
        debit_total: Decimal,
    ) -> JournalEntry:
        self.calls.append(
            {"tenant_id": tenant_id, "user_id": user_id, "entry": entry, "debit_total": debit_total}
        )
        return entry


async def test_post_journal_entry_routes_through_approval_seam() -> None:
    entry = _entry(amount="12000.00")
    repo = StubFinanceRepo(entry)
    port = FakeApprovalPort()
    service = FinanceService(
        repo=repo,  # type: ignore[arg-type]
        audit=RecordingSinks(),
        events=RecordingSinks(),
        default_currency=DefaultCurrency(),
    )
    service.attach_approval(port)  # type: ignore[arg-type]

    result = await service.post_journal_entry(
        tenant_id=TENANT, user_id=OTHER_USER, entry_id=ENTRY_ID
    )

    # Gates still ran, then the workflow port owns routing; direct post skipped.
    assert result is entry
    assert len(port.calls) == 1
    assert port.calls[0]["debit_total"] == Decimal("12000.00")
    assert port.calls[0]["entry"] is entry
    assert repo.post_calls == []


async def test_post_journal_entry_without_approval_posts_directly() -> None:
    entry = _entry(amount="8000.00")
    repo = StubFinanceRepo(entry)
    service = FinanceService(
        repo=repo,  # type: ignore[arg-type]
        audit=RecordingSinks(),
        events=RecordingSinks(),
        default_currency=DefaultCurrency(),
    )

    result = await service.post_journal_entry(
        tenant_id=TENANT, user_id=OTHER_USER, entry_id=ENTRY_ID
    )

    assert len(repo.post_calls) == 1
    assert repo.post_calls[0]["posted_by_user_id"] == OTHER_USER
    assert result is entry
