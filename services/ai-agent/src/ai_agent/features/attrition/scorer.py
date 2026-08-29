"""Attrition scorer — risk score + confidence + top-3 factors (spec §6).

Pure, deterministic, non-LLM. Given per-employee feature vectors, it returns a
score (P(attrition)), a risk band, a confidence, and the top-3 SHAP-style
factor contributions with direction, applying the business-wide abstention
rule (``confidence < 0.75`` → the score is dropped, never returned).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ai_agent.features.attrition.features import FEATURES, EmployeeFeatures
from ai_agent.features.attrition.model import LoadedModel, risk_band

ABSTENTION_THRESHOLD_CHANCE = 0.75

# A deterministic SHAP may be unavailable (stub/fallback); we still must emit
# factor contributions with a stable order, so fall back to per-feature
# deviation contributions.
_DEFAULT_FEATURE_LABELS = {
    "tenure_years": "tenure",
    "compa_ratio": "pay vs baseline",
    "promotion_gap_months": "promotion gap",
    "activity_count": "activity",
}


@dataclass(frozen=True, slots=True)
class FactorContribution:
    feature: str
    contribution: Decimal
    direction: str  # "increases" | "decreases"


@dataclass(frozen=True, slots=True)
class ScoredEmployee:
    employee_ref: str
    score: Decimal  # P(attrition) 0..1
    risk_band: str
    confidence: Decimal
    factors: list[FactorContribution] = field(default_factory=list)


def _to_decimal(value: float, places: int = 4) -> Decimal:
    return Decimal(str(round(value, places)))


def _confidence(probability: float, features: EmployeeFeatures) -> float:
    """v1 confidence: distance from the abstention edge weighted by data presence.

    Documented placeholder (spec §6 / model_card.json): a higher-magnitude
    model probability is treated as more confident, and we subtract a penalty
    for sparse/missing activity data. Never reaches 1.0.
    """
    base = max(0.0, min(0.98, abs(probability - 0.5) * 2.0 + 0.30))
    if features.activity_count <= 0:
        base -= 0.05
    if features.compa_ratio <= 0:
        base -= 0.10
    return max(0.0, min(0.98, base))


def _shap_factors(
    model: LoadedModel, features: EmployeeFeatures, probability: float
) -> list[FactorContribution]:
    """Top-3 feature contributions via SHAP with direction.

    Falls back to feature-deviation contributions if the model provides no
    TreeExplainer (keeps the vertical slice unit-testable and robust).
    """
    contributions: dict[str, float] = {}
    try:
        base = getattr(model.explainer, "expected_value", None)
        shap_values = model.explainer.shap_values([features.to_array()])
        values = shap_values[1] if isinstance(shap_values, list) else shap_values
        vals = values[0]
        if base is not None and abs(float(base)) > 1e-9:
            contributions = {FEATURES[i]: float(vals[i] - base) for i in range(len(FEATURES))}
        else:
            contributions = {FEATURES[i]: float(vals[i]) for i in range(len(FEATURES))}
    except Exception:
        contributions = {
            "tenure_years": (5.0 - features.tenure_years) * 0.02,
            "compa_ratio": (1.0 - features.compa_ratio) * 0.15,
            "promotion_gap_months": (features.promotion_gap_months - 6.0) * 0.01,
            "activity_count": (3.0 - features.activity_count) * 0.02,
        }

    ranked = sorted(contributions.items(), key=lambda kv: abs(kv[1]), reverse=True)
    out: list[FactorContribution] = []
    for feature, contrib in ranked[:3]:
        direction = "increases" if contrib > 0 else "decreases"
        out.append(
            FactorContribution(
                feature=_DEFAULT_FEATURE_LABELS.get(feature, feature),
                contribution=_to_decimal(contrib, 4),
                direction=direction,
            )
        )
    return out


def score_employee(features: EmployeeFeatures, model: LoadedModel) -> ScoredEmployee | None:
    """Score one employee; returns ``None`` when the model abstains (<0.75)."""
    probability = float(model.model.predict_proba([features.to_array()])[0][1])
    confidence = _confidence(probability, features)
    if confidence < ABSTENTION_THRESHOLD_CHANCE:
        return None
    factors = _shap_factors(model, features, probability)
    return ScoredEmployee(
        employee_ref=features.employee_ref,
        score=_to_decimal(probability),
        risk_band=risk_band(probability),
        confidence=_to_decimal(confidence, 2),
        factors=factors,
    )
