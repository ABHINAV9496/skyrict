"""Kafka event producers - publish domain events.

Currently a logging-only stub: no broker connection is made until the
identity event wiring lands. The production path will publish
``skyrict_events.BaseEvent`` envelopes via a ``BaseProducer`` subclass
(topic convention ``{domain}.{entity}.{action}``, e.g.
``identity.user.created``).
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger("identity.events")


async def publish_event(topic: str, key: str, payload: dict[str, Any]) -> None:
    """Publish a domain event - logging only until Kafka wiring lands."""
    logger.info(
        "event.published",
        topic=topic,
        key=key,
        payload_keys=list(payload.keys()),
    )
