"""Unit tests for the finance after-commit event publisher.

Regression: ``_on_commit`` must accept only ``session`` - SQLAlchemy's
``after_commit`` event dispatches a single argument (``after_begin`` is the
event that also receives the transaction/connection). Requiring an extra
``_previous_transaction`` argument raised a TypeError on every request's
teardown commit, turning otherwise-successful finance requests into 500s.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from core.events.producers.finance_events import FinanceEventPublisher


class FakeProducer:
    """Records publish() calls - mirrors the StubEventProducer contract."""

    def __init__(self) -> None:
        self.published: list[tuple[str, object, str | None]] = []

    def publish(self, topic: str, event: object, *, key: str | None = None) -> None:
        self.published.append((topic, event, key))


def _publisher(session: Session) -> FinanceEventPublisher:
    return FinanceEventPublisher(SimpleNamespace(sync_session=session), producer=FakeProducer())


def test_after_commit_drains_buffered_events() -> None:
    tenant_id = uuid.uuid4()
    invoice_id = uuid.uuid4()
    producer = FakeProducer()
    engine = create_engine("sqlite://")

    with Session(engine) as session:
        publisher = FinanceEventPublisher(SimpleNamespace(sync_session=session), producer=producer)
        publisher.invoice_created(
            invoice_id=invoice_id,
            invoice_number="INV-2026-00001",
            tenant_id=tenant_id,
            correlation_id="test-correlation",
        )
        session.execute(text("SELECT 1"))
        session.commit()

    assert publisher.pending_count == 0
    assert len(producer.published) == 1
    topic, _event, key = producer.published[0]
    assert topic == "finance.invoice.created"
    assert key == str(tenant_id)


def test_after_commit_with_no_pending_events_is_noop() -> None:
    engine = create_engine("sqlite://")

    with Session(engine) as session:
        publisher = _publisher(session)
        session.execute(text("SELECT 1"))
        session.commit()

    assert publisher.pending_count == 0
