"""RAGAS evaluation runner - composition root for ``ai-agent eval`` (SKY-58).

Runs the nightly retrieval-quality gate: for each curated eval case, drive the
REAL production retrieval pipeline (embedding provider → vector search → parent
fetch), generate an answer strictly from the retrieved context with the
configured LLM provider, then score the pairs with RAGAS (faithfulness, answer
relevancy, context precision, context recall). Results are persisted to
``ai_eval_runs`` and the CLI exits nonzero when any metric falls below its
threshold so the nightly workflow gates on the scores.

ragas is deliberately NOT a package dependency - the runner imports it lazily
and the nightly workflow installs it ephemerally:

    uv run --with "ragas>=0.2,<0.3" ai-agent eval --tenant <slug|uuid>

Local dev and CI lint/type/test stay light, and API drift in a pinned minor
release surfaces as a loud failure in the nightly log instead of a silent
score regression.

Security/reliability invariants mirror ``ingest.py``:

- The session's RLS hook pins the resolved tenant BEFORE the first statement,
  so every read is constrained to that tenant.
- Neither answers nor contexts are logged; only aggregate scores and run id
  go into logs/DB rows.
"""

from __future__ import annotations

import inspect
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from ai_agent.core.config import settings
from ai_agent.core.embedding import build_embedding_provider
from ai_agent.core.exceptions import StartupError
from ai_agent.core.providers.base import LlmRequest
from ai_agent.core.providers.registry import build_providers_from_settings
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.eval_runs_repository import EvalRunsRepository
from ai_agent.db.rag_repository import RagRepository
from ai_agent.db.session import async_session_factory
from ai_agent.db.tenant_resolver import resolve_tenant_id
from ai_agent.features.rag.retrieval.cache import RedisQueryCache
from ai_agent.features.rag.retrieval.service import RagRetrievalService, RetrievalResult
from ai_agent.rag_eval_cases import RAG_EVAL_CASES, RagEvalCase

if TYPE_CHECKING:
    from ai_agent.core.providers.base import LlmProvider

logger = structlog.get_logger("ai_agent.rag.eval")

# Metric names RAGAS reports per sample (see _run_ragas_evaluate).
_METRIC_NAMES = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")

_SYSTEM_PROMPT = (
    "You are Skyrict's retrieval assistant. Answer the user's question using "
    "ONLY the retrieved context below. If the context does not contain the "
    "answer, say the answer is not present in the retrieved context. Never add "
    "information from outside the context."
)


@dataclass(frozen=True, slots=True)
class EvalOutcome:
    """One completed evaluation run: means, gate result, and run id."""

    run_id: uuid.UUID
    sample_count: int
    means: dict[str, float]
    passed: bool
    failures: tuple[str, ...]


