"""Contextual classifier — XGBoost.

Trained against a small fixed label set that describes match BEHAVIOUR,
not betting outcomes. Labels Atlas uses (V1):

  * `balanced`         — none of the deviations below dominate
  * `late_pressure`    — late_pressure_score is the strongest signal
  * `high_volatility`  — market_volatility dominates
  * `high_engagement`  — signal_density dominates (schema v2 dropped engagement_rate)

Training labels are derived from the feature vectors themselves with a
deterministic rule when historical labels aren't available — i.e., the
classifier is bootstrapped from feature-rule heuristics, then refit on
real data once the rules become noisy. This keeps the service shippable
without waiting for a labelled dataset.

The classifier never outputs a winning team, a probability of any match
outcome, or a betting recommendation. It outputs a BEHAVIOUR class with
a confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import os

import numpy as np
import xgboost as xgb

from atlas.features.definitions import FEATURE_NAMES

CONTEXT_LABELS: list[str] = [
    "balanced",
    "late_pressure",
    "high_volatility",
    "high_engagement",
]


@dataclass
class ClassifierPrediction:
    label: str
    confidence: float
    top_factors: list[tuple[str, float]]


class ContextualClassifierModel:
    def __init__(
        self,
        *,
        booster: xgb.XGBClassifier,
        feature_importance: dict[str, float],
        labels: list[str],
    ) -> None:
        self.booster = booster
        self.feature_importance = feature_importance
        self.labels = labels

    @classmethod
    def train(
        cls,
        X: np.ndarray,
        y: np.ndarray,
        *,
        seed: int = 7,
        labels: list[str] | None = None,
    ) -> "ContextualClassifierModel":
        if X.ndim != 2 or X.shape[1] != len(FEATURE_NAMES):
            raise ValueError("X must match feature schema")
        if X.shape[0] != y.shape[0]:
            raise ValueError("X and y must align")
        labels = labels or CONTEXT_LABELS
        clf = xgb.XGBClassifier(
            n_estimators=120,
            max_depth=4,
            learning_rate=0.1,
            random_state=seed,
            n_jobs=1,
            tree_method="hist",
            device=_training_device(),
            objective="multi:softprob",
            num_class=len(labels),
            eval_metric="mlogloss",
        )
        clf.fit(X, y)
        importances = clf.feature_importances_
        fi = {n: float(v) for n, v in zip(FEATURE_NAMES, importances)}
        return cls(booster=clf, feature_importance=fi, labels=list(labels))

    def predict(self, x: list[float] | np.ndarray, *, top_k: int = 3) -> ClassifierPrediction:
        v = np.asarray(x, dtype=float).reshape(1, -1)
        probas = self.booster.predict_proba(v)[0]
        idx = int(np.argmax(probas))
        # Sort feature importances by magnitude — these explain the
        # MODEL globally; for the local explanation we additionally
        # multiply by the per-feature magnitude of the input vector to
        # capture which features are currently driving the call.
        local = [
            (n, float(self.feature_importance.get(n, 0.0)) * float(abs(v.ravel()[i])))
            for i, n in enumerate(FEATURE_NAMES)
        ]
        local.sort(key=lambda kv: kv[1], reverse=True)
        return ClassifierPrediction(
            label=self.labels[idx],
            confidence=float(probas[idx]),
            top_factors=local[: max(1, top_k)],
        )

    def to_state(self) -> dict:
        return {
            "booster": self.booster,
            "feature_importance": self.feature_importance,
            "labels": self.labels,
        }

    @classmethod
    def from_state(cls, state: dict) -> "ContextualClassifierModel":
        return cls(
            booster=state["booster"],
            feature_importance=dict(state["feature_importance"]),
            labels=list(state["labels"]),
        )


# ---------------------------------------------------------------------------
# Rule-based bootstrap labels — used when no labelled dataset exists.
# ---------------------------------------------------------------------------


def bootstrap_labels(X: np.ndarray) -> np.ndarray:
    """Deterministic labels for warm-start training.

    The rules are NOT a model. They exist so the classifier has a
    plausible starting label set before historical labels accumulate.
    Once real labels are available, retrain without this bootstrap.
    """
    if X.ndim != 2 or X.shape[1] != len(FEATURE_NAMES):
        raise ValueError("X must match feature schema")

    idx = {n: i for i, n in enumerate(FEATURE_NAMES)}
    out = np.empty((X.shape[0],), dtype=int)
    for r in range(X.shape[0]):
        v = X[r]
        late = float(v[idx["late_pressure_score"]])
        vol = float(v[idx["market_volatility"]])
        density = float(v[idx["signal_density"]])
        # Priority order — late pressure dominates because it's only
        # populated for matches past 60'; otherwise volatility, then
        # signal_density-driven engagement (no engagement_rate in
        # schema v2 — see definitions.py).
        if late >= 0.4:
            out[r] = CONTEXT_LABELS.index("late_pressure")
        elif vol >= 0.15:
            out[r] = CONTEXT_LABELS.index("high_volatility")
        elif density >= 1.5:
            out[r] = CONTEXT_LABELS.index("high_engagement")
        else:
            out[r] = CONTEXT_LABELS.index("balanced")
    return out


def _training_device() -> str:
    device = os.getenv("ATLAS_TRAINING_DEVICE", "cpu").strip().lower()
    return "cuda" if device in {"cuda", "gpu"} else "cpu"
