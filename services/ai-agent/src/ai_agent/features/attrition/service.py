"""Attrition scoring service (spec §6) - loads a model and scores a batch.

Stateless compute: given a list of anonymous employee feature vectors, return
the non-abstaining scores + top-3 factors. Deterministic, no LLM, no DB. Model
selection follows :func:`load_model` (bundled default or CLI artifact).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_agent.features.attrition.model import load_model
from ai_agent.features.attrition.scorer import ScoredEmployee, score_employee

if TYPE_CHECKING:
    from ai_agent.features.attrition.features import EmployeeFeatures


@dataclass(frozen=True, slots=True)
class ScoreBatchResult:
    model_version: str
    model_source: str
    considered: int
    abstained: int
    scored: list[ScoredEmployee]


class AttritionService:
    """Scores a batch of employees with a single model load."""

    def __init__(self, *, model_path: str | None = None) -> None:
        self._model_path = model_path

    def score_batch(self, employees: list[EmployeeFeatures]) -> ScoreBatchResult:
        model = load_model(self._model_path)
        scored: list[ScoredEmployee] = []
        abstained = 0
        for employee in employees:
            result = score_employee(employee, model)
            if result is None:
                abstained += 1
            else:
                scored.append(result)
        return ScoreBatchResult(
            model_version=model.version,
            model_source=model.source,
            considered=len(employees),
            abstained=abstained,
            scored=scored,
        )
