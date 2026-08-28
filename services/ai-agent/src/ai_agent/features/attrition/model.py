"""GradientBoostingClassifier + SHAP TreeExplainer (spec §6).

V1 ships a bundled default model fit deterministically on
:data:`~ai_agent.features.attrition.features.reference_training_data`, so
scoring works without any committed binary artifact and is reproducible
(fixed ``random_state``). A manually-trained artifact (exported by the CLI)
is preferred when present.

Only the scorer ever touches this module; the model never calls an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import shap
from sklearn.ensemble import GradientBoostingClassifier

from ai_agent.features.attrition.features import (
    MODEL_VERSION,
    reference_training_data,
)

# Severity buckets for P(attrition) -> risk band (spec §6 / schema check).
_LOW_BOUND = 0.45
_MEDIUM_BOUND = 0.70

# v1 heuristic shell around confidence: derived from the raw probability's
# distance from the abstention edge + data completeness, capped below 1.0 so a
# single-model output never claims certainty. This is a documented placeholder
# (see model_card.json) until a calibrated/validated model is trained.
_ABSTENTION_THRESHOLD = 0.75

_DEFAULT_MODEL_PATH = "ai_agent/features/attrition/artifacts/model.joblib"


class RiskBand:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def risk_band(probability: float) -> str:
    """Map P(attrition) to a low|medium|high band (spec §6)."""
    if probability < _LOW_BOUND:
        return RiskBand.LOW
    if probability < _MEDIUM_BOUND:
        return RiskBand.MEDIUM
    return RiskBand.HIGH


@dataclass(frozen=True, slots=True)
class LoadedModel:
    model: GradientBoostingClassifier
    explainer: Any
    source: str
    version: str


def build_default_model() -> LoadedModel:
    """Fit the bundled deterministic GBC + TreeExplainer (reproducible)."""
    x, y = reference_training_data()
    clf = GradientBoostingClassifier(
        n_estimators=40,
        max_depth=3,
        learning_rate=0.1,
        random_state=0,
    )
    clf.fit(x, y)
    explainer = shap.TreeExplainer(clf)
    return LoadedModel(
        model=clf, explainer=explainer, source="default-bundled", version=MODEL_VERSION
    )


def load_model(path: str | None = None) -> LoadedModel:
    """Return the preferred model: a CLI-exported artifact if it exists.

    ``path`` overrides the default artifact location. Missing/empty artifacts
    fall back to the bundled default so the service never fails to score.
    """
    import os
    import pickle

    target = path or _DEFAULT_MODEL_PATH
    if target and os.path.isfile(target):
        with open(target, "rb") as fh:
            payload = pickle.load(fh)
        if isinstance(payload, dict) and "model" in payload and "version" in payload:
            return LoadedModel(
                model=payload["model"],
                explainer=shap.TreeExplainer(payload["model"]),
                source=f"artifact:{target}",
                version=payload["version"],
            )
    return build_default_model()


def export_model(clf: GradientBoostingClassifier, version: str, path: str) -> None:
    """Persist a trained classifier + its version for later loading."""
    import os
    import pickle

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump({"model": clf, "version": version}, fh)