def _eval_user_id(tenant_id: uuid.UUID) -> uuid.UUID:
    """Deterministic eval identity so repeated runs share rate-limit/cache state."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"rag-eval:{tenant_id}")


def _select_cases(module: str | None) -> list[RagEvalCase]:
    cases = [case for case in RAG_EVAL_CASES if module is None or case.module == module]
    if not cases:
        known = sorted({case.module for case in RAG_EVAL_CASES})
        raise StartupError(f"no eval cases for module {module!r} (known: {known})")
    return cases


def _build_samples(
    evaluated: list[tuple[RagEvalCase, RetrievalResult, str]],
) -> list[dict[str, object]]:
    """Map retrieval results + answers onto ragas' sample schema (pure).

    Keys follow the ragas 0.2.x ``SingleTurnSample`` contract:
    ``user_input``, ``response``, ``retrieved_contexts``, ``reference``.
    """
    samples: list[dict[str, object]] = []
    for case, result, answer in evaluated:
        samples.append(
            {
                "user_input": case.question,
                "response": answer,
                "retrieved_contexts": [item.chunk_text for item in result.data],
                "reference": case.answer,
            }
        )
    return samples


async def _generate_answer(llm: LlmProvider, *, question: str, contexts: list[str]) -> str:
    """Answer strictly from context; the prompt forbids outside knowledge."""
    context_block = "\n\n".join(f"[{index}] {text}" for index, text in enumerate(contexts, start=1))
    completion = await llm.complete(
        LlmRequest(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=f"Retrieved context:\n{context_block}\n\nQuestion: {question}",
            max_tokens=512,
            temperature=0.0,
        )
    )
    return completion.text


def _summarize_samples(samples: list[dict[str, object]]) -> dict[str, float]:
    """Mean of every numeric metric across per-sample score dicts (pure)."""
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for sample in samples:
        for name, value in sample.items():
            if isinstance(value, (int, float)) and isinstance(name, str):
                totals[name] = totals.get(name, 0.0) + float(value)
                counts[name] = counts.get(name, 0) + 1
    return {name: totals[name] / counts[name] for name in counts}


def _gates_passed(
    means: dict[str, float], thresholds: dict[str, float]
) -> tuple[bool, tuple[str, ...]]:
    """Gate is green only when EVERY scored metric meets its threshold."""
    failures = tuple(
        name for name, threshold in thresholds.items() if means.get(name, 0.0) < threshold
    )
    return (not failures, failures)


def _to_decimal(value: float | None) -> Decimal | None:
    """RAGAS scores are 0..1 floats; the column is Numeric(5, 4)."""
    if value is None:
        return None
    return Decimal(str(round(max(0.0, min(1.0, value)), 4)))


async def _ragas_scores(samples: list[dict[str, object]]) -> list[dict[str, object]]:
    """Score *samples* with RAGAS; import happens lazily (see module docstring)."""
    try:
        from ragas import EvaluationDataset, evaluate
        from ragas.metrics import (
            AnswerRelevancy,
            ContextPrecision,
            ContextRecall,
            Faithfulness,
        )
    except ImportError as exc:  # pragma: no cover - exercised by the nightly workflow
        raise StartupError(
            "ragas is not installed - run the eval via the nightly workflow or "
            "locally with: uv run --with 'ragas>=0.2,<0.3' ai-agent eval"
        ) from exc

    dataset = EvaluationDataset.from_list(samples)
    metrics = [
        Faithfulness(),
        AnswerRelevancy(),
        ContextPrecision(),
        ContextRecall(),
    ]
    # ragas 0.2.x shifted between sync and async evaluate across minor
    # releases; handle both so the pinned range keeps working.
    result = evaluate(dataset=dataset, metrics=metrics)
    if inspect.isawaitable(result):
        result = await result

    raw_scores = getattr(result, "scores", None)
    if isinstance(raw_scores, list) and raw_scores and isinstance(raw_scores[0], dict):
        return [dict(sample) for sample in raw_scores]
    # Fallback for result shapes that only expose a DataFrame.
    frame = result.to_pandas()
    return frame.to_dict(orient="records")  # type: ignore[no-any-return]


async def run_eval(
    *,
    tenant: str,
    module: str | None,
    thresholds: dict[str, float],
) -> EvalOutcome:
    """Run the full eval pipeline for one tenant and persist the run."""
    embedding = build_embedding_provider(settings)
    if embedding is None:
        raise StartupError(
            "No embedding provider configured - set AI_EMBEDDING_PROVIDER=openai "
            "and AI_EMBEDDING_API_KEY"
        )
    llms = build_providers_from_settings(settings)
    if not llms:
        raise StartupError(
            "No LLM provider configured for answer generation - set AI_PROVIDER, "
            "AI_MODEL and AI_API_KEY"
        )
    llm = llms[0]

    cases = _select_cases(module)
    async with async_session_factory() as session:
        tenant_id = await resolve_tenant_id(session, tenant)
        TenantContext.set(str(tenant_id))
        TenantContext.set_tenant_slug(tenant)

        service = RagRetrievalService(
            embedding_provider=embedding,
            store=RagRepository(session),
            cache=RedisQueryCache(),
            top_k_retrieve=settings.RAG_TOP_K_RETRIEVE,
            top_k_return=settings.RAG_TOP_K_RETURN,
            cache_ttl_seconds=settings.RAG_CACHE_TTL_SECONDS,
            rate_limit_per_minute=settings.RATE_LIMIT_RAG_SEARCH_PER_MIN,
            tenant_limit_per_minute=settings.RATE_LIMIT_TENANT_PER_MIN,
        )
        user_id = _eval_user_id(tenant_id)

        evaluated: list[tuple[RagEvalCase, RetrievalResult, str]] = []
        for case in cases:
            result = await service.search(
                query=case.question,
                tenant_id=tenant_id,
                user_id=user_id,
                module=case.module,
            )
            contexts = [item.chunk_text for item in result.data]
            answer = await _generate_answer(llm, question=case.question, contexts=contexts)
            evaluated.append((case, result, answer))

        sample_scores = await _ragas_scores(_build_samples(evaluated))
        means = _summarize_samples(sample_scores)
        passed, failures = _gates_passed(means, thresholds)
        run = await EvalRunsRepository(session).insert_run(
            metrics={
                "thresholds": {name: thresholds.get(name) for name in _METRIC_NAMES},
                "scores": sample_scores,
                "module": module,
                "llm_model": llm.model,
            },
            passed=passed,
            sample_count=len(cases),
            faithfulness=_to_decimal(means.get("faithfulness")),
            answer_relevancy=_to_decimal(means.get("answer_relevancy")),
            context_precision=_to_decimal(means.get("context_precision")),
            context_recall=_to_decimal(means.get("context_recall")),
        )
        await session.commit()

    logger.info(
        "rag.eval_complete",
        tenant_id=str(tenant_id),
        run_id=str(run.id),
        sample_count=len(cases),
        passed=passed,
        failures=list(failures),
        **means,
    )
    return EvalOutcome(
        run_id=run.id,
        sample_count=len(cases),
        means=means,
        passed=passed,
        failures=failures,
    )
