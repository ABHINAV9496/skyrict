"""Event producers — Phase 1 uses a structlog stub; Kafka comes later.

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

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from skyrict_events.base import BaseEvent

logger = structlog.get_logger("core.events")


class StubEventProducer:
    """Log-only producer implementing the BaseEvent publish contract.

    Phase 1 stand-in for Kafka: ``publish`` logs the fully-serialized event
    (same envelope Kafka will carry) at INFO. No broker, no retries — this is
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
        """Async variant of :meth:`publish` (stub — no IO in Phase 1)."""
        self.publish(topic, event, key=key)


# Module-level singleton — features depend on this, not on constructing
# producers themselves, so swapping the stub for Kafka is a one-line change.
_event_producer: StubEventProducer | None = None


def get_event_producer() -> StubEventProducer:
    """Return the process-wide event producer (stub in Phase 1)."""
    global _event_producer
    if _event_producer is None:
        _event_producer = StubEventProducer()
    return _event_producer
