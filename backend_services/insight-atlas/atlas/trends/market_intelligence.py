"""Market-intelligence trend detectors — Magnus Absorption Part 8.

All detectors compare the match context's `market_state` (computed by
atlas/market.MarketStateEngine) against the prior context's
market_state. They are pure functions of those two dicts: the engines
own the math, the detectors own the thresholds + trend shaping, and
nothing here re-derives market analytics (no duplicated logic).

Evidence carries only public-safe market-behavior values (consensus /
divergence / confidence / volatility / fair probabilities / sharp
scores) — never margins, overrounds or exploit guidance.
"""

from __future__ import annotations

from typing import Any

from atlas.trends.models import Trend, TrendCategory, TrendInputs, TrendType


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _states(inputs: TrendInputs) -> tuple[dict[str, Any], dict[str, Any]]:
    now = (inputs.context or {}).get("market_state") or {}
    prior = (inputs.prior_context or {}).get("market_state") or {}
    return (now if isinstance(now, dict) else {},
            prior if isinstance(prior, dict) else {})


def _num(state: dict[str, Any], key: str) -> float | None:
    value = state.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _book_confidence(state: dict[str, Any]) -> float:
    """Detection confidence scales with market coverage."""
    books = _num(state, "bookmaker_count") or 0
    return _clamp(0.5 + 0.06 * books)


class MarketConsensusTrendDetector:
    """consensus_score delta ≥ threshold → MARKET_CONSENSUS_GROWING;
    ≤ -threshold → MARKET_CONSENSUS_WEAKENING."""

    def __init__(self, *, min_delta: float = 0.10) -> None:
        self._min_delta = min_delta

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        now, prior = _states(inputs)
        a = _num(prior, "consensus_score")
        b = _num(now, "consensus_score")
        if a is None or b is None:
            return []
        delta = b - a
        if abs(delta) < self._min_delta:
            return []
        growing = delta > 0
        return [Trend(
            trend_type=(TrendType.market_consensus_growing if growing
                        else TrendType.market_consensus_weakening),
            category=TrendCategory.ninja,
            canonical_match_id=inputs.canonical_match_id,
            competition_id=inputs.competition_id,
            minute=inputs.minute,
            strength=_clamp(abs(delta) / 0.4),
            confidence=_book_confidence(now),
            direction=0,
            evidence={
                "consensus_prev": round(a, 4),
                "consensus_now": round(b, 4),
                "consensus_delta": round(delta, 4),
                "bookmaker_count": int(_num(now, "bookmaker_count") or 0),
            },
        )]


class MarketDivergenceDetector:
    """Rising bookmaker disagreement → MARKET_DIVERGENCE; a high-
    divergence + low-consensus regime → MARKET_FRAGMENTATION."""

    def __init__(
        self,
        *,
        min_divergence: float = 0.5,
        min_rise: float = 0.10,
        fragmentation_divergence: float = 0.6,
        fragmentation_consensus: float = 0.35,
    ) -> None:
        self._min_divergence = min_divergence
        self._min_rise = min_rise
        self._frag_div = fragmentation_divergence
        self._frag_cons = fragmentation_consensus

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        now, prior = _states(inputs)
        b = _num(now, "divergence_score")
        if b is None:
            return []
        out: list[Trend] = []
        a = _num(prior, "divergence_score")
        common = {
            "divergence_now": round(b, 4),
            "outliers": list(now.get("divergence_outliers") or []),
            "bookmaker_count": int(_num(now, "bookmaker_count") or 0),
        }
        if a is not None and b >= self._min_divergence and (b - a) >= self._min_rise:
            out.append(Trend(
                trend_type=TrendType.market_divergence,
                category=TrendCategory.ninja,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=_clamp(b),
                confidence=_book_confidence(now),
                direction=0,
                evidence={**common,
                          "divergence_prev": round(a, 4),
                          "divergence_rise": round(b - a, 4)},
            ))
        consensus_now = _num(now, "consensus_score")
        if (
            b >= self._frag_div
            and consensus_now is not None
            and consensus_now <= self._frag_cons
        ):
            out.append(Trend(
                trend_type=TrendType.market_fragmentation,
                category=TrendCategory.ninja,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=_clamp(b),
                confidence=_book_confidence(now),
                direction=0,
                evidence={**common,
                          "consensus_now": round(consensus_now, 4)},
            ))
        return out


class MarketConfidenceTrendDetector:
    """confidence_velocity ≥ threshold → CONFIDENCE_ACCELERATION;
    ≤ -threshold → CONFIDENCE_DECAY."""

    def __init__(self, *, min_velocity: float = 0.08) -> None:
        self._min_velocity = min_velocity

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        now, _ = _states(inputs)
        velocity = _num(now, "confidence_velocity")
        score = _num(now, "confidence_score")
        if velocity is None or score is None:
            return []
        if abs(velocity) < self._min_velocity:
            return []
        accelerating = velocity > 0
        return [Trend(
            trend_type=(TrendType.confidence_acceleration if accelerating
                        else TrendType.confidence_decay),
            category=TrendCategory.ninja,
            canonical_match_id=inputs.canonical_match_id,
            competition_id=inputs.competition_id,
            minute=inputs.minute,
            strength=_clamp(abs(velocity) / 0.25),
            confidence=_book_confidence(now),
            direction=int(now.get("sharp_direction") or 0),
            evidence={
                "confidence_score": round(score, 4),
                "confidence_velocity": round(velocity, 4),
                "fair_probabilities": now.get("fair_probabilities"),
            },
        )]


class MarketVolatilityTrendDetector:
    """volatility_score delta ≥ threshold → VOLATILITY_INCREASE;
    ≤ -threshold → VOLATILITY_DECREASE."""

    def __init__(self, *, min_delta: float = 0.15) -> None:
        self._min_delta = min_delta

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        now, prior = _states(inputs)
        a = _num(prior, "volatility_score")
        b = _num(now, "volatility_score")
        if a is None or b is None:
            return []
        delta = b - a
        if abs(delta) < self._min_delta:
            return []
        increasing = delta > 0
        return [Trend(
            trend_type=(TrendType.volatility_increase if increasing
                        else TrendType.volatility_decrease),
            category=TrendCategory.ninja,
            canonical_match_id=inputs.canonical_match_id,
            competition_id=inputs.competition_id,
            minute=inputs.minute,
            strength=_clamp(abs(delta) / 0.5),
            confidence=_book_confidence(now),
            direction=0,
            evidence={
                "volatility_prev": round(a, 4),
                "volatility_now": round(b, 4),
                "volatility_delta": round(delta, 4),
            },
        )]


class SharpMarketMoveDetector:
    """sharp_movement_score ≥ threshold → SHARP_MARKET_MOVE. Describes
    meaningful coordinated market behavior — not advice."""

    def __init__(self, *, min_score: float = 0.6) -> None:
        self._min_score = min_score

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        now, _ = _states(inputs)
        score = _num(now, "sharp_movement_score")
        if score is None or score < self._min_score:
            return []
        return [Trend(
            trend_type=TrendType.sharp_market_move,
            category=TrendCategory.ninja,
            canonical_match_id=inputs.canonical_match_id,
            competition_id=inputs.competition_id,
            minute=inputs.minute,
            strength=_clamp(score),
            confidence=_book_confidence(now),
            direction=int(now.get("sharp_direction") or 0),
            evidence={
                "sharp_movement_score": round(score, 4),
                "fair_probabilities": now.get("fair_probabilities"),
                "bookmaker_count": int(_num(now, "bookmaker_count") or 0),
            },
        )]
