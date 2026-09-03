"""Lightweight telemetry helpers - metrics and timing over structlog.

Foundational plumbing: emits metric records through the already-configured
structlog pipeline (JSON in production), so operational signals need no extra
transport. Use ``timed_span`` to measure a code block and ``record_metric``
for point-in-time counters.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = structlog.get_logger("identity.telemetry")


def record_metric(name: str, value: float = 1.0, **tags: Any) -> None:
    """Emit a metric record (counter or gauge) with structured tags."""
    logger.info("metric", metric=name, value=value, **tags)


async def timed_span(name: str, **tags: Any) -> AsyncGenerator[None, None]:
    """Time a block of code and emit the duration (seconds) as a metric.

    Usage::

        async with timed_span("auth.login"):
            await authenticate(...)
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        record_metric(name, value=time.perf_counter() - start, unit="seconds", **tags)
