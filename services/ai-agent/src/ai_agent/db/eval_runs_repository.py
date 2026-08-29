"""Persistence for ai_eval_runs — one RAGAS evaluation run per row.

The table is global (cross-tenant metrics, no tenant_id column) and rows are
append-only: the nightly evaluation inserts a run, CI reads last night's row
to gate merges. ``metrics`` holds the full per-sample scores JSONB; the typed
columns (faithfulness, answer_relevancy, context_precision, context_recall)
hold the rounded aggregates for cheap filtering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import insert

from ai_agent.models.ai_eval_run import AiEvalRunModel

if TYPE_CHECKING:
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession


class EvalRunsRepository:
    """One-run write path for RAGAS results (read path: none yet)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert_run(
        self,
        *,
        metrics: dict[str, object],
        passed: bool,
        sample_count: int,
        faithfulness: Decimal | None,
        answer_relevancy: Decimal | None,
        context_precision: Decimal | None,
        context_recall: Decimal | None,
    ) -> AiEvalRunModel:
        """Persist one evaluation run and return the stored row."""
        stmt = (
            insert(AiEvalRunModel)
            .values(
                metrics=metrics,
                passed=passed,
                sample_count=sample_count,
                faithfulness=faithfulness,
                answer_relevancy=answer_relevancy,
                context_precision=context_precision,
                context_recall=context_recall,
            )
            .returning(AiEvalRunModel)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
