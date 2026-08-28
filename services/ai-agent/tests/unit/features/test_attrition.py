"""Unit tests for the HR attrition model + scorer (spec §6).

The scorer is deterministic and LLM-free: it must return a score + risk band
+ confidence + exactly the top-3 factor contributions with direction, and it
must abstain (return no score) when confidence is below the 0.75 gate.
"""

from __future__ import annotations

import pytest

from ai_agent.features.attrition.features import EmployeeFeatures
from ai_agent.features.attrition.model import (
    MODEL_VERSION,
    RiskBand,
    build_default_model,
    risk_band,
)
from ai_agent.features.attrition.scorer import score_employee

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("prob", "expected"),
    [
        pytest.param(0.30, RiskBand.LOW, id="low"),
        pytest.param(0.50, RiskBand.MEDIUM, id="medium"),
        pytest.param(0.80, RiskBand.HIGH, id="high"),
        pytest.param(0.44, RiskBand.LOW, id="just-below-low-bound"),
        pytest.param(0.45, RiskBand.MEDIUM, id="at-low-bound"),
        pytest.param(0.70, RiskBand.HIGH, id="at-medium-bound"),
    ],
)
def test_risk_band_mapping(prob: float, expected: str) -> None:
    assert risk_band(prob) == expected


def test_high_risk_employee_returns_score_and_factors() -> None:
    model = build_default_model()
    features = EmployeeFeatures(
        employee_ref="e1",
        tenure_years=1.0,
        compa_ratio=0.85,
        promotion_gap_months=20.0,
        activity_count=1.0,
    )

    result = score_employee(features, model)

    assert result is not None
    assert result.employee_ref == "e1"
    assert result.risk_band == RiskBand.HIGH
    assert 0.0 <= float(result.score) <= 1.0
    # Top-3 factor contributions, never more.
    assert len(result.factors) == 3
    for factor in result.factors:
        assert factor.direction in ("increases", "decreases")
        assert factor.feature
        assert isinstance(float(factor.contribution), float)


def test_low_risk_employee_factors_decrease_risk() -> None:
    model = build_default_model()
    features = EmployeeFeatures(
        employee_ref="e2",
        tenure_years=8.0,
        compa_ratio=1.15,
        promotion_gap_months=2.0,
        activity_count=12.0,
    )

    result = score_employee(features, model)

    assert result is not None
    assert result.risk_band == RiskBand.LOW
    assert any(f.direction == "decreases" for f in result.factors)


def test_abstention_drops_low_confidence_score() -> None:
    model = build_default_model()
    # Boundary input whose P(attrition) lands near 0.5 -> confidence < 0.75.
    features = EmployeeFeatures(
        employee_ref="e3",
        tenure_years=3.0,
        compa_ratio=1.0,
        promotion_gap_months=9.0,
        activity_count=4.0,
    )

    assert score_employee(features, model) is None


def test_service_batch_counts_considered_scored_abstained() -> None:
    from ai_agent.features.attrition.service import AttritionService

    service = AttritionService()
    employees = [
        EmployeeFeatures("e1", 1.0, 0.85, 20.0, 1.0),  # scored (high)
        EmployeeFeatures("e2", 8.0, 1.15, 2.0, 12.0),  # scored (low)
        EmployeeFeatures("e3", 3.0, 1.00, 9.0, 4.0),  # abstains
    ]

    result = service.score_batch(employees)

    assert result.considered == 3
    assert result.abstained == 1
    assert len(result.scored) == 2
    assert result.model_version == MODEL_VERSION


def test_loaded_default_model_version_matches_constant() -> None:
    model = build_default_model()
    assert model.version == MODEL_VERSION
