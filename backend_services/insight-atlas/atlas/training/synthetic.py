"""Synthetic feature-matrix generator.

Used in two places:
  * unit tests (no external analytics API available)
  * cold-start: bootstrapping the first model versions before any real
    history exists

The distribution is deliberately heterogeneous — three latent regimes
generate slightly different feature centroids so clustering has
structure to discover and the classifier can latch onto something
meaningful.
"""

from __future__ import annotations

import numpy as np

from atlas.features.definitions import FEATURE_NAMES, registry


def synthesize_training_set(
    n_samples: int = 600, *, seed: int = 7
) -> np.ndarray:
    """Returns an (n_samples, len(FEATURE_NAMES)) matrix."""
    rng = np.random.default_rng(seed)
    rows = []
    # Three latent regimes — balanced, late-pressure, high-volatility.
    centroids = {
        "balanced": _centroid_balanced(),
        "late": _centroid_late_pressure(),
        "volatile": _centroid_volatile(),
    }
    regimes = list(centroids.keys())
    probs = [0.5, 0.3, 0.2]
    for _ in range(n_samples):
        regime = rng.choice(regimes, p=probs)
        base = centroids[regime].copy()
        noise = rng.normal(0.0, 0.05, size=base.shape)
        v = base + noise
        # Clamp into the per-feature envelopes from the registry.
        for i, name in enumerate(FEATURE_NAMES):
            fd = registry[name]
            v[i] = float(max(fd.low, min(fd.high, v[i])))
        rows.append(v)
    return np.asarray(rows, dtype=float)


def _named(values: dict[str, float]) -> np.ndarray:
    v = np.zeros(len(FEATURE_NAMES))
    for i, name in enumerate(FEATURE_NAMES):
        v[i] = values.get(name, registry[name].default)
    return v


def _centroid_balanced() -> np.ndarray:
    return _named({
        "pressure_home_5m": 0.5,
        "pressure_away_5m": 0.5,
        "pressure_delta": 0.0,
        "market_volatility": 0.05,
        "consensus_shift": 0.0,
        "signal_density": 0.3,
        "community_confidence": 0.5,
        "sentiment_delta": 0.0,
        "momentum_score": 0.0,
        "market_stability_score": 0.9,
        "late_pressure_score": 0.0,
    })


def _centroid_late_pressure() -> np.ndarray:
    return _named({
        "pressure_home_5m": 0.7,
        "pressure_away_5m": 0.55,
        "pressure_delta": 0.15,
        "market_volatility": 0.08,
        "consensus_shift": -0.02,
        "signal_density": 1.4,
        "community_confidence": 0.55,
        "sentiment_delta": 0.05,
        "momentum_score": 0.3,
        "market_stability_score": 0.8,
        "late_pressure_score": 0.6,
    })


def _centroid_volatile() -> np.ndarray:
    return _named({
        "pressure_home_5m": 0.5,
        "pressure_away_5m": 0.5,
        "pressure_delta": 0.0,
        "market_volatility": 0.22,
        "consensus_shift": -0.08,
        "signal_density": 2.6,
        "community_confidence": 0.45,
        "sentiment_delta": -0.1,
        "momentum_score": -0.15,
        "market_stability_score": 0.5,
        "late_pressure_score": 0.0,
    })
