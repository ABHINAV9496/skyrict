"""Unit tests for the payment-matching inbox (FIN-AUT-003 B7).

Covers the pure deterministic scorer (:func:`score_match` - amount affinity,
customer hint, invoice-number reference, renormalized weights), candidate
ranking/filtering, and the service flow: register (stores best score + status),
live inbox reads, accept (delegates to apply_payment then stamps intent), the
15-minute undo (delete payment + recompute invoice paid state + reopen), and
dismissals. Repository persistence is exercised by the migration round-trip /
integration suite, not here.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.core.audit_events import (
    FINANCE_PAYMENT_INTENT_REGISTERED,
    FINANCE_PAYMENT_MATCH_ACCEPTED,
    FINANCE_PAYMENT_MATCH_DISMISSED,
    FINANCE_PAYMENT_MATCH_UNDONE,
)
from core.domain.entities import Invoice, PaymentIntent
from core.domain.value_objects import InvoiceStatus, PaymentIntentStatus
from core.features.finance.models.payment_intent import ErpPaymentIntentModel
from core.features.finance.payment_match import (
    PaymentMatchService,
    _compute_candidates,
    score_match,
)
from skyrict_common.exceptions import ConflictError, ValidationError

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
CUSTOMER_A = uuid.UUID("22222222-2222-2222-2222-222222222222")
CUSTOMER_B = uuid.UUID("33333333-3333-3333-3333-333333333333")
INVOICE_A_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
INVOICE_B_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _invoice(
    invoice_id: uuid.UUID,
    number: str,
    total: str,
    customer_id: uuid.UUID,
    outstanding: str | None = None,
) -> tuple[Invoice, Decimal]:
    invoice = Invoice(
        tenant_id=TENANT_ID,
        invoice_number=number,
        customer_id=customer_id,
        invoice_date=datetime(2026, 9, 1).date(),
        due_date=datetime(2026, 9, 30).date(),
        status=InvoiceStatus.APPROVED,
        total=Decimal(total),
        source="manual",
        source_ref=None,
        lines=(),
        id=invoice_id,
    )
    return invoice, Decimal(outstanding if outstanding is not None else total)


class StubIntentRepo:
    def __init__(self) -> None:
        self.intents: dict[uuid.UUID, PaymentIntent] = {}
        self.outstanding: list[tuple[Invoice, Decimal]] = []
        self.payments: dict[uuid.UUID, object] = {}
        self.settled: list[uuid.UUID] = []
        self.deleted_payments: list[uuid.UUID] = []
        self.writes: list[tuple[str, object]] = []

    def _with_id(self, intent: PaymentIntent) -> PaymentIntent:
        stored = replace(intent, id=intent.id or uuid.uuid4())
        self.intents[stored.id] = stored
        return stored

    async def create_payment_intent(self, intent: PaymentIntent) -> PaymentIntent:
        stored = self._with_id(intent)
        self.writes.append(("create_intent", stored))
        return stored

    async def get_payment_intent(self, intent_id, tenant_id):
        return self.intents.get(intent_id)

    async def list_payment_intents(self, tenant_id, *, status=None, offset=0, limit=50):
        values = [i for i in self.intents.values() if i.status == status]
        return sorted(
            values, key=lambda i: i.created_at or datetime.min.replace(tzinfo=UTC), reverse=True
        )[offset : offset + limit]

    async def update_payment_intent(self, intent: PaymentIntent):
        self.intents[intent.id] = intent
        self.writes.append(("update_intent", intent))
        return intent

    async def outstanding_invoices(self, tenant_id):
        return self.outstanding

    async def delete_payment(self, payment_id, tenant_id):
        if payment_id in self.payments:
            del self.payments[payment_id]
            self.deleted_payments.append(payment_id)
            return True
        return False

    async def settle_invoice_payment_status(self, invoice_id, tenant_id):
        self.settled.append(invoice_id)
        return None


class FakeFinance:
    """Duck-typed FinanceService slice: preflight + apply_payment with outstanding guard."""

    def __init__(self, repo: StubIntentRepo) -> None:
        self.repo = repo
        self.applied: list[dict[str, object]] = []
        self._seq = 0

    async def preflight_payment(self, *, tenant_id, invoice_id, amount):
        # Outstanding guard mirrors the real validation that would reject overpay.
        for inv, outstanding in self.repo.outstanding:
            if inv.id == invoice_id and amount > outstanding:
                raise ValidationError("exceeds the outstanding balance")
        return None

    async def apply_payment(self, *, tenant_id, user_id, invoice_id, amount, method, paid_at):
        await self.preflight_payment(tenant_id=tenant_id, invoice_id=invoice_id, amount=amount)
        self._seq += 1
        payment = SimpleNamespace(
            id=uuid.uuid4(), payment_number=f"PAY-2026-{self._seq:05d}", amount=amount
        )
        self.repo.payments[payment.id] = payment
        self.applied.append(
            {"invoice_id": invoice_id, "amount": amount, "method": method, "paid_at": paid_at}
        )
        return payment


class StubCustomers:
    def __init__(self, names: dict[uuid.UUID, str] | None = None) -> None:
        self.names = names or {}

    async def get_customer_name(self, customer_id, *, tenant_id):
        return self.names.get(customer_id)


class RecordingAudit:
    def __init__(self) -> None:
        self.logs: list[dict[str, object]] = []

    async def log(self, **kwargs: object) -> None:
        self.logs.append(kwargs)


def _fresh_service():
    repo = StubIntentRepo()
    finance = FakeFinance(repo)
    audit = RecordingAudit()
    customers = StubCustomers({CUSTOMER_A: "Acme GmbH"})
    service = PaymentMatchService(repo=repo, finance=finance, audit=audit, customers=customers)
    return repo, finance, audit, service


def _body(**overrides):
    fields = {
        "amount": Decimal("500.00"),
        "paid_at": datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
        "method": "bank_transfer",
        "reference": None,
        "source": "manual",
        "source_ref": None,
        "customer_id": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


# ---------------------------------------------------------------------------
# Pure scorer
# ---------------------------------------------------------------------------


def test_score_match_exact_full_payoff_is_one() -> None:
    score = score_match(
        Decimal("500"),
        None,
        None,
        "INV-2026-00042",
        None,
        Decimal("500"),
        Decimal("500"),
    )
    assert score == Decimal("1.0")


def test_score_match_partial_amount_affinity() -> None:
    # Half of the outstanding balance -> 0.5 and nothing else to weight against.
    score = score_match(
        Decimal("250"), None, None, "INV-2026-00042", None, Decimal("500"), Decimal("500")
    )
    assert score == Decimal("0.5000")


def test_score_match_customer_hint_raises_score() -> None:
    without = score_match(
        Decimal("500"),
        CUSTOMER_B,
        None,
        "INV-2026-00042",
        CUSTOMER_A,
        Decimal("500"),
        Decimal("500"),
    )
    with_hint = score_match(
        Decimal("500"),
        CUSTOMER_A,
        None,
        "INV-2026-00042",
        CUSTOMER_A,
        Decimal("500"),
        Decimal("500"),
    )
    assert with_hint > without
    # weights renormalize: only amount + customer are applicable -> matches stay full.
    assert with_hint == Decimal("1.0")


def test_score_match_reference_contains_invoice_number() -> None:
    score = score_match(
        Decimal("500"),
        None,
        "payment INV-2026-00042 thanks",
        "INV-2026-00042",
        None,
        Decimal("500"),
        Decimal("500"),
    )
    assert score == Decimal("1.0")
    unrelated = score_match(
        Decimal("500"),
        None,
        "rent top-up",
        "INV-2026-00042",
        None,
        Decimal("500"),
        Decimal("500"),
    )
    assert unrelated < Decimal("1.0")


def test_compute_candidates_filters_below_bar_and_ranks() -> None:
    pairs = [
        _invoice(INVOICE_A_ID, "INV-2026-00042", "500", CUSTOMER_A, "500"),
        _invoice(INVOICE_B_ID, "INV-2026-00099", "50", CUSTOMER_A, "50"),
    ]
    candidates = _compute_candidates(Decimal("500"), CUSTOMER_A, None, pairs)
    assert len(candidates) == 1, "a 50 balance against a 500 receipt is well under the bar"
    best = candidates[0]
    assert best.invoice_id == INVOICE_A_ID
    assert best.score == Decimal("1.0")


def test_compute_candidates_tie_prefers_most_fully_covered() -> None:
    # Same score: the invoice the amount covers most fully (500/500 > 480/480...)
    # both are exact so tie-break -> lower outstanding first.
    pairs = [
        _invoice(INVOICE_A_ID, "INV-2026-00042", "500", CUSTOMER_A, "500"),
        _invoice(INVOICE_B_ID, "INV-2026-00420", "500", CUSTOMER_A, "500"),
    ]
    candidates = _compute_candidates(Decimal("500"), CUSTOMER_A, None, pairs)
    assert [c.invoice_id for c in candidates] == [INVOICE_A_ID, INVOICE_B_ID]


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


async def test_register_scores_and_stamps_candidate() -> None:
    repo, _finance, audit, service = _fresh_service()
    repo.outstanding = [_invoice(INVOICE_A_ID, "INV-2026-00042", "500", CUSTOMER_A, "500")]

    intent = await service.register(
        TENANT_ID, uuid.uuid4(), _body(amount=Decimal("500"), customer_id=CUSTOMER_A)
    )

    assert intent.status == PaymentIntentStatus.CANDIDATE
    assert intent.score == Decimal("1.0")
    assert intent.suggested_invoice_id == INVOICE_A_ID
    assert audit.logs[-1]["action"] == FINANCE_PAYMENT_INTENT_REGISTERED


async def test_register_with_no_match_stays_open() -> None:
    repo, _finance, _audit, service = _fresh_service()
    repo.outstanding = [_invoice(INVOICE_A_ID, "INV-2026-00042", "99900", CUSTOMER_A, "99900")]

    intent = await service.register(TENANT_ID, uuid.uuid4(), _body(amount=Decimal("40")))

    assert intent.status == PaymentIntentStatus.OPEN
    assert intent.score is None
    assert intent.suggested_invoice_id is None


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------


async def test_list_inbox_returns_unresolved_with_live_candidates() -> None:
    repo, _finance, _audit, service = _fresh_service()
    repo.outstanding = [_invoice(INVOICE_A_ID, "INV-2026-00042", "500", CUSTOMER_A, "500")]
    await service.register(
        TENANT_ID, uuid.uuid4(), _body(amount=Decimal("500"), customer_id=CUSTOMER_A)
    )
    await service.register(
        TENANT_ID, uuid.uuid4(), _body(amount=Decimal("40"), reference="random small")
    )

    rows = await service.list_inbox(TENANT_ID)

    assert len(rows) == 2
    candidate_row = next(r for r in rows if r[0].score is not None)
    assert candidate_row[2] == "Acme GmbH"  # own customer name is resolved for the list
    assert len(candidate_row[1]) == 1
    assert candidate_row[1][0].invoice_id == INVOICE_A_ID


async def test_list_inbox_applied_need_explicit_status() -> None:
    repo, _finance, _audit, service = _fresh_service()
    repo.outstanding = [_invoice(INVOICE_A_ID, "INV-2026-00042", "500", CUSTOMER_A, "500")]
    intent = await service.register(TENANT_ID, uuid.uuid4(), _body(amount=Decimal("500")))
    await service.accept(TENANT_ID, uuid.uuid4(), intent.id, invoice_id=INVOICE_A_ID)

    unresolved = await service.list_inbox(TENANT_ID)
    assert unresolved == []
    applied = await service.list_inbox(TENANT_ID, status=PaymentIntentStatus.APPLIED)
    assert len(applied) == 1


# ---------------------------------------------------------------------------
# Accept
# ---------------------------------------------------------------------------


async def test_accept_delegates_apply_payment_and_stamps() -> None:
    repo, finance, audit, service = _fresh_service()
    repo.outstanding = [_invoice(INVOICE_A_ID, "INV-2026-00042", "500", CUSTOMER_A, "500")]
    intent = await service.register(TENANT_ID, uuid.uuid4(), _body(amount=Decimal("500")))
    user_id = uuid.uuid4()

    applied = await service.accept(TENANT_ID, user_id, intent.id, invoice_id=INVOICE_A_ID)

    assert applied.status == PaymentIntentStatus.APPLIED
    assert applied.applied_invoice_id == INVOICE_A_ID
    assert applied.applied_payment_id is not None
    assert applied.applied_by == user_id
    assert len(finance.applied) == 1
    assert audit.logs[-1]["action"] == FINANCE_PAYMENT_MATCH_ACCEPTED


async def test_accept_idempotent_guard_rejects_reapply() -> None:
    repo, finance, _audit, service = _fresh_service()
    repo.outstanding = [_invoice(INVOICE_A_ID, "INV-2026-00042", "500", CUSTOMER_A, "500")]
    intent = await service.register(TENANT_ID, uuid.uuid4(), _body(amount=Decimal("500")))
    user_id = uuid.uuid4()
    await service.accept(TENANT_ID, user_id, intent.id, invoice_id=INVOICE_A_ID)

    with pytest.raises(ConflictError, match="already resolved"):
        await service.accept(TENANT_ID, user_id, intent.id, invoice_id=INVOICE_A_ID)
    assert len(finance.applied) == 1, "a double-click must never double-pay"


async def test_accept_overpay_surfaces_guard() -> None:
    repo, _finance, _audit, service = _fresh_service()
    repo.outstanding = [_invoice(INVOICE_A_ID, "INV-2026-00042", "100", CUSTOMER_A, "100")]
    intent = await service.register(TENANT_ID, uuid.uuid4(), _body(amount=Decimal("500")))
    with pytest.raises(ValidationError, match="outstanding"):
        await service.accept(TENANT_ID, uuid.uuid4(), intent.id, invoice_id=INVOICE_A_ID)
    assert repo.intents[intent.id].status == PaymentIntentStatus.OPEN


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


async def test_undo_within_window_deletes_payment_reopens() -> None:
    repo, _finance, audit, service = _fresh_service()
    repo.outstanding = [_invoice(INVOICE_A_ID, "INV-2026-00042", "500", CUSTOMER_A, "500")]
    intent = await service.register(TENANT_ID, uuid.uuid4(), _body(amount=Decimal("500")))
    applied = await service.accept(TENANT_ID, uuid.uuid4(), intent.id, invoice_id=INVOICE_A_ID)
    payment_id = applied.applied_payment_id
    assert payment_id in repo.payments

    undone = await service.undo(TENANT_ID, uuid.uuid4(), intent.id)

    assert payment_id not in repo.payments
    assert payment_id in repo.deleted_payments
    assert INVOICE_A_ID in repo.settled, "undo must recompute the invoice paid state"
    assert undone.status == PaymentIntentStatus.CANDIDATE
    assert undone.applied_payment_id is None
    assert audit.logs[-1]["action"] == FINANCE_PAYMENT_MATCH_UNDONE


async def test_undo_expired_window_rejected() -> None:
    repo, _finance, _audit, service = _fresh_service()
    repo.outstanding = [_invoice(INVOICE_A_ID, "INV-2026-00042", "500", CUSTOMER_A, "500")]
    intent = await service.register(TENANT_ID, uuid.uuid4(), _body(amount=Decimal("500")))
    await service.accept(TENANT_ID, uuid.uuid4(), intent.id, invoice_id=INVOICE_A_ID)
    # behave as if the 15-minute window lapsed
    repo.intents[intent.id] = replace(
        repo.intents[intent.id], applied_at=datetime.now(UTC) - timedelta(minutes=16)
    )

    with pytest.raises(ConflictError, match="undo window"):
        await service.undo(TENANT_ID, uuid.uuid4(), intent.id)


async def test_undo_only_for_applied() -> None:
    _repo, _finance, _audit, service = _fresh_service()
    intent = await service.register(TENANT_ID, uuid.uuid4(), _body(amount=Decimal("40")))
    with pytest.raises(ConflictError, match="applied"):
        await service.undo(TENANT_ID, uuid.uuid4(), intent.id)


# ---------------------------------------------------------------------------
# Dismiss + bulk
# ---------------------------------------------------------------------------


async def test_dismiss_closes_without_money() -> None:
    _repo, finance, audit, service = _fresh_service()
    intent = await service.register(TENANT_ID, uuid.uuid4(), _body(amount=Decimal("40")))

    dismissed = await service.dismiss(TENANT_ID, uuid.uuid4(), intent.id)

    assert dismissed.status == PaymentIntentStatus.DISMISSED
    assert dismissed.dismissed_at is not None
    assert finance.applied == []
    assert audit.logs[-1]["action"] == FINANCE_PAYMENT_MATCH_DISMISSED
    with pytest.raises(ConflictError, match="already resolved"):
        await service.dismiss(TENANT_ID, uuid.uuid4(), intent.id)


async def test_bulk_accept_all_or_nothing_rejects_before_applying() -> None:
    repo, finance, audit, service = _fresh_service()
    repo.outstanding = [
        _invoice(INVOICE_A_ID, "INV-2026-00042", "500", CUSTOMER_A, "500"),
        _invoice(INVOICE_B_ID, "INV-2026-00099", "100", CUSTOMER_A, "100"),
    ]
    a = await service.register(TENANT_ID, uuid.uuid4(), _body(amount=Decimal("500")))
    b = await service.register(TENANT_ID, uuid.uuid4(), _body(amount=Decimal("500")))

    with pytest.raises(ValidationError, match="outstanding"):
        await service.bulk_accept(
            TENANT_ID, uuid.uuid4(), [(a.id, INVOICE_A_ID), (b.id, INVOICE_B_ID)]
        )

    # Nothing applied, no intent stamped: the batch was rejected as a whole.
    assert finance.applied == []
    assert repo.intents[a.id].status == PaymentIntentStatus.CANDIDATE
    assert repo.intents[b.id].status == PaymentIntentStatus.CANDIDATE
    assert FINANCE_PAYMENT_MATCH_ACCEPTED not in [log["action"] for log in audit.logs]


async def test_bulk_accept_all_valid_applies_every_item() -> None:
    repo, finance, _audit, service = _fresh_service()
    repo.outstanding = [
        _invoice(INVOICE_A_ID, "INV-2026-00042", "500", CUSTOMER_A, "500"),
        _invoice(INVOICE_B_ID, "INV-2026-00099", "100", CUSTOMER_A, "100"),
    ]
    a = await service.register(TENANT_ID, uuid.uuid4(), _body(amount=Decimal("500")))
    b = await service.register(TENANT_ID, uuid.uuid4(), _body(amount=Decimal("100")))

    results = await service.bulk_accept(
        TENANT_ID, uuid.uuid4(), [(a.id, INVOICE_A_ID), (b.id, INVOICE_B_ID)]
    )

    assert len(results) == 2
    assert results[0].ok is True
    assert results[1].ok is True
    assert len(finance.applied) == 2
    assert repo.intents[a.id].status == PaymentIntentStatus.APPLIED
    assert repo.intents[b.id].status == PaymentIntentStatus.APPLIED


def test_intent_model_declares_source_ref_idempotency_stamp() -> None:
    """Model metadata must mirror migration 0059's partial-unique dedupe stamp."""
    stamp = next(
        (
            i
            for i in ErpPaymentIntentModel.__table__.indexes
            if i.name == "uq_erp_payment_intents_source_ref"
        ),
        None,
    )
    assert stamp is not None, "model is missing the (source, source_ref) idempotency stamp"
    assert stamp.unique is True
    assert stamp.dialect_options["postgresql"]["where"] is not None
