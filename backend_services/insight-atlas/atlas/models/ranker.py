"""Contextual ranker — LightGBM LambdaRank.

Used by Radar to surface matches "worth attention" based on the
intelligence context vector. The ranking target is a contextual interest
score derived from anomaly, momentum, and engagement signals — never an
outcome label.

Inputs come in groups (the matches that would be ranked together for a
particular user / surface). For V1 the only "group" is the global Radar
feed, so we train as one big group.
"""

from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np

from atlas.features.definitions import FEATURE_NAMES


@dataclass
class RankerScore:
    score: float
    top_factors: list[tuple[str, float]]


class ContextualRankerModel:
    def __init__(
        self,
        *,
        booster: lgb.LGBMRanker,
        feature_importance: dict[str, float],
    ) -> None:
        self.booster = booster
        self.feature_importance = feature_importance

    @classmethod
    def train(
        cls,
        X: np.ndarray,
        y: np.ndarray,
        *,
        seed: int = 7,
    ) -> "ContextualRankerModel":
        if X.ndim != 2 or X.shape[1] != len(FEATURE_NAMES):
            raise ValueError("X must match feature schema")
        if X.shape[0] != y.shape[0]:
            raise ValueError("X and y must align")
        groups = [X.shape[0]]
        ranker = lgb.LGBMRanker(
            n_estimators=120,
            num_leaves=15,
            learning_rate=0.1,
            random_state=seed,
            verbose=-1,
        )
        ranker.fit(X, y, group=groups)
        importances = ranker.feature_importances_
        # LightGBM importances are integers — normalise so they sum to 1
        # for a cleaner explanation.
        total = float(importances.sum()) or 1.0
        fi = {n: float(v) / total for n, v in zip(FEATURE_NAMES, importances)}
        return cls(booster=ranker, feature_importance=fi)

    def score_vector(self, x: list[float] | np.ndarray, *, top_k: int = 3) -> RankerScore:
        v = np.asarray(x, dtype=float).reshape(1, -1)
        score = float(self.booster.predict(v)[0])
        local = [
            (n, float(self.feature_importance.get(n, 0.0)) * float(abs(v.ravel()[i])))
            for i, n in enumerate(FEATURE_NAMES)
        ]
        local.sort(key=lambda kv: kv[1], reverse=True)
        return RankerScore(score=score, top_factors=local[: max(1, top_k)])

    def to_state(self) -> dict:
        return {"booster": self.booster, "feature_importance": self.feature_importance}

    @classmethod
    def from_state(cls, state: dict) -> "ContextualRankerModel":
        return cls(
            booster=state["booster"],
            feature_importance=dict(state["feature_importance"]),
        )


def bootstrap_relevance(X: np.ndarray) -> np.ndarray:
    """Bootstrap relevance scores — a small integer label per row.

    Composed from feature magnitudes that correlate with "interestingness":
    high momentum, high engagement, high late pressure, high volatility.
    Provides the LambdaRank-style integer relevance label.
    """
    if X.ndim != 2 or X.shape[1] != len(FEATURE_NAMES):
        raise ValueError("X must match feature schema")
    idx = {n: i for i, n in enumerate(FEATURE_NAMES)}
    out = np.empty(X.shape[0], dtype=int)
    for r in range(X.shape[0]):
        v = X[r]
        # engagement_rate term dropped in schema v2 — replaced by a
        # marginal bump from signal_density (the only community-side
        # feature left). See atlas/features/definitions.py.
        score = (
            abs(v[idx["momentum_score"]]) * 2.0
            + v[idx["late_pressure_score"]] * 2.0
            + v[idx["market_volatility"]] * 4.0
            + v[idx["signal_density"]] * 0.25
        )
        out[r] = int(max(0, min(4, round(score))))
    return out
