"""Finance expense policy & claims (FIN-AUT-004, SKY-85 B16).

Thin service + router for per-category expense policies, claim submission,
approval/rejection, and the persisted violation ledger.

Evaluation (per claim, against the matching category policy or the DEFAULT
row when present):

- ``cap_amount`` exceeded -> **blocked** (409, no claim row created)
- ``requires_receipt`` and no ``receipt_url`` -> **blocked**
- ``advance_amount`` > ``advance_limit`` -> **blocked**

Every failed evaluation writes an ``erp_expense_policy_violations`` row so
reporting can group by ``reason_code``. Reads use ``erp.expense.read``; writes
use ``erp.expense.write``; approval/rejection use ``erp.expense.approve``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query

from core.api.deps import (
    get_finance_expense_policy_service,
    require_permission,
)
from core.core.audit_events import (
    FINANCE_EXPENSE_CLAIM_APPROVED,
    FINANCE_EXPENSE_CLAIM_REJECTED,
    FINANCE_EXPENSE_CLAIM_SUBMITTED,
    FINANCE_EXPENSE_POLICY_CREATED,
    FINANCE_EXPENSE_POLICY_UPDATED,
    FINANCE_EXPENSE_VIOLATION_RECORDED,
)
from core.domain.entities import (
    ExpenseClaim,
    ExpensePolicy,
    ExpensePolicyViolation,
)
from core.domain.value_objects import (
    ExpenseClaimStatus,
    ExpenseViolationReason,
    ViolationOutcome,
)
from core.features.finance.ports import AuditSink, FinanceWave4RepositoryPort
from core.features.finance.schemas_wave5 import (
    ExpenseClaimRequest,
    ExpenseClaimResponse,
    ExpenseEvaluationResponse,
    ExpensePolicyRequest,
    ExpensePolicyResponse,
    ExpensePolicyUpdateRequest,
    ExpenseViolationResponse,
)
from skyrict_common.exceptions import ConflictError, NotFoundError, ValidationError
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/finance/expenses", tags=["finance-expenses"])

require_expense_read = require_permission("erp.expense.read")
require_expense_write = require_permission("erp.expense.write")
require_expense_approve = require_permission("erp.expense.approve")

DEFAULT_POLICY_CATEGORY = "DEFAULT"


def _tenant_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["tenant_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _user_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["user_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


class FinanceExpensePolicyService:
    """Expense policy evaluation + claim lifecycle (thin over the repo)."""

    def __init__(self, repo: FinanceWave4RepositoryPort, audit: AuditSink) -> None:
        self._repo = repo
        self._audit = audit

    # -- Policies -----------------------------------------------------------

    async def upsert_policy(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, category: str, body: Any
    ) -> ExpensePolicy:
        existing = await self._repo.get_expense_policy(category, tenant_id)
        if existing is None:
            created = await self._repo.create_expense_policy(
                ExpensePolicy(
                    tenant_id=tenant_id,
                    category=category,
                    name=body.name,
                    cap_amount=(Decimal(body.cap_amount) if body.cap_amount is not None else None),
                    requires_receipt=bool(body.requires_receipt),
                    advance_limit=(
                        Decimal(body.advance_limit) if body.advance_limit is not None else None
                    ),
                    created_by=user_id,
                )
            )
            await self._audit.log(
                tenant_id=tenant_id,
                user_id=user_id,
                action=FINANCE_EXPENSE_POLICY_CREATED,
                target=f"expense_policy:{created.id}",
                details={"category": created.category},
            )
            return created
        updated = replace(
            existing,
            name=body.name if body.name is not None else existing.name,
            cap_amount=(
                Decimal(body.cap_amount) if body.cap_amount is not None else existing.cap_amount
            ),
            requires_receipt=(
                body.requires_receipt
                if body.requires_receipt is not None
                else existing.requires_receipt
            ),
            advance_limit=(
                Decimal(body.advance_limit)
                if body.advance_limit is not None
                else existing.advance_limit
            ),
        )
        result = await self._repo.update_expense_policy(updated)
        if result is None:
            raise NotFoundError(f"Expense policy for category '{category}' not found")
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_EXPENSE_POLICY_UPDATED,
            target=f"expense_policy:{result.id}",
            details={"category": result.category},
        )
        return result

    async def list_policies(self, tenant_id: uuid.UUID) -> list[ExpensePolicy]:
        return list(await self._repo.list_expense_policies(tenant_id))

    async def get_policy(self, tenant_id: uuid.UUID, category: str) -> ExpensePolicy:
        policy = await self._repo.get_expense_policy(category, tenant_id)
        if policy is None:
            raise NotFoundError(f"Expense policy for category '{category}' not found")
        return policy

    # -- Claims -------------------------------------------------------------

    async def _record_violation(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        category: str,
        reason: ExpenseViolationReason,
        outcome: ViolationOutcome,
        amount: Decimal,
        claim_id: uuid.UUID | None,
        message: str,
    ) -> None:
        created = await self._repo.create_expense_violation(
            ExpensePolicyViolation(
                tenant_id=tenant_id,
                category=category,
                reason_code=reason,
                outcome=outcome,
                amount=amount,
                claim_id=claim_id,
                submitted_by=user_id,
                message=message,
            )
        )
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_EXPENSE_VIOLATION_RECORDED,
            target=f"expense_violation:{created.id}",
            details={
                "category": category,
                "reason_code": reason,
                "outcome": outcome,
                "amount": str(amount),
            },
        )

    def _policy_for(self, policies: Sequence[ExpensePolicy], category: str) -> ExpensePolicy | None:
        for policy in policies:
            if policy.category == category:
                return policy
        for policy in policies:
            if policy.category == DEFAULT_POLICY_CATEGORY:
                return policy
        return None

    async def submit_claim(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, body: Any
    ) -> ExpenseEvaluationResponse:
        amount = Decimal(body.amount)
        category = str(body.category)
        advance = Decimal(body.advance_amount) if body.advance_amount is not None else Decimal("0")
        policy = self._policy_for(await self._repo.list_expense_policies(tenant_id), category)

        if policy is not None:
            if policy.cap_amount is not None and amount > policy.cap_amount:
                await self._record_violation(
                    tenant_id,
                    user_id,
                    category=category,
                    reason=ExpenseViolationReason.CATEGORY_CAP_EXCEEDED,
                    outcome=ViolationOutcome.BLOCKED,
                    amount=amount,
                    claim_id=None,
                    message=(
                        f"Amount {amount} exceeds category cap {policy.cap_amount} for '{category}'"
                    ),
                )
                raise ConflictError(
                    f"Expense amount {amount} exceeds the cap for category '{category}'"
                )
            if policy.requires_receipt and not body.receipt_url:
                await self._record_violation(
                    tenant_id,
                    user_id,
                    category=category,
                    reason=ExpenseViolationReason.RECEIPT_REQUIRED,
                    outcome=ViolationOutcome.BLOCKED,
                    amount=amount,
                    claim_id=None,
                    message=f"Category '{category}' requires a receipt",
                )
                raise ConflictError(f"Category '{category}' requires a receipt")
            if policy.advance_limit is not None and advance > policy.advance_limit:
                await self._record_violation(
                    tenant_id,
                    user_id,
                    category=category,
                    reason=ExpenseViolationReason.ADVANCE_LIMIT_EXCEEDED,
                    outcome=ViolationOutcome.BLOCKED,
                    amount=amount,
                    claim_id=None,
                    message=(
                        f"Advance {advance} exceeds the limit {policy.advance_limit} "
                        f"for '{category}'"
                    ),
                )
                raise ConflictError(
                    f"Advance {advance} exceeds the limit for category '{category}'"
                )

        claim = await self._repo.create_expense_claim(
            ExpenseClaim(
                tenant_id=tenant_id,
                category=category,
                amount=amount,
                description=body.description,
                receipt_url=body.receipt_url,
                advance_amount=body.advance_amount,
                source_ref=body.source_ref,
                submitted_by=user_id,
            )
        )
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_EXPENSE_CLAIM_SUBMITTED,
            target=f"expense_claim:{claim.id}",
            details={"category": category, "amount": str(amount)},
        )
        return ExpenseEvaluationResponse(
            claim=ExpenseClaimResponse.model_validate(claim),
            decision="approved",
        )

    async def list_claims(self, tenant_id: uuid.UUID, status: str | None) -> list[ExpenseClaim]:
        return list(await self._repo.list_expense_claims(tenant_id, status=status))

    async def get_claim(self, tenant_id: uuid.UUID, claim_id: uuid.UUID) -> ExpenseClaim:
        claim = await self._repo.get_expense_claim(claim_id, tenant_id)
        if claim is None:
            raise NotFoundError(f"Expense claim {claim_id} not found")
        return claim

    async def decide_claim(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        claim_id: uuid.UUID,
        *,
        approve: bool,
        rejection_reason: str | None = None,
    ) -> ExpenseClaim:
        current = await self.get_claim(tenant_id, claim_id)
        if current.status is not ExpenseClaimStatus.SUBMITTED:
            raise ValidationError(f"Cannot decide a claim in state '{current.status}'")
        if not approve and not rejection_reason:
            raise ValidationError("Rejecting a claim requires a rejection_reason")
        status = ExpenseClaimStatus.APPROVED if approve else ExpenseClaimStatus.REJECTED
        updated = await self._repo.set_expense_claim_status(
            claim_id,
            tenant_id,
            status=status,
            user_id=user_id,
            rejection_reason=rejection_reason,
        )
        if updated is None:
            raise NotFoundError(f"Expense claim {claim_id} not found")
        action = FINANCE_EXPENSE_CLAIM_APPROVED if approve else FINANCE_EXPENSE_CLAIM_REJECTED
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            target=f"expense_claim:{claim_id}",
            details={
                "category": updated.category,
                "amount": str(updated.amount),
                "rejection_reason": rejection_reason,
            },
        )
        return updated

    # -- Violations ---------------------------------------------------------

    async def list_violations(
        self, tenant_id: uuid.UUID, reason_code: str | None
    ) -> list[ExpensePolicyViolation]:
        return list(await self._repo.list_expense_violations(tenant_id, reason_code=reason_code))


@router.post("/policies", response_model=ResponseEnvelope[ExpensePolicyResponse])
async def upsert_expense_policy(
    body: ExpensePolicyRequest,
    current_user: dict[str, Any] = Depends(require_expense_write),
    svc: FinanceExpensePolicyService = Depends(get_finance_expense_policy_service),
) -> ResponseEnvelope[ExpensePolicyResponse]:
    policy = await svc.upsert_policy(
        _tenant_id(current_user), _user_id(current_user), body.category, body
    )
    return ResponseEnvelope(data=ExpensePolicyResponse.model_validate(policy))


@router.get("/policies", response_model=ResponseEnvelope[list[ExpensePolicyResponse]])
async def list_expense_policies(
    current_user: dict[str, Any] = Depends(require_expense_read),
    svc: FinanceExpensePolicyService = Depends(get_finance_expense_policy_service),
) -> ResponseEnvelope[list[ExpensePolicyResponse]]:
    policies = await svc.list_policies(_tenant_id(current_user))
    return ResponseEnvelope(data=[ExpensePolicyResponse.model_validate(p) for p in policies])


@router.get("/policies/{category}", response_model=ResponseEnvelope[ExpensePolicyResponse])
async def get_expense_policy(
    category: str,
    current_user: dict[str, Any] = Depends(require_expense_read),
    svc: FinanceExpensePolicyService = Depends(get_finance_expense_policy_service),
) -> ResponseEnvelope[ExpensePolicyResponse]:
    policy = await svc.get_policy(_tenant_id(current_user), category)
    return ResponseEnvelope(data=ExpensePolicyResponse.model_validate(policy))


@router.put("/policies/{category}", response_model=ResponseEnvelope[ExpensePolicyResponse])
async def update_expense_policy(
    category: str,
    body: ExpensePolicyUpdateRequest,
    current_user: dict[str, Any] = Depends(require_expense_write),
    svc: FinanceExpensePolicyService = Depends(get_finance_expense_policy_service),
) -> ResponseEnvelope[ExpensePolicyResponse]:
    policy = await svc.upsert_policy(
        _tenant_id(current_user), _user_id(current_user), category, body
    )
    return ResponseEnvelope(data=ExpensePolicyResponse.model_validate(policy))


@router.post("/claims", response_model=ResponseEnvelope[ExpenseEvaluationResponse])
async def submit_expense_claim(
    body: ExpenseClaimRequest,
    current_user: dict[str, Any] = Depends(require_expense_write),
    svc: FinanceExpensePolicyService = Depends(get_finance_expense_policy_service),
) -> ResponseEnvelope[ExpenseEvaluationResponse]:
    result = await svc.submit_claim(_tenant_id(current_user), _user_id(current_user), body)
    return ResponseEnvelope(data=result)


@router.get("/claims", response_model=ResponseEnvelope[list[ExpenseClaimResponse]])
async def list_expense_claims(
    status: str | None = Query(default=None),
    current_user: dict[str, Any] = Depends(require_expense_read),
    svc: FinanceExpensePolicyService = Depends(get_finance_expense_policy_service),
) -> ResponseEnvelope[list[ExpenseClaimResponse]]:
    claims = await svc.list_claims(_tenant_id(current_user), status)
    return ResponseEnvelope(data=[ExpenseClaimResponse.model_validate(c) for c in claims])


@router.get("/claims/{claim_id}", response_model=ResponseEnvelope[ExpenseClaimResponse])
async def get_expense_claim(
    claim_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_expense_read),
    svc: FinanceExpensePolicyService = Depends(get_finance_expense_policy_service),
) -> ResponseEnvelope[ExpenseClaimResponse]:
    claim = await svc.get_claim(_tenant_id(current_user), claim_id)
    return ResponseEnvelope(data=ExpenseClaimResponse.model_validate(claim))


@router.post("/claims/{claim_id}/approve", response_model=ResponseEnvelope[ExpenseClaimResponse])
async def approve_expense_claim(
    claim_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_expense_approve),
    svc: FinanceExpensePolicyService = Depends(get_finance_expense_policy_service),
) -> ResponseEnvelope[ExpenseClaimResponse]:
    claim = await svc.decide_claim(
        _tenant_id(current_user), _user_id(current_user), claim_id, approve=True
    )
    return ResponseEnvelope(data=ExpenseClaimResponse.model_validate(claim))


@router.post("/claims/{claim_id}/reject", response_model=ResponseEnvelope[ExpenseClaimResponse])
async def reject_expense_claim(
    claim_id: uuid.UUID,
    rejection_reason: str = Query(..., min_length=1, max_length=500),
    current_user: dict[str, Any] = Depends(require_expense_approve),
    svc: FinanceExpensePolicyService = Depends(get_finance_expense_policy_service),
) -> ResponseEnvelope[ExpenseClaimResponse]:
    claim = await svc.decide_claim(
        _tenant_id(current_user),
        _user_id(current_user),
        claim_id,
        approve=False,
        rejection_reason=rejection_reason,
    )
    return ResponseEnvelope(data=ExpenseClaimResponse.model_validate(claim))


@router.get("/violations", response_model=ResponseEnvelope[list[ExpenseViolationResponse]])
async def list_expense_violations(
    reason_code: str | None = Query(default=None),
    current_user: dict[str, Any] = Depends(require_expense_read),
    svc: FinanceExpensePolicyService = Depends(get_finance_expense_policy_service),
) -> ResponseEnvelope[list[ExpenseViolationResponse]]:
    violations = await svc.list_violations(_tenant_id(current_user), reason_code)
    return ResponseEnvelope(data=[ExpenseViolationResponse.model_validate(v) for v in violations])
