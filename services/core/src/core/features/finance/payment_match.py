"""Finance automation wave 3 - payment-matching inbox (FIN-AUT-003 B7).

Unmatched cash receipts (bank feed, manual entry, or a B23 document-extracted
vendor reference) land in ``erp_payment_intents`` and wait for a human.

The deterministic scorer (:func:`score_match`) ranks APPROVED invoices against
each receipt by weighted signals - amount affinity to the outstanding balance
(0.5), the receipt's customer hint (0.3), and an invoice-number reference in
the receipt text (0.2) - with weights renormalized over the signals actually
present. The best score is recorded at create time (so the inbox can sort by
confidence) and candidates are recomputed LIVE at inbox-read (so outstanding
balances never go stale).

Accepting reuses the existing ``apply_payment`` path (validation, AR/Cash
posting, paid-on-zero, ``FINANCE_PAYMENT_APPLIED`` audit) and just stamps the
intent with the payment it created. Undo deletes exactly that payment row,
recomputes the invoice's paid state from the remaining payments, and reopens
the intent - but only within a 15-minute window, matching the audit "mistake
recovery" posture used elsewhere in finance. Dismissal closes an intent
without moving money; it is reversible in the sense that a brand-new push
re-registers it.

Reads use ``erp.finance.read``; all mutations use ``erp.finance.write``.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query

from core.api.deps import get_finance_wave4_service, require_permission
from core.core.audit_events import (
    FINANCE_PAYMENT_INTENT_REGISTERED,
    FINANCE_PAYMENT_MATCH_ACCEPTED,
    FINANCE_PAYMENT_MATCH_DISMISSED,
    FINANCE_PAYMENT_MATCH_UNDONE,
)
from core.domain.entities import Invoice, PaymentIntent, PaymentMatchCandidate
from core.domain.value_objects import PaymentIntentStatus
from core.features.finance.ports import AuditSink, CustomerPort, PaymentMatchRepositoryPort
from core.features.finance.schemas_wave4 import (
    InvoiceSuggestionResponse,
    PaymentIntentCreateRequest,
    PaymentIntentResponse,
    PaymentMatchAcceptRequest,
    PaymentMatchBulkAcceptRequest,
    PaymentMatchBulkAcceptResponse,
    PaymentMatchBulkResult,
)
from core.features.finance.service import FinanceService
from skyrict_common.exceptions import ConflictError, NotFoundError
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/finance/payment-intents", tags=["finance-payment-intents"])

require_finance_read = require_permission("erp.finance.read")
require_finance_write = require_permission("erp.finance.write")

# ---------------------------------------------------------------------------
# Deterministic scoring (pure math - unit-testable, ran to Clerk-4).
# ---------------------------------------------------------------------------

SCORE_AUTO_BAR = Decimal("0.90")
SCORE_CANDIDATE_BAR = Decimal("0.70")
UNDO_WINDOW = timedelta(minutes=15)


def _amount_affinity(amount: Decimal, outstanding: Decimal) -> Decimal:
    """How well a receipt covers an invoice's remaining balance (0..1)."""
    if amount <= 0 or outstanding <= 0:
        return Decimal("0")
    return min(amount, outstanding) / max(amount, outstanding)


def score_match(
    amount: Decimal,
    customer_id: uuid.UUID | None,
    reference: str | None,
    invoice_number: str,
    invoice_customer_id: uuid.UUID | None,
    invoice_total: Decimal,
    outstanding: Decimal,
) -> Decimal:
    """Weighted match score (0..1) of a receipt against one APPROVED invoice.

    Signals, renormalized over the ones actually present: amount affinity (0.5),
    customer-hint equality (0.3), and an invoice-number reference inside the
    receipt text (0.2). Deterministic - no randomness, no thresholds baked in.
    """
    amount_signal = _amount_affinity(amount, outstanding)
    weighted = Decimal("0.5") * amount_signal
    weights = Decimal("0.5")

    if customer_id is not None:
        weighted += Decimal("0.3") * Decimal("1" if invoice_customer_id == customer_id else "0")
        weights += Decimal("0.3")

    has_number = bool(invoice_number)
    if reference and has_number:
        ref_hit = Decimal("1" if _invoice_number_in_reference(reference, invoice_number) else "0")
        weighted += Decimal("0.2") * ref_hit
        weights += Decimal("0.2")

    return (weighted / weights).quantize(Decimal("0.0001"))


