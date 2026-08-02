"""Ninja — market trend detectors.

All four detectors operate on the persisted h2h odds timeline
(OddsTick history) and the bookmaker state at the latest snapshot.
Implied probability (1/price) is the comparison unit so thresholds are
provider- and price-level-agnostic.

  market_shift         — consensus implied probability moved
  market_acceleration  — the move is speeding up vs the recent baseline
  market_disagreement  — bookmakers materially disagree right now
  market_anomaly       — one bookmaker is detached from the rest
"""

from __future__ import annotations

from datetime import datetime

from atlas.odds.features import H2H, _latest_per_bookmaker, _mean
from atlas.trends.models import Trend, TrendCategory, TrendInputs, TrendType

# Cap on chart series length so chart_data stays render-sized.
CHART_MAX_POINTS = 50


def _implied(price: float | None) -> float | None:
    if price is None or price <= 0:
        return None
    return 1.0 / price


def _consensus_prob_points(inputs: TrendInputs) -> list[tuple[datetime, float]]:
    """Timestamped consensus home implied-probability series: per
    snapshot instant, forward-fill each bookmaker's latest price and
    average the implied probabilities."""
    h2h = sorted(
        (t for t in inputs.odds_history if t.market == H2H),
        key=lambda t: t.captured_at,
    )
    timestamps = sorted({t.captured_at for t in h2h})
    latest_by_book: dict[str, float] = {}
    points: list[tuple[datetime, float]] = []
    for ts in timestamps:
        for t in h2h:
            if t.captured_at == ts and t.home is not None and t.home > 0:
                latest_by_book[t.bookmaker] = t.home
        probs = [1.0 / price for price in latest_by_book.values()]
        if probs:
            points.append((ts, sum(probs) / len(probs)))
    return points


def _consensus_prob_series(inputs: TrendInputs) -> list[float]:
    return [v for _, v in _consensus_prob_points(inputs)]


def _chart(points: list[tuple[datetime, float]]) -> dict:
    tail = points[-CHART_MAX_POINTS:]
    return {
        "kind": "implied_probability",
        "series": [{"t": ts.isoformat(), "v": round(v, 4)} for ts, v in tail],
    }


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


class MarketShiftDetector:
    """Consensus home implied probability moved ≥ threshold between the
    two most recent snapshots."""

    def __init__(self, *, min_prob_delta: float = 0.03) -> None:
        self._min_delta = min_prob_delta

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        points = _consensus_prob_points(inputs)
        series = [v for _, v in points]
        if len(series) < 2:
            return []
        delta = series[-1] - series[-2]
        if abs(delta) < self._min_delta:
            return []
        books = len({t.bookmaker for t in inputs.odds_history if t.market == H2H})
        return [
            Trend(
                trend_type=TrendType.market_shift,
                category=TrendCategory.ninja,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=_clamp(abs(delta) / 0.15),
                confidence=_clamp(0.5 + 0.1 * books),
                direction=1 if delta > 0 else -1,
                evidence={
                    "implied_prob_prev": round(series[-2], 4),
                    "implied_prob_now": round(series[-1], 4),
                    "prob_delta": round(delta, 4),
                    "bookmaker_count": books,
                },
                chart_data=_chart(points),
            )
        ]


class MarketAccelerationDetector:
    """The latest consensus move is ≥ factor × the mean of the recent
    moves — the market is speeding up, not just drifting."""

    def __init__(self, *, factor: float = 2.0, min_prob_delta: float = 0.02) -> None:
        self._factor = factor
        self._min_delta = min_prob_delta

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        series = _consensus_prob_series(inputs)
        if len(series) < 4:
            return []
        deltas = [abs(series[i] - series[i - 1]) for i in range(1, len(series))]
        last = deltas[-1]
        baseline = _mean(deltas[:-1]) or 0.0
        if last < self._min_delta or baseline <= 0 or last < self._factor * baseline:
            return []
        direction = 1 if series[-1] > series[-2] else -1
        return [
            Trend(
                trend_type=TrendType.market_acceleration,
                category=TrendCategory.ninja,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=_clamp(last / (self._factor * max(baseline, 1e-6)) / 3.0),
                confidence=_clamp(0.6 + 0.05 * (len(series) - 4)),
                direction=direction,
                evidence={
                    "last_delta": round(last, 4),
                    "baseline_delta": round(baseline, 4),
                    "acceleration_factor": round(last / max(baseline, 1e-6), 2),
                    "samples": len(series),
                },
            )
        ]


class MarketDisagreementDetector:
    """The spread of home implied probabilities across bookmakers at the
    latest snapshot exceeds the threshold — books disagree about the
    same match right now."""

    def __init__(self, *, min_prob_spread: float = 0.08) -> None:
        self._min_spread = min_prob_spread

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        h2h = [t for t in inputs.odds_history if t.market == H2H]
        latest = _latest_per_bookmaker(h2h)
        probs = {
            t.bookmaker: p
            for t in latest
            if (p := _implied(t.home)) is not None
        }
        if len(probs) < 2:
            return []
        spread = max(probs.values()) - min(probs.values())
        if spread < self._min_spread:
            return []
        return [
            Trend(
                trend_type=TrendType.market_disagreement,
                category=TrendCategory.ninja,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=_clamp(spread / 0.25),
                confidence=_clamp(0.5 + 0.1 * len(probs)),
                direction=0,
                evidence={
                    "prob_spread": round(spread, 4),
                    "bookmaker_probs": {k: round(v, 4) for k, v in probs.items()},
                },
            )
        ]


class MarketAnomalyDetector:
    """One bookmaker's home implied probability deviates from the
    MEDIAN of all books by ≥ threshold — a single detached book (stale
    feed, exposure management, or information). Median, not mean: a
    single outlier must not drag the baseline toward itself and flag
    the honest books as anomalous."""

    def __init__(self, *, min_prob_deviation: float = 0.10) -> None:
        self._min_dev = min_prob_deviation

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        h2h = [t for t in inputs.odds_history if t.market == H2H]
        latest = _latest_per_bookmaker(h2h)
        probs = {
            t.bookmaker: p
            for t in latest
            if (p := _implied(t.home)) is not None
        }
        if len(probs) < 3:
            return []
        ordered = sorted(probs.values())
        n = len(ordered)
        median = (
            ordered[n // 2]
            if n % 2 == 1
            else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0
        )
        out: list[Trend] = []
        for book, prob in probs.items():
            deviation = prob - median
            if abs(deviation) < self._min_dev:
                continue
            out.append(
                Trend(
                    trend_type=TrendType.market_anomaly,
                    category=TrendCategory.ninja,
                    canonical_match_id=inputs.canonical_match_id,
                    competition_id=inputs.competition_id,
                    minute=inputs.minute,
                    strength=_clamp(abs(deviation) / 0.25),
                    confidence=_clamp(0.5 + 0.1 * (len(probs) - 1)),
                    direction=1 if deviation > 0 else -1,
                    evidence={
                        "bookmaker": book,
                        "bookmaker_prob": round(prob, 4),
                        "median_prob": round(median, 4),
                        "deviation": round(deviation, 4),
                    },
                )
            )
        return out
