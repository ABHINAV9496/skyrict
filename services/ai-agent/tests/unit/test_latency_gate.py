"""SKY-100 deterministic first-token latency gate.

This is the CI perf gate: with a zero-delay scripted provider and warm
in-memory caches, the warmed supervisor turn MUST make zero provider calls
and stay under the configured p95 target. It is a regression gate - it cannot
vary with machine speed, only with accidental behavior changes (a cache-key
break, a bypassed abstain path, or a newly-added unbounded loop would push
provider_calls above 0 or blow past the target).
"""

from __future__ import annotations

from latency_harness import (
    TENANT_ID,
    StubRouter,
    build_service,
    run_turn,
    summarize,
)

from ai_agent.core.config import Settings
from ai_agent.features.supervisor import service as supervisor_service

_GATE_QUERY = "tell me about the multi-turn roadmap"
# Keyword-routable variants for the keyword-first fast-path gates below:
# the inventory query routes to a PROVISIONED agent (delegate LLM call only),
# the accounting query routes to an UNPROVISIONED agent (zero calls at all).
_KEYWORD_QUERY = "What stock is below reorder point?"
_UNPROVISIONED_KEYWORD_QUERY = "tell me about multi-turn accounting"


def _warm_router() -> StubRouter:
    """Scripted router whose classifier abstains - the response-cache path."""
    return StubRouter(delay_ms=0, classify_text='{"agents": [], "confidence": 0.1}')


async def test_warm_supervisor_turn_makes_zero_provider_calls() -> None:
    router = _warm_router()
    service = build_service(router=router, caches=True)

    await run_turn(service, query=_GATE_QUERY, router=router)  # warm both caches
    results = [await run_turn(service, query=_GATE_QUERY, router=router) for _ in range(21)]

    assert sum(result.provider_calls for result in results) == 0


async def test_warm_supervisor_turn_p95_below_target() -> None:
    settings = Settings(_env_file=None)
    router = _warm_router()
    service = build_service(router=router, caches=True)

    await run_turn(service, query=_GATE_QUERY, router=router)
    results = [await run_turn(service, query=_GATE_QUERY, router=router) for _ in range(21)]
    summary = summarize(
        results,
        target_ms=settings.FIRST_TOKEN_P95_TARGET_MS,
        provider_calls=sum(result.provider_calls for result in results),
    )

    assert summary["verdict"] == "PASS"
    assert summary["first_token_p95_ms"] <= 5.0


async def test_baseline_turn_still_streams_with_caches_off() -> None:
    """The gate is not meaningless: without caches every turn still makes its
    two provider calls and stays far under the target."""
    router = StubRouter(delay_ms=0)
    service = build_service(router=router, caches=False)

    results = [await run_turn(service, query=_GATE_QUERY, router=router) for _ in range(21)]
    measured_calls = sum(result.provider_calls for result in results)
    summary = summarize(results, target_ms=1000, provider_calls=measured_calls)

    assert summary["verdict"] == "PASS"
    # Keyword-free gate query: the cold abstain path still makes both provider
    # calls (classify + supervisor answer); the keyword fast path is gated
    # separately below.
    assert measured_calls == 42


async def test_keyword_hit_turn_makes_one_cold_provider_call() -> None:
    """Keyword-first fast path: a keyword hit routes with NO classifier call.

    Regression gate for the keyword-first routing fix: a keyword hit must
    short-circuit BEFORE the classifier LLM, so a cold turn to a provisioned
    agent costs only the delegate's own provider call (was two: classify +
    delegate).
    """
    router = StubRouter(delay_ms=0)
    service = build_service(router=router, caches=False)

    results = [await run_turn(service, query=_KEYWORD_QUERY, router=router) for _ in range(21)]

    measured_calls = sum(result.provider_calls for result in results)
    summary = summarize(results, target_ms=1000, provider_calls=measured_calls)

    assert summary["verdict"] == "PASS"
    # 21 turns x 1 call (delegate only) - the classifier call is gone.
    assert measured_calls == 21


async def test_keyword_hit_to_unprovisioned_agent_makes_zero_provider_calls() -> None:
    """A keyword hit on a disabled module streams its abstention for free.

    The routing decision, the provisioned check, and the abstention text are
    all deterministic - no provider call is ever attempted.
    """
    router = StubRouter(delay_ms=0)
    service = build_service(router=router, caches=False)

    results = [
        await run_turn(service, query=_UNPROVISIONED_KEYWORD_QUERY, router=router)
        for _ in range(21)
    ]

    assert sum(result.provider_calls for result in results) == 0


async def test_turn_completed_telemetry_cold_then_warm(monkeypatch) -> None:
    """Each turn emits supervisor.turn_completed with latency + cache flags."""
    captured: list[dict[str, object]] = []

    def fake_info(event: str, **kw: object) -> None:
        if event == "supervisor.turn_completed":
            captured.append({"event": event, **kw})

    monkeypatch.setattr(supervisor_service.logger, "info", fake_info)
    router = _warm_router()
    service = build_service(router=router, caches=True)

    await run_turn(service, query=_GATE_QUERY, router=router)
    await run_turn(service, query=_GATE_QUERY, router=router)

    assert len(captured) == 2
    cold, warm = captured
    assert cold["event"] == "supervisor.turn_completed"
    assert cold["cache_hit"] is False
    assert cold["tenant_id"] == str(TENANT_ID)
    assert isinstance(cold["total_ms"], float) and cold["total_ms"] >= 0
    assert isinstance(cold["first_token_ms"], float) and cold["first_token_ms"] >= 0
    assert warm["cache_hit"] is True
    assert warm["classification_cache_hit"] is True
    assert warm["response_cache_hit"] is True
