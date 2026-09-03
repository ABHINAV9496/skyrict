"""Event producers - Phase 1 uses a structlog stub; Kafka comes later.

``skyrict_events`` provides the ``BaseEvent`` envelope and a Kafka
``BaseProducer``. Core does NOT connect to Kafka in Phase 1: :class:`StubEventProducer`
serializes the same envelope and emits it as a structured log line, so every
producer's call site is identical to the real thing and swapping in the Kafka
producer later is a one-line change.

Submodules hold domain producers built on this stub: :mod:`finance_events`
adds the finance money-moment publisher that buffers events and emits them
only after the request transaction commits.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from skyrict_events.base import BaseEvent

logger = structlog.get_logger("core.events")


class StubEventProducer:
    """Log-only producer implementing the BaseEvent publish contract.

    Phase 1 stand-in for Kafka: ``publish`` logs the fully-serialized event
    (same envelope Kafka will carry) at INFO. No broker, no retries - this is
    explicitly a stub until the platform Kafka ticket lands.
    """

    def publish(self, topic: str, event: BaseEvent, *, key: str | None = None) -> None:
        """Emit the event as a structured log line.

        Args:
            topic: Kafka topic the event WOULD be published to.
            event: The ``skyrict_events`` envelope (must be a BaseEvent).
            key: Optional partition key (usually tenant_id or entity ID).
        """
        logger.info(
            "event.published_stub",
            topic=topic,
            event_type=event.event_type,
            event_id=event.event_id,
            tenant_id=event.tenant_id,
            correlation_id=event.correlation_id,
            key=key or event.tenant_id,
            version=event.version,
            metadata=event.metadata,
        )

    async def apublish(self, topic: str, event: BaseEvent, *, key: str | None = None) -> None:
        """Async variant of :meth:`publish` (stub - no IO in Phase 1)."""
        self.publish(topic, event, key=key)


# Module-level singleton - features depend on this, not on constructing
# producers themselves, so swapping the stub for Kafka is a one-line change.
_event_producer: StubEventProducer | None = None


def get_event_producer() -> StubEventProducer:
    """Return the process-wide event producer (stub in Phase 1)."""
    global _event_producer
    if _event_producer is None:
        _event_producer = StubEventProducer()
    return _event_producer


# ---------------------------------------------------------------------------
# After-commit event buffer (docs/modules/hr-payroll.md §2.5)
# ---------------------------------------------------------------------------
# Events emitted inside a request are buffered in a ContextVar and flushed
# ONLY after the DB transaction commits (see core/db/session.py get_db). This
# guarantees no event is observable unless its write was durable. Emits made
# outside a request (tests, background jobs) publish immediately.
# A pending buffer entry is (topic, event, key).
_event_buffer: ContextVar[list[tuple[str, BaseEvent, str | None]] | None] = ContextVar(
    "core_event_buffer",
    default=None,
)


def start_event_buffer() -> None:
    """Begin buffering after-commit events for the current request."""
    _event_buffer.set([])


def buffered_events() -> list[tuple[str, BaseEvent, str | None]]:
    """Return the currently buffered (topic, event, key) triples."""
    buffer = _event_buffer.get()
    return list(buffer) if buffer is not None else []


async def flush_events() -> None:
    """Publish every buffered event to the producer, then drop the buffer."""
    buffer = _event_buffer.get()
    if buffer is None:
        return
    producer = get_event_producer()
    for topic, event, key in buffer:
        await producer.apublish(topic, event, key=key)
    _event_buffer.set(None)


def clear_event_buffer() -> None:
    """Discard buffered events (transaction rolled back / failed)."""
    _event_buffer.set(None)


async def apublish(topic: str, event: BaseEvent, *, key: str | None = None) -> None:
    """Publish an event, honoring the after-commit buffer when active.

    Emit functions call this module-level wrapper instead of the producer
    directly; when ``get_db`` has opened a buffer the event is queued until
    the transaction commits, otherwise it publishes immediately.
    """
    buffer = _event_buffer.get()
    if buffer is None:
        await get_event_producer().apublish(topic, event, key=key)
        return
    buffer.append((topic, event, key))
