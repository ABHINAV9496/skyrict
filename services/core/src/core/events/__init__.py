"""Domain event infrastructure - producers, consumers, and handlers.

The ``skyrict_events`` library provides the shared envelope (``BaseEvent``)
and the ``BaseProducer`` / ``BaseConsumer`` contracts. This package groups the
core service's own producers, consumers, and handlers by direction.

Phase 1: Kafka is NOT wired yet. :class:`StubEventProducer` logs events
(structlog) using the ``skyrict_events`` envelope so producers can be swapped
for the real Kafka producer without changing call sites.
"""

from __future__ import annotations

from core.events.producers import StubEventProducer, get_event_producer

__all__ = ["StubEventProducer", "get_event_producer"]
