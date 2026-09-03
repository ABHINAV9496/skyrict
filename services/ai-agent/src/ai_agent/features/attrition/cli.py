"""Manual attrition-model training CLI (spec §6 training cadence).

The platform has no scheduler: retraining and export is an explicit human
step. Running this fits a ``GradientBoostingClassifier`` (+ SHAP) on the
bundled reference dataset - or on a CSV you supply - and writes the artifact
that :func:`ai_agent.features.attrition.model.load_model` prefers at runtime.
"""

from __future__ import annotations

from pathlib import Path

import typer

from ai_agent.features.attrition.features import FEATURES, reference_training_data

app = typer.Typer(
    name="attrition", help="Train/export the HR attrition model", no_args_is_help=True
)

_DEFAULT_OUT = str(Path(__file__).resolve().parent / "artifacts" / "model.joblib")


@app.command()
def train(
    dataset: str = typer.Option(
        "",
        "--dataset",
        help="optional CSV: rows = features in order tenure_years,compa_ratio,promotion_gap_months,activity_count,label(0/1); header optional",
    ),
    version: str = typer.Option(
        "v1-gbc-2026-08",
        "--version",
        help="model_version string stored with the artifact",
    ),
    output: str = typer.Option(_DEFAULT_OUT, "--output", help="artifact path"),
    max_depth: int = typer.Option(3, "--max-depth"),
    estimators: int = typer.Option(40, "--estimators"),
) -> None:
    """Fit a GradientBoostingClassifier and export it for runtime loading."""
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import accuracy_score

    from ai_agent.features.attrition.model import export_model

    x, y = _load_data(dataset)
    clf = GradientBoostingClassifier(
        n_estimators=estimators, max_depth=max_depth, learning_rate=0.1, random_state=0
    )
    clf.fit(x, y)
    acc = accuracy_score(y, clf.predict(x))
    export_model(clf, version, output)
    typer.echo(
        f"trained GBC on {len(y)} rows (features={list(FEATURES)}), "
        f"train acc={acc:.3f}, exported -> {output} (version={version})"
    )


def _load_data(path: str) -> tuple[list[list[float]], list[int]]:
    if not path:
        return reference_training_data()
    import csv

    xs: list[list[float]] = []
    ys: list[int] = []
    with open(path, encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row or not row[0].strip():
                continue
            if row[0].strip().lower() in ("tenure_years", "feature"):
                continue
            values = [float(v) for v in row]
            xs.append(values[:4])
            ys.append(int(values[4]))
    return xs, ys
