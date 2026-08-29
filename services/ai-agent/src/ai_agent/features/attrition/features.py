"""Feature vectors for the attrition model (spec §6).

``EmployeeFeatures`` is the model input shape, keyed by an opaque
``employee_ref`` (core's employee UUID) so no PII is carried. The v1 model
uses four features derived by core from HR/payroll data:

- ``tenure_years``        years since ``hire_date``
- ``compa_ratio``         current salary / department-baseline salary (>=1 above baseline)
- ``promotion_gap_months`` months since the last compensation ``effective_from``
- ``activity_count``       recent leave-movement / attendance records

This module also carries the small labeled reference dataset used to fit the
bundled deterministic ``GradientBoostingClassifier`` default, so scoring works
out of the box and the model is reproducible (fixed seed).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# Order matters: it is the model input order AND the SHAP feature-name order.
FEATURES = ("tenure_years", "compa_ratio", "promotion_gap_months", "activity_count")

MODEL_VERSION = "v1-gbc-2026-08"


@dataclass(frozen=True, slots=True)
class EmployeeFeatures:
    employee_ref: str
    tenure_years: float
    compa_ratio: float
    promotion_gap_months: float
    activity_count: float

    def to_array(self) -> list[float]:
        return [
            self.tenure_years,
            self.compa_ratio,
            self.promotion_gap_months,
            self.activity_count,
        ]


# Deterministic training folds: values are normalized-ish and labelled
# 1 = attrition-prone, 0 = retained. The rows bias toward the documented risk
# drivers (low tenure, low compa-ratio, long promotion gap, low activity all
# push the class toward 1) so the fitted tree honours the intended semantics.
_TRAINING_ROWS: list[tuple[tuple[float, float, float, float], int]] = [
    ((1.0, 0.85, 20.0, 1.0), 1),
    ((2.0, 0.90, 15.0, 2.0), 1),
    ((0.7, 0.80, 26.0, 0.0), 1),
    ((3.0, 0.95, 12.0, 3.0), 1),
    ((1.5, 0.88, 18.0, 2.0), 1),
    ((5.0, 1.05, 6.0, 8.0), 0),
    ((8.0, 1.15, 2.0, 12.0), 0),
    ((6.0, 1.10, 4.0, 9.0), 0),
    ((12.0, 1.20, 3.0, 15.0), 0),
    ((4.0, 1.00, 7.0, 7.0), 0),
]


def reference_training_data() -> tuple[list[list[float]], list[int]]:
    """Return (X, y) for the bundled default model.

    Exposed for the training CLI so re-fitting from scratch stays possible
    without an external dataset; callers may pass their own folds instead.
    """
    xs: list[list[float]] = []
    ys: list[int] = []
    for x, y in _TRAINING_ROWS:
        xs.append(list(x))
        ys.append(y)
    return xs, ys


def coerce_decimal(value: Any) -> Decimal | None:
    """Best-effort Decimal coercion used when building response factors."""
    try:
        return Decimal(str(value))
    except Exception:
        return None