def _invoice_number_in_reference(reference: str, invoice_number: str) -> bool:
    """Case-insensitive contains folded to [a-z0-9-] so 'INV-2026-0042' matches 'INV-2026-00042' loosely.

    Only digits/letters/hyphen survive folding; a receipt ref like
    "payment INV-2026-0042 thanks" would otherwise never equal the canonical
    invoice number.
    """
    fold_reference = re.sub(r"[^a-z0-9-]", "", reference.lower())
    fold_number = re.sub(r"[^a-z0-9-]", "", invoice_number.lower())
    return bool(fold_number) and fold_number in fold_reference


def _compute_candidates(
    amount: Decimal,
    customer_id: uuid.UUID | None,
    reference: str | None,
    pairs: Sequence[tuple[Invoice, Decimal]],
) -> tuple[PaymentMatchCandidate, ...]:
    """Rank APPROVED invoices against one receipt, keeping score >= 0.70.

    Ties (equal score) prefer the invoice that the amount covers most fully -
    an exact-match receipt should never sit behind a partial one.
    """
    out: list[PaymentMatchCandidate] = []
    for invoice, outstanding in pairs:
        if outstanding <= 0:
            continue
        if invoice.id is None:
            continue
        score = score_match(
            amount,
            customer_id,
            reference,
            invoice.invoice_number,
            invoice.customer_id,
            invoice.total,
            outstanding,
        )
        if score >= SCORE_CANDIDATE_BAR:
            out.append(
                PaymentMatchCandidate(
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    customer_id=invoice.customer_id,
                    customer_name=None,
                    outstanding=outstanding,
                    score=score,
                )
            )
    return tuple(sorted(out, key=lambda c: (c.score, -c.outstanding), reverse=True))


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@dataclass
class PaymentMatchService:
    """Business rules for the payment-matching inbox (thin over repo + finance)."""

    repo: PaymentMatchRepositoryPort
    finance: FinanceService
    audit: AuditSink
    customers: CustomerPort | None = None

    async def _suggested_invoice(self, intent: PaymentIntent) -> PaymentMatchCandidate | None:
        candidates = await self._score_for(intent)
        return candidates[0] if candidates else None

    async def _score_for(self, intent: PaymentIntent) -> tuple[PaymentMatchCandidate, ...]:
        pairs = await self.repo.outstanding_invoices(intent.tenant_id)
        return _compute_candidates(intent.amount, intent.customer_id, intent.reference, pairs)

    async def register(self, tenant_id: uuid.UUID, user_id: uuid.UUID, body: Any) -> PaymentIntent:
        """Queue an unmatched receipt; record its deterministic best match."""
        best = await self._score_for(
            PaymentIntent(
                tenant_id=tenant_id,
                amount=body.amount,
                paid_at=body.paid_at,
                method=body.method,
                reference=body.reference,
                source=body.source,
                source_ref=body.source_ref,
                customer_id=body.customer_id,
                created_by=user_id,
            )
        )
        intent = PaymentIntent(
            tenant_id=tenant_id,
            amount=body.amount,
            paid_at=body.paid_at,
            method=body.method,
            reference=body.reference,
            source=body.source,
            source_ref=body.source_ref,
            customer_id=body.customer_id,
            created_by=user_id,
            score=best[0].score if best else None,
            suggested_invoice_id=best[0].invoice_id if best else None,
            status=PaymentIntentStatus.CANDIDATE if best else PaymentIntentStatus.OPEN,
        )
        created = await self.repo.create_payment_intent(intent)
        assert created.id is not None
        await self.audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_PAYMENT_INTENT_REGISTERED,
            target=f"payment_intent:{created.id}",
            details={
                "amount": str(created.amount),
                "method": created.method,
                "reference": created.reference,
            },
        )
        return created

    async def list_inbox(
        self,
        tenant_id: uuid.UUID,
        *,
        status: PaymentIntentStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[tuple[PaymentIntent, tuple[PaymentMatchCandidate, ...], str | None]]:
        """Inbox page of ``(intent, live candidates, intent customer name)``.

        Without a status filter only the unresolved queue (open + candidate) is
        returned; applied/dismissed rows need an explicit filter. Candidates are
        recomputed in ONE repo query per page so outstanding stays fresh.
        """
        if status is not None:
            intents = list(
                await self.repo.list_payment_intents(
                    tenant_id, status=status, offset=offset, limit=limit
                )
            )
        else:
            opened = await self.repo.list_payment_intents(
                tenant_id, status=PaymentIntentStatus.OPEN, limit=limit
            )
            candidate = await self.repo.list_payment_intents(
                tenant_id, status=PaymentIntentStatus.CANDIDATE, limit=limit
            )
            merged = sorted(
                opened + candidate,
                key=lambda i: i.created_at or datetime.min.replace(tzinfo=UTC),
                reverse=True,
            )
            intents = merged[offset : offset + limit]

        pairs = await self.repo.outstanding_invoices(tenant_id)
        row: list[tuple[PaymentIntent, tuple[PaymentMatchCandidate, ...], str | None]] = []
        for intent in intents:
            candidates: tuple[PaymentMatchCandidate, ...] = ()
            if intent.status in (
                PaymentIntentStatus.OPEN,
                PaymentIntentStatus.CANDIDATE,
            ):
                candidates = _compute_candidates(
                    intent.amount, intent.customer_id, intent.reference, pairs
                )
            customer_name: str | None = None
            if self.customers is not None and intent.customer_id is not None:
                customer_name = await self.customers.get_customer_name(
                    intent.customer_id, tenant_id=tenant_id
                )
            row.append((intent, candidates, customer_name))
        return row

    async def get(self, tenant_id: uuid.UUID, intent_id: uuid.UUID) -> PaymentIntent:
        intent = await self.repo.get_payment_intent(intent_id, tenant_id)
        if intent is None:
            raise NotFoundError(f"Payment intent {intent_id} not found")
        return intent

    async def accept(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        intent_id: uuid.UUID,
        *,
        invoice_id: uuid.UUID,
    ) -> PaymentIntent:
        """Apply an unresolved receipt's money to an invoice (via apply_payment).

        The intent (not the payment UNIQUE stamp) is the idempotency guard: a
        resolved intent cannot be applied twice.
        """
        intent = await self.get(tenant_id, intent_id)
        if intent.status in (PaymentIntentStatus.APPLIED, PaymentIntentStatus.DISMISSED):
            raise ConflictError(f"Payment intent {intent_id} is already resolved")
        payment = await self.finance.apply_payment(
            tenant_id=tenant_id,
            user_id=user_id,
            invoice_id=invoice_id,
            amount=intent.amount,
            method=intent.method,
            paid_at=intent.paid_at,
        )
        assert payment.id is not None
        now = datetime.now(UTC)
        updated = await self.repo.update_payment_intent(
            replace(
                intent,
                status=PaymentIntentStatus.APPLIED,
                applied_invoice_id=invoice_id,
                applied_payment_id=payment.id,
                applied_at=now,
                applied_by=user_id,
                dismissed_at=None,
            )
        )
        assert updated is not None
        await self.audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_PAYMENT_MATCH_ACCEPTED,
            target=f"payment_intent:{intent_id}",
            details={
                "payment_id": str(payment.id),
                "payment_number": payment.payment_number,
                "invoice_id": str(invoice_id),
                "amount": str(payment.amount),
            },
        )
        return updated

    async def undo(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, intent_id: uuid.UUID
    ) -> PaymentIntent:
        """Delete the accepted payment, recompute the invoice, reopen the intent.

        Only within UNDO_WINDOW of the accept - past that the payment is part of
        the closed ledger and must be reversed (future B-item) instead.
        """
        intent = await self.get(tenant_id, intent_id)
        if intent.status != PaymentIntentStatus.APPLIED:
            raise ConflictError("Only an applied payment intent can be undone")
        if intent.applied_at is None:
            raise ConflictError("Applied intent is missing its applied_at stamp")
        if datetime.now(UTC) > intent.applied_at + UNDO_WINDOW:
            raise ConflictError("The 15-minute undo window has expired")
        if intent.applied_payment_id is None or intent.applied_invoice_id is None:
            raise ConflictError("Applied intent is missing its payment/invoice stamp")

        deleted = await self.repo.delete_payment(intent.applied_payment_id, tenant_id)
        if not deleted:
            raise ConflictError("The accepted payment no longer exists - nothing to undo")

        await self.repo.settle_invoice_payment_status(intent.applied_invoice_id, tenant_id)
        reopened_status = (
            PaymentIntentStatus.CANDIDATE
            if (intent.score or Decimal("0")) >= SCORE_CANDIDATE_BAR
            else PaymentIntentStatus.OPEN
        )
        updated = await self.repo.update_payment_intent(
            replace(
                intent,
                status=reopened_status,
                applied_invoice_id=None,
                applied_payment_id=None,
                applied_at=None,
                applied_by=None,
            )
        )
        assert updated is not None
        await self.audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_PAYMENT_MATCH_UNDONE,
            target=f"payment_intent:{intent_id}",
            details={
                "invoice_id": str(intent.applied_invoice_id),
                "payment_id": str(intent.applied_payment_id),
                "amount": str(intent.amount),
            },
        )
        return updated

    async def dismiss(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, intent_id: uuid.UUID
    ) -> PaymentIntent:
        """Close an unresolved intent without moving money."""
        intent = await self.get(tenant_id, intent_id)
        if intent.status in (PaymentIntentStatus.APPLIED, PaymentIntentStatus.DISMISSED):
            raise ConflictError(f"Payment intent {intent_id} is already resolved")
        updated = await self.repo.update_payment_intent(
            replace(intent, status=PaymentIntentStatus.DISMISSED, dismissed_at=datetime.now(UTC))
        )
        assert updated is not None
        await self.audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_PAYMENT_MATCH_DISMISSED,
            target=f"payment_intent:{intent_id}",
            details={"amount": str(intent.amount)},
        )
        return updated

    async def _prevalidate_batch(
        self,
        tenant_id: uuid.UUID,
        items: Sequence[tuple[uuid.UUID, uuid.UUID]],
    ) -> None:
        """Raise on the first invalid item, applying nothing.

        Mirrors the exact guards ``finance.apply_payment`` enforces for a single
        match, so the whole batch is committed to before any money moves.
        """
        for intent_id, invoice_id in items:
            intent = await self.get(tenant_id, intent_id)
            if intent.status in (PaymentIntentStatus.APPLIED, PaymentIntentStatus.DISMISSED):
                raise ConflictError(f"Payment intent {intent_id} is already resolved")
            await self.finance.preflight_payment(
                tenant_id=tenant_id, invoice_id=invoice_id, amount=intent.amount
            )

    async def bulk_accept(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        items: Sequence[tuple[uuid.UUID, uuid.UUID]],
    ) -> list[PaymentMatchBulkResult]:
        """Apply many intent->invoice matches as one all-or-nothing batch.

        Every item is validated up front (intent unresolved + payment applyable)
        before any money moves; a single invalid item rejects the whole batch.
        """
        await self._prevalidate_batch(tenant_id, items)
        results: list[PaymentMatchBulkResult] = []
        for intent_id, invoice_id in items:
            await self.accept(tenant_id, user_id, intent_id, invoice_id=invoice_id)
            results.append(
                PaymentMatchBulkResult(intent_id=intent_id, ok=True, payment_number=None)
            )
        return results


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _tenant_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["tenant_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _user_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["user_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _parse_intent_status(value: str | None) -> PaymentIntentStatus | None:
    if value is None:
        return None
    return PaymentIntentStatus(value)


def _to_response(
    intent: PaymentIntent,
    candidates: tuple[PaymentMatchCandidate, ...],
    customer_name: str | None,
) -> PaymentIntentResponse:
    resp = PaymentIntentResponse.model_validate(intent)
    resp.customer_name = customer_name
    resp.suggestions = [InvoiceSuggestionResponse.model_validate(c) for c in candidates]
    return resp


@router.post(
    "",
    response_model=ResponseEnvelope[PaymentIntentResponse],
    status_code=201,
)
async def register_payment_intent(
    body: PaymentIntentCreateRequest,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: PaymentMatchService = Depends(get_finance_wave4_service),
) -> ResponseEnvelope[PaymentIntentResponse]:
    intent = await svc.register(_tenant_id(current_user), _user_id(current_user), body)
    candidates = await svc._score_for(intent)
    customer_name = None
    if svc.customers is not None and intent.customer_id is not None:
        customer_name = await svc.customers.get_customer_name(
            intent.customer_id, tenant_id=intent.tenant_id
        )
    return ResponseEnvelope(data=_to_response(intent, candidates, customer_name))


@router.get("", response_model=ResponseEnvelope[list[PaymentIntentResponse]])
async def list_payment_intents(
    status: str | None = Query(default=None),
    offset: int = 0,
    limit: int = Query(default=50, le=200),
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: PaymentMatchService = Depends(get_finance_wave4_service),
) -> ResponseEnvelope[list[PaymentIntentResponse]]:
    rows = await svc.list_inbox(
        _tenant_id(current_user),
        status=_parse_intent_status(status),
        offset=offset,
        limit=limit,
    )
    return ResponseEnvelope(
        data=[_to_response(intent, candidates, name) for intent, candidates, name in rows]
    )


# Registered before /{intent_id} routes so 'bulk-accept' is never a UUID capture.
@router.post(
    "/bulk-accept",
    response_model=ResponseEnvelope[PaymentMatchBulkAcceptResponse],
)
async def bulk_accept_payment_intents(
    body: PaymentMatchBulkAcceptRequest,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: PaymentMatchService = Depends(get_finance_wave4_service),
) -> ResponseEnvelope[PaymentMatchBulkAcceptResponse]:
    results = await svc.bulk_accept(
        _tenant_id(current_user),
        _user_id(current_user),
        [(item.intent_id, item.invoice_id) for item in body.items],
    )
    return ResponseEnvelope(data=PaymentMatchBulkAcceptResponse(results=results))


@router.post("/{intent_id}/accept", response_model=ResponseEnvelope[PaymentIntentResponse])
async def accept_payment_intent(
    intent_id: uuid.UUID,
    body: PaymentMatchAcceptRequest,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: PaymentMatchService = Depends(get_finance_wave4_service),
) -> ResponseEnvelope[PaymentIntentResponse]:
    intent = await svc.accept(
        _tenant_id(current_user), _user_id(current_user), intent_id, invoice_id=body.invoice_id
    )
    return ResponseEnvelope(data=PaymentIntentResponse.model_validate(intent))


@router.post("/{intent_id}/undo", response_model=ResponseEnvelope[PaymentIntentResponse])
async def undo_payment_intent(
    intent_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: PaymentMatchService = Depends(get_finance_wave4_service),
) -> ResponseEnvelope[PaymentIntentResponse]:
    intent = await svc.undo(_tenant_id(current_user), _user_id(current_user), intent_id)
    return ResponseEnvelope(data=PaymentIntentResponse.model_validate(intent))


@router.post("/{intent_id}/dismiss", response_model=ResponseEnvelope[PaymentIntentResponse])
async def dismiss_payment_intent(
    intent_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: PaymentMatchService = Depends(get_finance_wave4_service),
) -> ResponseEnvelope[PaymentIntentResponse]:
    intent = await svc.dismiss(_tenant_id(current_user), _user_id(current_user), intent_id)
    return ResponseEnvelope(data=PaymentIntentResponse.model_validate(intent))
