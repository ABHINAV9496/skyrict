"""Unit tests for expense policy & claims (FIN-AUT-004, SKY-85 B16).

Covers policy upsert, claim submission evaluation (cap/receipt/advance blocks),
claim approval/rejection, and violation recording. Repository persistence
tested by integration suites.
"""

from __future__ import annotations

import uuid
from contextlib import suppress
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from core.core.audit_events import (
    FINANCE_EXPENSE_CLAIM_APPROVED,
    FINANCE_EXPENSE_CLAIM_REJECTED,
    FINANCE_EXPENSE_CLAIM_SUBMITTED,
    FINANCE_EXPENSE_POLICY_CREATED,
)
from core.domain.value_objects import (
    ExpenseClaimStatus,
    ExpenseViolationReason,
    ViolationOutcome,
)
from core.features.finance.expense_policy import FinanceExpensePolicyService
from skyrict_common.exceptions import ConflictError, NotFoundError, ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.domain.entities import ExpenseClaim, ExpensePolicy, ExpensePolicyViolation


class StubExpenseRepo:
    def __init__(self) -> None:
        self.policies: dict[str, ExpensePolicy] = {}
        self.claims: dict[uuid.UUID, ExpenseClaim] = {}
        self.violations: list[ExpensePolicyViolation] = []

    async def create_expense_policy(self, policy: ExpensePolicy) -> ExpensePolicy:
        pid = uuid.uuid4()
        stored = replace(policy, id=pid)
        self.policies[policy.category] = stored
        return stored

    async def get_expense_policy(self, category: str, tenant_id: uuid.UUID) -> ExpensePolicy | None:
        p = self.policies.get(category)
        return p if p is not None and p.tenant_id == tenant_id else None

    async def list_expense_policies(self, tenant_id: uuid.UUID) -> Sequence[ExpensePolicy]:
        return [p for p in self.policies.values() if p.tenant_id == tenant_id]

    async def update_expense_policy(self, policy: ExpensePolicy) -> ExpensePolicy | None:
        if policy.id is None:
            return None
        self.policies[policy.category] = policy
        return policy

    async def create_expense_claim(self, claim: ExpenseClaim) -> ExpenseClaim:
        cid = uuid.uuid4()
        stored = replace(claim, id=cid)
        self.claims[cid] = stored
        return stored

    async def get_expense_claim(
        self, claim_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ExpenseClaim | None:
        c = self.claims.get(claim_id)
        return c if c is not None and c.tenant_id == tenant_id else None

    async def list_expense_claims(
        self, tenant_id: uuid.UUID, *, status: str | None = None
    ) -> Sequence[ExpenseClaim]:
        values = [c for c in self.claims.values() if c.tenant_id == tenant_id]
        if status is not None:
            values = [c for c in values if c.status == status]
        return values

    async def set_expense_claim_status(
        self,
        claim_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        status: str,
        user_id: uuid.UUID | None = None,
        rejection_reason: str | None = None,
    ) -> ExpenseClaim | None:
        c = self.claims.get(claim_id)
        if c is None or c.tenant_id != tenant_id:
            return None
        updated = replace(c, status=status, approved_by=user_id, rejection_reason=rejection_reason)
        self.claims[claim_id] = updated
        return updated

    async def create_expense_violation(
        self, violation: ExpensePolicyViolation
    ) -> ExpensePolicyViolation:
        vid = uuid.uuid4()
        stored = replace(violation, id=vid)
        self.violations.append(stored)
        return stored

    async def list_expense_violations(
        self, tenant_id: uuid.UUID, *, reason_code: str | None = None
    ) -> Sequence[ExpensePolicyViolation]:
        values = [v for v in self.violations if v.tenant_id == tenant_id]
        if reason_code is not None:
            values = [v for v in values if v.reason_code == reason_code]
        return values


class RecordingAudit:
    def __init__(self) -> None:
        self.logs: list[dict[str, object]] = []

    async def log(self, **kwargs: object) -> None:
        self.logs.append(kwargs)


TENANT = uuid.uuid4()
USER = uuid.uuid4()


def _fresh() -> tuple[StubExpenseRepo, RecordingAudit, FinanceExpensePolicyService]:
    repo = StubExpenseRepo()
    audit = RecordingAudit()
    return repo, audit, FinanceExpensePolicyService(repo=repo, audit=audit)


def _policy_body(category: str = "travel", **overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "category": category,
        "name": "Travel policy",
        "cap_amount": Decimal("500"),
        "requires_receipt": True,
        "advance_limit": Decimal("200"),
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _claim_body(category: str = "travel", **overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "category": category,
        "amount": Decimal("300"),
        "description": "Flight",
        "receipt_url": "https://example.com/receipt.pdf",
        "advance_amount": Decimal("100"),
        "source_ref": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


# --- Policy CRUD ---


async def test_upsert_creates_new_policy() -> None:
    _repo, audit, svc = _fresh()
    policy = await svc.upsert_policy(TENANT, USER, "travel", _policy_body())
    assert policy.id is not None
    assert policy.category == "travel"
    assert audit.logs[-1]["action"] == FINANCE_EXPENSE_POLICY_CREATED


async def test_upsert_updates_existing_policy() -> None:
    _repo, audit, svc = _fresh()
    await svc.upsert_policy(TENANT, USER, "travel", _policy_body(cap_amount=Decimal("500")))
    updated = await svc.upsert_policy(
        TENANT,
        USER,
        "travel",
        SimpleNamespace(
            name="Updated", cap_amount=Decimal("800"), requires_receipt=None, advance_limit=None
        ),
    )
    assert updated.cap_amount == Decimal("800")
    assert updated.requires_receipt is True  # unchanged (None = keep)
    assert any(log["action"] == "finance.expense_policy.updated" for log in audit.logs)


async def test_get_policy_not_found() -> None:
    _, _, svc = _fresh()
    with pytest.raises(NotFoundError):
        await svc.get_policy(TENANT, "nonexistent")


# --- Claim submission ---


async def test_submit_claim_approved_within_policy() -> None:
    _repo, audit, svc = _fresh()
    await svc.upsert_policy(TENANT, USER, "travel", _policy_body())
    result = await svc.submit_claim(TENANT, USER, _claim_body())
    assert result.decision == "approved"
    assert result.claim.id is not None
    assert result.claim.status == ExpenseClaimStatus.SUBMITTED
    assert audit.logs[-1]["action"] == FINANCE_EXPENSE_CLAIM_SUBMITTED


async def test_submit_claim_no_policy_also_approved() -> None:
    _, _, svc = _fresh()
    result = await svc.submit_claim(TENANT, USER, _claim_body())
    assert result.decision == "approved"


async def test_submit_claim_blocked_by_cap() -> None:
    repo, _audit, svc = _fresh()
    await svc.upsert_policy(TENANT, USER, "travel", _policy_body(cap_amount=Decimal("500")))
    with pytest.raises(ConflictError, match="exceeds the cap"):
        await svc.submit_claim(TENANT, USER, _claim_body(amount=Decimal("600")))
    assert len(repo.violations) == 1
    assert repo.violations[0].reason_code == ExpenseViolationReason.CATEGORY_CAP_EXCEEDED
    assert repo.violations[0].outcome == ViolationOutcome.BLOCKED


async def test_submit_claim_blocked_by_receipt_required() -> None:
    repo, _, svc = _fresh()
    await svc.upsert_policy(TENANT, USER, "travel", _policy_body())
    with pytest.raises(ConflictError, match="requires a receipt"):
        await svc.submit_claim(TENANT, USER, _claim_body(receipt_url=None))
    assert repo.violations[0].reason_code == ExpenseViolationReason.RECEIPT_REQUIRED


async def test_submit_claim_blocked_by_advance_limit() -> None:
    repo, _, svc = _fresh()
    await svc.upsert_policy(TENANT, USER, "travel", _policy_body())
    with pytest.raises(ConflictError, match="exceeds the limit"):
        await svc.submit_claim(TENANT, USER, _claim_body(advance_amount=Decimal("300")))
    assert repo.violations[0].reason_code == ExpenseViolationReason.ADVANCE_LIMIT_EXCEEDED


# --- Claim approval/rejection ---


async def test_approve_claim() -> None:
    _repo, audit, svc = _fresh()
    await svc.upsert_policy(TENANT, USER, "travel", _policy_body())
    result = await svc.submit_claim(TENANT, USER, _claim_body())
    claim = await svc.decide_claim(TENANT, USER, result.claim.id, approve=True)
    assert claim.status == ExpenseClaimStatus.APPROVED
    assert audit.logs[-1]["action"] == FINANCE_EXPENSE_CLAIM_APPROVED


async def test_reject_claim() -> None:
    _repo, audit, svc = _fresh()
    await svc.upsert_policy(TENANT, USER, "travel", _policy_body())
    result = await svc.submit_claim(TENANT, USER, _claim_body())
    claim = await svc.decide_claim(
        TENANT, USER, result.claim.id, approve=False, rejection_reason="Too expensive"
    )
    assert claim.status == ExpenseClaimStatus.REJECTED
    assert claim.rejection_reason == "Too expensive"
    assert audit.logs[-1]["action"] == FINANCE_EXPENSE_CLAIM_REJECTED


async def test_reject_claim_requires_reason() -> None:
    _repo, _, svc = _fresh()
    await svc.upsert_policy(TENANT, USER, "travel", _policy_body())
    result = await svc.submit_claim(TENANT, USER, _claim_body())
    with pytest.raises(ValidationError, match="requires a rejection_reason"):
        await svc.decide_claim(TENANT, USER, result.claim.id, approve=False)


async def test_decide_rejects_non_submitted_claim() -> None:
    _repo, _, svc = _fresh()
    await svc.upsert_policy(TENANT, USER, "travel", _policy_body())
    result = await svc.submit_claim(TENANT, USER, _claim_body())
    await svc.decide_claim(TENANT, USER, result.claim.id, approve=True)
    with pytest.raises(ValidationError, match="Cannot decide"):
        await svc.decide_claim(TENANT, USER, result.claim.id, approve=True)


# --- Violations ---


async def test_list_violations_filters_by_reason() -> None:
    _repo, _, svc = _fresh()
    await svc.upsert_policy(TENANT, USER, "travel", _policy_body())
    with suppress(ConflictError):
        await svc.submit_claim(TENANT, USER, _claim_body(amount=Decimal("600")))
    with suppress(ConflictError):
        await svc.submit_claim(TENANT, USER, _claim_body(receipt_url=None))
    all_v = await svc.list_violations(TENANT, None)
    assert len(all_v) == 2
    cap_only = await svc.list_violations(TENANT, "category_cap_exceeded")
    assert len(cap_only) == 1
