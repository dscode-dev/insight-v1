"""Clustering models.

Two flavours coexist by design:

  * `ClusterModel` — KMeans with a fixed `k`. Provides STABLE cluster
    IDs across re-fits when initialised with the previous centroids.
    Atlas uses this to label matches with a behavioural cluster id that
    the UI can rely on between training runs.

  * `DensityClusterModel` — HDBSCAN. Discovers variable-density groups
    and exposes a `noise` class (id -1). Used for *discovery* — flagging
    that a match doesn't belong to any historical pattern.

Both report contributions: distance to centroid (KMeans) and the
features whose mean differs most between the assigned cluster and the
global mean (both).
"""

from __future__ import annotations

from dataclasses import dataclass

import hdbscan
import numpy as np
from sklearn.cluster import KMeans

from atlas.features.definitions import FEATURE_NAMES


# ---------------------------------------------------------------------------
# KMeans (stable IDs)
# ---------------------------------------------------------------------------


@dataclass
class ClusterAssignment:
    cluster_id: int
    distance: float
    top_factors: list[tuple[str, float]]


class ClusterModel:
    def __init__(
        self,
        *,
        estimator: KMeans,
        cluster_means: np.ndarray,
        global_mean: np.ndarray,
    ) -> None:
        self.estimator = estimator
        self.cluster_means = cluster_means
        self.global_mean = global_mean

    @classmethod
    def train(cls, X: np.ndarray, *, n_clusters: int = 4, seed: int = 7) -> "ClusterModel":
        if X.ndim != 2 or X.shape[1] != len(FEATURE_NAMES):
            raise ValueError("X must match feature schema")
        if X.shape[0] < n_clusters * 3:
            raise ValueError("need at least 3 samples per cluster")
        km = KMeans(n_clusters=n_clusters, n_init=10, random_state=seed)
        km.fit(X)
        return cls(
            estimator=km,
            cluster_means=km.cluster_centers_.copy(),
            global_mean=X.mean(axis=0),
        )

    def assign(self, x: list[float] | np.ndarray, *, top_k: int = 3) -> ClusterAssignment:
        v = np.asarray(x, dtype=float).reshape(1, -1)
        cid = int(self.estimator.predict(v)[0])
        center = self.cluster_means[cid]
        dist = float(np.linalg.norm(v.ravel() - center))
        # Differential signal: features whose centroid deviates most from
        # the global mean — i.e., what makes this cluster distinct.
        diff = np.abs(center - self.global_mean)
        factors = list(zip(FEATURE_NAMES, [float(d) for d in diff]))
        factors.sort(key=lambda kv: kv[1], reverse=True)
        return ClusterAssignment(
            cluster_id=cid,
            distance=dist,
            top_factors=factors[: max(1, top_k)],
        )

    def to_state(self) -> dict:
        return {
            "estimator": self.estimator,
            "cluster_means": self.cluster_means,
            "global_mean": self.global_mean,
        }

    @classmethod
    def from_state(cls, state: dict) -> "ClusterModel":
        return cls(
            estimator=state["estimator"],
            cluster_means=np.asarray(state["cluster_means"], dtype=float),
            global_mean=np.asarray(state["global_mean"], dtype=float),
        )


# ---------------------------------------------------------------------------
# HDBSCAN (density)
# ---------------------------------------------------------------------------


@dataclass
class DensityAssignment:
    cluster_id: int  # -1 means noise
    is_noise: bool
    probability: float
    top_factors: list[tuple[str, float]]


class DensityClusterModel:
    def __init__(
        self,
        *,
        clusterer: "hdbscan.HDBSCAN",
        labels: np.ndarray,
        cluster_means: dict[int, np.ndarray],
        global_mean: np.ndarray,
    ) -> None:
        self.clusterer = clusterer
        self.labels = labels
        self.cluster_means = cluster_means
        self.global_mean = global_mean

    @classmethod
    def train(cls, X: np.ndarray, *, min_cluster_size: int = 5) -> "DensityClusterModel":
        if X.ndim != 2 or X.shape[1] != len(FEATURE_NAMES):
            raise ValueError("X must match feature schema")
        if X.shape[0] < min_cluster_size * 2:
            raise ValueError("need enough samples for hdbscan")
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size, prediction_data=True
        )
        labels = clusterer.fit_predict(X)
        global_mean = X.mean(axis=0)
        cluster_means: dict[int, np.ndarray] = {}
        for cid in set(int(lab) for lab in labels if lab != -1):
            mask = labels == cid
            cluster_means[cid] = X[mask].mean(axis=0)
        return cls(
            clusterer=clusterer,
            labels=labels,
            cluster_means=cluster_means,
            global_mean=global_mean,
        )

    def assign(self, x: list[float] | np.ndarray, *, top_k: int = 3) -> DensityAssignment:
        v = np.asarray(x, dtype=float).reshape(1, -1)
        # `approximate_predict` returns (label_array, probability_array).
        labels, probs = hdbscan.approximate_predict(self.clusterer, v)
        cid = int(labels[0])
        prob = float(probs[0])
        is_noise = cid == -1
        if is_noise:
            # For noise, deviation against global mean is the explainer.
            diff = np.abs(v.ravel() - self.global_mean)
        else:
            center = self.cluster_means.get(cid, self.global_mean)
            diff = np.abs(center - self.global_mean)
        factors = list(zip(FEATURE_NAMES, [float(d) for d in diff]))
        factors.sort(key=lambda kv: kv[1], reverse=True)
        return DensityAssignment(
            cluster_id=cid,
            is_noise=is_noise,
            probability=prob,
            top_factors=factors[: max(1, top_k)],
        )

    def to_state(self) -> dict:
        return {
            "clusterer": self.clusterer,
            "labels": self.labels,
            "cluster_means": self.cluster_means,
            "global_mean": self.global_mean,
        }

    @classmethod
    def from_state(cls, state: dict) -> "DensityClusterModel":
        return cls(
            clusterer=state["clusterer"],
            labels=np.asarray(state["labels"]),
            cluster_means={int(k): np.asarray(v, dtype=float) for k, v in state["cluster_means"].items()},
            global_mean=np.asarray(state["global_mean"], dtype=float),
        )
