"""Echo — narrative trend detectors.

Operate on the sentiment / community features the feature pipeline
already derives from the sentiment reader (`sentiment_delta`,
`community_confidence`). Atlas never reads raw posts, users or social
state — only the numeric features. No LLM anywhere.

  sentiment_shift     — community sentiment moved sharply
  narrative_conflict  — sentiment direction contradicts the market move
  community_signal    — community confidence is unusually strong
"""

from __future__ import annotations

from typing import Any

from atlas.odds.features import H2H, _consensus_home_series
from atlas.trends.models import Trend, TrendCategory, TrendInputs, TrendType


def _f(d: dict[str, Any] | None, key: str) -> float | None:
    if not d:
        return None
    try:
        return float(d.get(key))
    except (TypeError, ValueError):
        return None


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _market_direction(inputs: TrendInputs) -> int:
    """Sign of the latest consensus implied-probability move (home
    perspective). 0 when there is no usable market series."""
    h2h = [t for t in inputs.odds_history if t.market == H2H]
    series = _consensus_home_series(h2h)
    probs = [1.0 / v for v in series if v > 0]
    if len(probs) < 2:
        return 0
    delta = probs[-1] - probs[-2]
    if delta > 0:
        return 1
    if delta < 0:
        return -1
    return 0


class SentimentShiftDetector:
    """|sentiment_delta| (already a windowed delta at the feature layer)
    exceeds the threshold — community sentiment moved sharply."""

    def __init__(self, *, min_abs_delta: float = 0.35) -> None:
        self._min_abs = min_abs_delta

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        delta = _f(inputs.features, "sentiment_delta")
        if delta is None or abs(delta) < self._min_abs:
            return []
        return [
            Trend(
                trend_type=TrendType.sentiment_shift,
                category=TrendCategory.echo,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=_clamp(abs(delta)),
                confidence=0.6,
                direction=1 if delta > 0 else -1,
                evidence={"sentiment_delta": round(delta, 4)},
            )
        ]


class NarrativeConflictDetector:
    """Sentiment direction contradicts the market's latest move — the
    crowd and the books are telling different stories."""

    def __init__(self, *, min_abs_sentiment: float = 0.25) -> None:
        self._min_abs = min_abs_sentiment

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        sentiment = _f(inputs.features, "sentiment_delta")
        if sentiment is None or abs(sentiment) < self._min_abs:
            return []
        market_dir = _market_direction(inputs)
        sentiment_dir = 1 if sentiment > 0 else -1
        if market_dir == 0 or market_dir == sentiment_dir:
            return []
        return [
            Trend(
                trend_type=TrendType.narrative_conflict,
                category=TrendCategory.echo,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=_clamp(abs(sentiment)),
                confidence=0.55,
                direction=sentiment_dir,
                evidence={
                    "sentiment_delta": round(sentiment, 4),
                    "sentiment_direction": sentiment_dir,
                    "market_direction": market_dir,
                },
            )
        ]


class CommunitySignalDetector:
    """community_confidence is unusually strong — the community is
    converging on something about this match."""

    def __init__(self, *, min_confidence: float = 0.75) -> None:
        self._min_conf = min_confidence

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        conf = _f(inputs.features, "community_confidence")
        if conf is None or conf < self._min_conf:
            return []
        return [
            Trend(
                trend_type=TrendType.community_signal,
                category=TrendCategory.echo,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=_clamp(conf),
                confidence=_clamp(conf * 0.8),
                direction=0,
                evidence={"community_confidence": round(conf, 4)},
            )
        ]
