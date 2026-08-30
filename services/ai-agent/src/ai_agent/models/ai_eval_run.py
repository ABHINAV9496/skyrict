"""ai_eval_runs - RAGAS evaluation run results.

Global (not tenant-scoped) table recording nightly RAGAS evaluation results.
Each run stores aggregate metrics (faithfulness, answer_relevancy, context
precision/recall), a pass/fail flag against configured thresholds, and the
full metrics JSONB for drill-down.

The ``passed`` column gates CI: nightly workflow fails if faithfulness < 0.8.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiEvalRunModel(Base):
    """One RAGAS evaluation run with aggregate metrics."""

    __tablename__ = "ai_eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    metrics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    faithfulness: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    answer_relevancy: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    context_precision: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    context_recall: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
