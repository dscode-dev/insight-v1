"""Anomaly model — IsolationForest.

Unsupervised: trained on the distribution of feature vectors, scores
each new vector by how far it sits from the rest. We expose:

  * `score` ∈ [0, 1] where higher means *more* anomalous, derived from
    the negative `decision_function` and normalised against the training
    distribution.
  * `is_anomaly` boolean using a stable, model-internal threshold
    captured at training time so explainability stays consistent across
    inferences.
  * `top_factors` — per-feature z-score deviation against the training
    mean / std, sorted by absolute magnitude. This is the explainer
    output the brief mandates ("never generate black-box outputs").

Output is contextual: "movement detected" — never "bet against".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import IsolationForest

from atlas.features.definitions import FEATURE_NAMES


@dataclass
class AnomalyScore:
    score: float
    is_anomaly: bool
    top_factors: list[tuple[str, float]]


class AnomalyModel:
    """Wraps an `IsolationForest` plus the per-feature training stats
    needed for explainability."""

    def __init__(
        self,
        *,
        estimator: IsolationForest,
        feature_means: np.ndarray,
        feature_stds: np.ndarray,
        score_floor: float,
        score_ceiling: float,
    ) -> None:
        if len(feature_means) != len(FEATURE_NAMES):
            raise ValueError("feature_means length must match FEATURE_NAMES")
        if len(feature_stds) != len(FEATURE_NAMES):
            raise ValueError("feature_stds length must match FEATURE_NAMES")
        self.estimator = estimator
        self.feature_means = feature_means
        self.feature_stds = feature_stds
        self._score_floor = score_floor
        self._score_ceiling = score_ceiling

    @classmethod
    def train(cls, X: np.ndarray, *, contamination: float = 0.05, seed: int = 7) -> "AnomalyModel":
        if X.ndim != 2 or X.shape[1] != len(FEATURE_NAMES):
            raise ValueError(f"X must be 2D with {len(FEATURE_NAMES)} columns")
        if X.shape[0] < 10:
            raise ValueError("need at least 10 samples to train AnomalyModel")
        clf = IsolationForest(
            n_estimators=200,
            contamination=contamination,
            random_state=seed,
            n_jobs=1,
        )
        clf.fit(X)
        means = X.mean(axis=0)
        stds = X.std(axis=0)
        # Guard zero stds — replace with a tiny epsilon to keep the
        # explainer division stable.
        stds = np.where(stds < 1e-9, 1e-9, stds)
        # Normalise scoring envelope from the training distribution so
        # inference outputs are in [0, 1].
        raw = -clf.decision_function(X)
        floor, ceiling = float(np.quantile(raw, 0.05)), float(np.quantile(raw, 0.95))
        if ceiling - floor < 1e-9:
            floor, ceiling = float(raw.min()), float(raw.max() + 1e-9)
        return cls(
            estimator=clf,
            feature_means=means,
            feature_stds=stds,
            score_floor=floor,
            score_ceiling=ceiling,
        )

    def score_vector(self, x: list[float] | np.ndarray, *, top_k: int = 3) -> AnomalyScore:
        v = np.asarray(x, dtype=float).reshape(1, -1)
        if v.shape[1] != len(FEATURE_NAMES):
            raise ValueError(f"input must have {len(FEATURE_NAMES)} features")

        raw = float(-self.estimator.decision_function(v)[0])
        # Normalise into [0, 1] using the training-time envelope.
        denom = self._score_ceiling - self._score_floor
        norm = (raw - self._score_floor) / denom if denom > 0 else 0.0
        norm = max(0.0, min(1.0, norm))

        is_anom = bool(self.estimator.predict(v)[0] == -1)

        # Per-feature z-score deviation — the explainer signal.
        z = (v.ravel() - self.feature_means) / self.feature_stds
        factors = list(zip(FEATURE_NAMES, [float(abs(zi)) for zi in z]))
        factors.sort(key=lambda kv: kv[1], reverse=True)
        return AnomalyScore(
            score=norm,
            is_anomaly=is_anom,
            top_factors=factors[: max(1, top_k)],
        )

    # ---- persistence ----------------------------------------------------

    def to_state(self) -> dict:
        """Return a joblib-serialisable dict. Used by the artifact store."""
        return {
            "estimator": self.estimator,
            "feature_means": self.feature_means,
            "feature_stds": self.feature_stds,
            "score_floor": self._score_floor,
            "score_ceiling": self._score_ceiling,
        }

    @classmethod
    def from_state(cls, state: dict) -> "AnomalyModel":
        return cls(
            estimator=state["estimator"],
            feature_means=np.asarray(state["feature_means"], dtype=float),
            feature_stds=np.asarray(state["feature_stds"], dtype=float),
            score_floor=float(state["score_floor"]),
            score_ceiling=float(state["score_ceiling"]),
        )
