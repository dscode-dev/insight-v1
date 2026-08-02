"""Outcome classifier — XGBoost (same library/algorithm as the live classifier,
but bound to the SEPARATE outcome_v1 schema). Emits probabilities + confidence +
uncertainty. CPU-only (honours ATLAS_TRAINING_DEVICE).
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import numpy as np
import xgboost as xgb

from atlas.outcome.schema import (
    FEATURE_NAMES_OUTCOME,
    OUTCOME_LABELS,
    OUTCOME_LABEL_TO_ID,
)


@dataclass
class OutcomePrediction:
    probabilities: dict[str, float]  # {"HOME_WIN":..,"DRAW":..,"AWAY_WIN":..}
    label: str
    confidence: float                # max class probability
    uncertainty: float               # normalised entropy in [0,1]


def _device() -> str:
    d = os.getenv("ATLAS_TRAINING_DEVICE", "cpu").strip().lower()
    return "cuda" if d in {"cuda", "gpu"} else "cpu"


class OutcomeClassifier:
    def __init__(self, booster: xgb.XGBClassifier, feature_importance: dict[str, float]):
        self.booster = booster
        self.feature_importance = feature_importance

    @classmethod
    def train(cls, X: np.ndarray, y: np.ndarray, *, seed: int = 7) -> "OutcomeClassifier":
        if X.ndim != 2 or X.shape[1] != len(FEATURE_NAMES_OUTCOME):
            raise ValueError("X must match the outcome_v1 feature schema")
        if X.shape[0] != y.shape[0]:
            raise ValueError("X and y must align")
        clf = xgb.XGBClassifier(
            n_estimators=120, max_depth=3, learning_rate=0.1,
            subsample=0.9, colsample_bytree=0.9, random_state=seed, n_jobs=1,
            tree_method="hist", device=_device(),
            objective="multi:softprob", num_class=len(OUTCOME_LABELS),
            eval_metric="mlogloss",
        )
        clf.fit(X, y)
        fi = {n: float(v) for n, v in zip(FEATURE_NAMES_OUTCOME, clf.feature_importances_)}
        return cls(clf, fi)

    def predict(self, x: list[float] | np.ndarray) -> OutcomePrediction:
        v = np.asarray(x, dtype=float).reshape(1, -1)
        p = self.booster.predict_proba(v)[0]
        probs = {OUTCOME_LABELS[i]: float(p[i]) for i in range(len(OUTCOME_LABELS))}
        idx = int(np.argmax(p))
        entropy = -sum(q * math.log(q + 1e-9) for q in p) / math.log(len(OUTCOME_LABELS))
        return OutcomePrediction(
            probabilities=probs,
            label=OUTCOME_LABELS[idx],
            confidence=float(p[idx]),
            uncertainty=float(entropy),
        )

    @staticmethod
    def label_id(label: str) -> int:
        return OUTCOME_LABEL_TO_ID[label]

    def to_state(self) -> dict:
        return {"booster": self.booster, "feature_importance": self.feature_importance}

    @classmethod
    def from_state(cls, state: dict) -> "OutcomeClassifier":
        return cls(state["booster"], dict(state["feature_importance"]))
