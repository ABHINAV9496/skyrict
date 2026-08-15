"""Finance event schemas and publisher (money moments, after-commit).

The four money moments announce themselves through the shared ``BaseEvent``
envelope (``skyrict_events``). Topic == ``event_type`` following the
``{domain}.{entity}.{action}`` convention.

:class:`FinanceEventPublisher` buffers emitted events and publishes them ONLY
after the request transaction commits. This matters: ``get_db`` commits in
dependency teardown, so a publish at emit-time would fire BEFORE the money
actually persisted. The publisher registers a session ``after_commit`` listener
(attached to the sync session backing the request's ``AsyncSession`` — the same
pattern as the RLS ``after_begin`` listener in ``core.db.session``) and drains
there. Consumers therefore never observe money that did not commit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from sqlalchemy import event

from skyrict_events.base import BaseEvent

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from core.events.producers import StubEventProducer

logger = structlog.get_logger("core.events.finance")


# ---------------------------------------------------------------------------
# Event schemas
# ---------------------------------------------------------------------------


class JournalEntryPostedEvent(BaseEvent):
    """A journal entry transitioned draft -> posted (money became real)."""

    event_type: str = "finance.journal_entry.posted"
    entry_id: str


class InvoiceCreatedEvent(BaseEvent):
    """An invoice was created (draft, or issued for create-from-order)."""

    event_type: str = "finance.invoice.created"
    invoice_id: str
    invoice_number: str


class InvoiceApprovedEvent(BaseEvent):
    """An invoice was approved; the accrual entry recognized revenue."""

    event_type: str = "finance.invoice.approved"
    invoice_id: str
    invoice_number: str
    revenue_entry_id: str


class PaymentAppliedEvent(BaseEvent):
    """A payment was applied (cash moved; receivables reduced)."""

    event_type: str = "finance.payment.applied"
    payment_id: str
    payment_number: str
    invoice_id: str


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------


class FinanceEventPublisher:
    """Buffers finance events and publishes them after the request commits.

    Implements (structurally) the ``FinanceEventSink`` port in
    ``core.features.finance.ports`` without importing it — core.events may not
    depend on feature modules (import-linter), and the service depends on the
    Protocol, so the duck-typed boundary keeps both contracts intact.
    """

    def __init__(
        self,
        session: object,
        *,
        producer: StubEventProducer,
    ) -> None:
        self._producer = producer
        self._pending: list[tuple[str, BaseEvent]] = []

        # Attach the after-commit drain to the sync session that backs the
        # request's AsyncSession (weakref'd by event.listen, so it is cleaned
        # up when the request session is garbage collected).
        sync_session = getattr(session, "sync_session", None)
        if sync_session is not None:
            event.listen(sync_session, "after_commit", self._on_commit)

    # --- Sink methods (FinanceEventSink protocol shape) ---

    def journal_entry_posted(
        self,
        *,
        entry_id: uuid.UUID,
        tenant_id: uuid.UUID,
        correlation_id: str,
    ) -> None:
        self._buffer(
            JournalEntryPostedEvent(
                entry_id=str(entry_id),
                tenant_id=str(tenant_id),
                correlation_id=correlation_id,
            )
        )

    def invoice_created(
        self,
        *,
        invoice_id: uuid.UUID,
        invoice_number: str,
        tenant_id: uuid.UUID,
        correlation_id: str,
    ) -> None:
        self._buffer(
            InvoiceCreatedEvent(
                invoice_id=str(invoice_id),
                invoice_number=invoice_number,
                tenant_id=str(tenant_id),
                correlation_id=correlation_id,
            )
        )

    def invoice_approved(
        self,
        *,
        invoice_id: uuid.UUID,
        invoice_number: str,
        revenue_entry_id: uuid.UUID,
        tenant_id: uuid.UUID,
        correlation_id: str,
    ) -> None:
        self._buffer(
            InvoiceApprovedEvent(
                invoice_id=str(invoice_id),
                invoice_number=invoice_number,
                revenue_entry_id=str(revenue_entry_id),
                tenant_id=str(tenant_id),
                correlation_id=correlation_id,
            )
        )

    def payment_applied(
        self,
        *,
        payment_id: uuid.UUID,
        payment_number: str,
        invoice_id: uuid.UUID,
        tenant_id: uuid.UUID,
        correlation_id: str,
    ) -> None:
        self._buffer(
            PaymentAppliedEvent(
                payment_id=str(payment_id),
                payment_number=payment_number,
                invoice_id=str(invoice_id),
                tenant_id=str(tenant_id),
                correlation_id=correlation_id,
            )
        )

    # --- Buffer + drain ---

    def _buffer(self, event: BaseEvent) -> None:
        self._pending.append((event.event_type, event))

    def _drain(self) -> None:
        """Publish every buffered event and clear the buffer."""
        pending = self._pending
        self._pending = []
        for topic, evt in pending:
            self._producer.publish(topic, evt, key=str(evt.tenant_id))

    def _on_commit(self, _session: Session) -> None:
        """Publish after a successful commit.

        Never lets a producer failure escape: the transaction already committed,
        so an exception here would turn a successful request into a 500 while
        the money IS in the ledger. Log and drop instead (Phase 1 stub has no
        failure mode anyway).
        """
        if not self._pending:
            return
        try:
            self._drain()
        except Exception:  # pragma: no cover - defensive, no failure path today
            logger.exception("finance_events.publish_failed", pending=len(self._pending))
            self._pending = []

    @property
    def pending_count(self) -> int:
        """Number of buffered, not-yet-published events (test seam)."""
        return len(self._pending)

    @property
    def pending_events(self) -> Sequence[tuple[str, BaseEvent]]:
        """Snapshot of buffered events (test seam)."""
        return tuple(self._pending)
