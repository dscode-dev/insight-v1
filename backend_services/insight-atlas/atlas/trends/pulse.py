"""Pulse — momentum trend detectors.

Operate on the recomputed match context (current vs prior) and the
feature snapshot. Several features are already differenced/rated at
the feature layer (pressure_delta, signal_density), so dominance and
tempo work from one snapshot; momentum_shift and pressure_building
compare against the prior state.

  momentum_shift     — momentum changed sign / moved sharply
  pressure_building  — pressure rising across recalculations
  tempo_change       — event density changed materially
  dominance_pattern  — one side sustaining clear territorial pressure
"""

from __future__ import annotations

from typing import Any

from atlas.trends.models import Trend, TrendCategory, TrendInputs, TrendType


def _f(d: dict[str, Any] | None, key: str) -> float | None:
    if not d:
        return None
    v = d.get(key)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


class MomentumShiftDetector:
    """Momentum flipped sign or jumped by ≥ threshold. Prefers the
    feature-layer momentum_score; falls back to context momentum."""

    def __init__(self, *, min_delta: float = 0.3) -> None:
        self._min_delta = min_delta

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        now = _f(inputs.features, "momentum_score")
        prev = _f(inputs.prior_features, "momentum_score")
        source = "features"
        if now is None or prev is None:
            now = _f(inputs.context, "momentum")
            prev = _f(inputs.prior_context, "momentum")
            source = "context"
        if now is None or prev is None:
            return []
        delta = now - prev
        flipped = prev != 0 and now != 0 and (prev > 0) != (now > 0)
        if abs(delta) < self._min_delta and not flipped:
            return []
        return [
            Trend(
                trend_type=TrendType.momentum_shift,
                category=TrendCategory.pulse,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=_clamp(abs(delta)),
                confidence=0.8 if flipped else 0.65,
                direction=1 if delta > 0 else -1,
                evidence={
                    "momentum_prev": round(prev, 4),
                    "momentum_now": round(now, 4),
                    "delta": round(delta, 4),
                    "sign_flip": flipped,
                    "source": source,
                },
            )
        ]


class PressureBuildingDetector:
    """Pressure rose vs the prior context AND is above the floor —
    sustained build-up, not a blip from zero."""

    def __init__(self, *, min_rise: float = 0.1, floor: float = 0.5) -> None:
        self._min_rise = min_rise
        self._floor = floor

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        now = _f(inputs.context, "pressure")
        prev = _f(inputs.prior_context, "pressure")
        if now is None or prev is None:
            return []
        rise = now - prev
        if rise < self._min_rise or now < self._floor:
            return []
        return [
            Trend(
                trend_type=TrendType.pressure_building,
                category=TrendCategory.pulse,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=_clamp(now),
                confidence=_clamp(0.55 + rise),
                direction=0,
                evidence={
                    "pressure_prev": round(prev, 4),
                    "pressure_now": round(now, 4),
                    "rise": round(rise, 4),
                },
            )
        ]


class TempoChangeDetector:
    """Event density (signal_density feature) changed by ≥ threshold
    vs the prior snapshot — the game sped up or slowed down."""

    def __init__(self, *, min_delta: float = 0.3) -> None:
        self._min_delta = min_delta

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        now = _f(inputs.features, "signal_density")
        prev = _f(inputs.prior_features, "signal_density")
        if now is None or prev is None:
            return []
        delta = now - prev
        if abs(delta) < self._min_delta:
            return []
        return [
            Trend(
                trend_type=TrendType.tempo_change,
                category=TrendCategory.pulse,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=_clamp(abs(delta)),
                confidence=0.6,
                direction=1 if delta > 0 else -1,
                evidence={
                    "signal_density_prev": round(prev, 4),
                    "signal_density_now": round(now, 4),
                    "delta": round(delta, 4),
                },
            )
        ]


class DominancePatternDetector:
    """One side is sustaining clear dominance.

    Preferred input (Sprint 1): live match statistics — possession,
    shots, dangerous attacks — combined into a composite home−away
    differential in [-1, 1] (mean of the per-stat differentials
    available). Falls back to the windowed `pressure_delta` feature
    when no statistics arrived with this tick.
    """

    _STATS = ("possession", "shots", "dangerous_attacks")

    def __init__(self, *, min_abs_delta: float = 0.4) -> None:
        self._min_abs = min_abs_delta

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        score, components = self._composite(inputs.match_stats)
        basis = "match_stats"
        if score is None:
            score = _f(inputs.features, "pressure_delta")
            basis = "pressure"
            components = {}
        if score is None or abs(score) < self._min_abs:
            return []
        evidence: dict[str, Any] = {
            "dominance_score": round(score, 4),
            "basis": basis,
        }
        evidence.update(components)
        return [
            Trend(
                trend_type=TrendType.dominance_pattern,
                category=TrendCategory.pulse,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=_clamp(abs(score)),
                # Stat-backed dominance is better corroborated than the
                # single pressure feature.
                confidence=0.75 if basis == "match_stats" else 0.65,
                direction=1 if score > 0 else -1,
                evidence=evidence,
            )
        ]

    def _composite(
        self, stats: dict[str, float] | None
    ) -> tuple[float | None, dict[str, float]]:
        """Mean of the normalised home−away differentials across the
        stat pairs present. Each differential is (home−away)/(home+away),
        which lands in [-1, 1] for both percentage pairs (possession)
        and count pairs (shots, dangerous attacks)."""
        if not stats:
            return None, {}
        diffs: list[float] = []
        components: dict[str, float] = {}
        for stat in self._STATS:
            home = stats.get(f"{stat}_home")
            away = stats.get(f"{stat}_away")
            if home is None or away is None:
                continue
            total = home + away
            diff = (home - away) / total if total > 0 else 0.0
            diffs.append(diff)
            components[f"{stat}_diff"] = round(diff, 4)
        if not diffs:
            return None, {}
        return sum(diffs) / len(diffs), components
