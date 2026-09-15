"""First-token latency harness for the Agents shell chat path (SKY-100).

Measures the completion path from request receipt to the first streamed
token (``TokenEvent``) and to the terminal ``done`` event, p50/p95 over
repeated turns. The supervisor runs on scripted fakes only - no database, no
network, no live provider - so the numbers isolate the supervisor/provider
path overhead and are reproducible in CI.

The provider stub sleeps a configurable delay before returning/streaming,
mirroring real network latency. With warm caches (``--cache``), a repeated
identical turn skips the classifier provider call entirely, so the measured
p50/p95 reflects the cache-hit path the SKY-100 gate commits to.

Scenarios
---------
``inventory``
    "What stock is below reorder point?" routes to the inventory_monitor
    agent: classifier ``complete()`` + streaming delegate (the one true
    streaming path - the target for first-token optimization).
``supervisor``
    The stub classifier abstains (no module keyword), so the turn answers as
    the general supervisor via ``complete()`` - the path that gets a
    prompt/response cache.

Usage
-----
    uv run --directory services/ai-agent python scripts/latency_harness.py
    uv run --directory services/ai-agent python scripts/latency_harness.py --scenario supervisor --samples 41 --json

Verdict: ``PASS`` when p95 first-token <= ``--target-ms`` (default 1000).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from ai_agent.cache.response_cache import MemoryResponseCache
from ai_agent.core.providers import LlmCompletion, LlmRequest
from ai_agent.core.providers.base import LlmStreamChunk
from ai_agent.features.nl_query.gateway import ProductRef, StockLevelRow
from ai_agent.features.supervisor.prompts import CLASSIFY_SYSTEM_PROMPT
from ai_agent.features.supervisor.schemas import SupervisorEvent, TokenEvent
from ai_agent.features.supervisor.service import SupervisorService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()

DEFAULT_TARGET_MS = 1000
DEFAULT_SAMPLES = 21
DEFAULT_WARM_SAMPLES = 1
DEFAULT_PROVIDER_DELAY_MS = 200

_CLASSIFY_ANSWER = '{"agents": ["inventory_monitor"], "confidence": 0.9}'
_ABSTAIN_ANSWER = '{"agents": [], "confidence": 0.1}'

_ANONYMOUS_ANSWER = (
    "Here is the summary the monitor has right now. "
    "This line is deliberately long enough to stream as several word deltas "
    "so the harness measures real token streaming rather than a one-word reply. "
    "Stock levels and reorder points are refreshed per request, so repeated "
    "questions always reflect the latest state."
)

_INVENTORY_QUERY = "What stock is below reorder point?"
_SUPERVISOR_QUERY = "tell me a joke about accounting"


@dataclass(frozen=True, slots=True)
class TurnResult:
    """One measured turn through the supervisor."""

    first_token_ms: float | None
    total_ms: float
    provider_calls: int


class StubRouter:
    """Scripted router: sleeps ``delay_ms`` then answers deterministically.

    Identical to the unit-test fake except for the configurable first-token
    delay, which simulates real provider round-trip latency.
    """

    def __init__(
        self,
        *,
        delay_ms: int,
        has_providers: bool = True,
        classify_text: str = _CLASSIFY_ANSWER,
    ) -> None:
        self.has_providers = has_providers
        self._delay_ms = delay_ms
        self._classify_text = classify_text
        self.complete_calls = 0
        self.stream_calls = 0

    @property
    def provider_calls(self) -> int:
        return self.complete_calls + self.stream_calls

    async def complete(self, request: LlmRequest) -> LlmCompletion:
        self.complete_calls += 1
        await asyncio.sleep(self._delay_ms / 1000)
        text = (
            self._classify_text
            if request.system_prompt == CLASSIFY_SYSTEM_PROMPT
            else _ANONYMOUS_ANSWER
        )
        return LlmCompletion(text=text, model_used="stub", latency_ms=self._delay_ms)

    async def stream(self, request: LlmRequest) -> AsyncIterator[LlmStreamChunk]:
        self.stream_calls += 1
        await asyncio.sleep(self._delay_ms / 1000)
        for delta in _word_deltas(_ANONYMOUS_ANSWER):
            yield LlmStreamChunk(token_delta=delta, model_used="stub")


class StubGateway:
    """Read-only inventory fake feeding the inventory delegate."""

    def __init__(self) -> None:
        self._product_id = uuid.uuid4()
        self._warehouse_id = uuid.uuid4()

    async def list_products(self) -> list[ProductRef]:
        return [
            ProductRef(
                id=self._product_id,
                sku="SKU-001",
                name="Widget",
                reorder_point=Decimal("10"),
                cost_price=Decimal("4.20"),
                cost_currency="USD",
            )
        ]

    async def list_warehouses(self) -> list[object]:
        return []

    async def get_stock_levels(
        self,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
    ) -> list[StockLevelRow]:
        return [
            StockLevelRow(
                product_id=self._product_id,
                warehouse_id=self._warehouse_id,
                qty_on_hand=Decimal("5"),
                qty_reserved=Decimal("2"),
            )
        ]

    async def list_movements(
        self,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        movement_type: str | None = None,
    ) -> list[object]:
        return []


def build_service(*, router: StubRouter, caches: bool = False) -> SupervisorService:
    """SupervisorService with scripted fakes - no DB, no network.

    With ``caches`` the classification + response caches are wired as
    in-memory stores so a repeated identical turn skips the provider calls -
    the warm-path the SKY-100 gate commits to.
    """

    gateway = StubGateway()

    async def gateway_factory() -> StubGateway:
        return gateway

    return SupervisorService(
        llm_router=router,
        gateway_factory=gateway_factory,
        provisioned={"inventory_monitor": True},
        classification_cache=MemoryResponseCache() if caches else None,
        response_cache=MemoryResponseCache() if caches else None,
        classification_cache_ttl_seconds=300,
        response_cache_ttl_seconds=300,
    )


async def run_turn(
    service: SupervisorService,
    *,
    query: str,
    router: StubRouter,
) -> TurnResult:
    """Run one turn; first_token_ms is time to the first TokenEvent.

    provider_calls counts calls made during THIS turn only (delta from before
    the turn), so warm-up and cache effects are reported per measured turn.
    """
    started = time.perf_counter()
    calls_before = router.provider_calls
    first_token_ms: float | None = None
    async for event in _iter_events(service, query):
        if isinstance(event, TokenEvent) and first_token_ms is None:
            first_token_ms = (time.perf_counter() - started) * 1000
    total_ms = (time.perf_counter() - started) * 1000
    return TurnResult(
        first_token_ms=first_token_ms,
        total_ms=total_ms,
        provider_calls=router.provider_calls - calls_before,
    )


async def _iter_events(service: SupervisorService, query: str) -> AsyncIterator[SupervisorEvent]:
    async for event in service.stream_answer(
        query=query,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
    ):
        yield event


def summarize(
    results: list[TurnResult],
    *,
    target_ms: int,
    provider_calls: int,
) -> dict[str, object]:
    """p50/p95 over measured turns plus the verdict vs the gate target."""
    first_tokens = [r.first_token_ms for r in results if r.first_token_ms is not None]
    totals = [r.total_ms for r in results]
    if not first_tokens:
        raise RuntimeError("no first-token measurements - no TokenEvent streamed")
    p50 = statistics.quantiles(first_tokens, n=4)[1]
    p95 = statistics.quantiles(first_tokens, n=20)[18]
    return {
        "samples": len(results),
        "first_token_p50_ms": round(p50, 1),
        "first_token_p95_ms": round(p95, 1),
        "total_p50_ms": round(statistics.quantiles(totals, n=4)[1], 1),
        "total_p95_ms": round(statistics.quantiles(totals, n=20)[18], 1),
        "provider_calls": provider_calls,
        "target_p95_ms": target_ms,
        "verdict": "PASS" if p95 <= target_ms else "FAIL",
    }


def _word_deltas(text: str) -> list[str]:
    words = text.split(" ")
    return [word + (" " if index < len(words) - 1 else "") for index, word in enumerate(words)]


async def amain(args: argparse.Namespace) -> dict[str, object]:
    classify_text = _ABSTAIN_ANSWER if args.scenario == "supervisor" else _CLASSIFY_ANSWER
    router = StubRouter(delay_ms=args.provider_delay_ms, classify_text=classify_text)
    service = build_service(router=router, caches=args.cache)
    query = _INVENTORY_QUERY if args.scenario == "inventory" else _SUPERVISOR_QUERY

    # Warm caches (a cache-aware build is wired in when --cache is used).
    if args.cache:
        for _ in range(args.warm_samples):
            await run_turn(service, query=query, router=router)

    results = [await run_turn(service, query=query, router=router) for _ in range(args.samples)]
    summary = summarize(
        results,
        target_ms=args.target_ms,
        provider_calls=sum(result.provider_calls for result in results),
    )
    summary["scenario"] = args.scenario
    summary["cache"] = bool(args.cache)
    summary["provider_delay_ms"] = args.provider_delay_ms
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("inventory", "supervisor"), default="inventory")
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--warm-samples", type=int, default=DEFAULT_WARM_SAMPLES)
    parser.add_argument("--provider-delay-ms", type=int, default=DEFAULT_PROVIDER_DELAY_MS)
    parser.add_argument("--target-ms", type=int, default=DEFAULT_TARGET_MS)
    parser.add_argument("--cache", action="store_true", help="wire caches (baseline-off)")
    parser.add_argument("--json", action="store_true", help="emit a single JSON line")
    args = parser.parse_args()

    summary = asyncio.run(amain(args))
    if args.json:
        print(json.dumps(summary))
    else:
        print(
            f"scenario={summary['scenario']} cache={summary['cache']} "
            f"{summary['samples']} samples "
            f"first_token p50={summary['first_token_p50_ms']}ms "
            f"p95={summary['first_token_p95_ms']}ms "
            f"total p95={summary['total_p95_ms']}ms "
            f"provider_calls={summary['provider_calls']} "
            f"verdict={summary['verdict']} (target {summary['target_p95_ms']}ms)"
        )


if __name__ == "__main__":
    main()
