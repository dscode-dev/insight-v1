"""Foundational odds features.

Sprint scope: descriptive, no ML, no probability engine. We derive a
small set of foundational features from a match's odds history:

  home_odds, draw_odds, away_odds  — latest cross-bookmaker consensus
  odds_movement                    — direction of the last home move (-1/0/+1)
  odds_delta                       — magnitude of the last home move
  market_count                     — distinct markets observed
  bookmaker_count                  — distinct bookmakers observed

Consensus = mean across bookmakers; the home-price timeline is built by
forward-filling each bookmaker's most recent quote, so movement
reflects the market as a whole rather than a single book.
"""

from __future__ import annotations

from atlas.odds.models import OddsTick

H2H = "h2h"


def _mean(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _consensus_home_series(h2h: list[OddsTick]) -> list[float]:
    """Forward-filled cross-bookmaker home-odds consensus per snapshot
    instant, oldest→newest.
    """
    ordered = sorted(h2h, key=lambda t: t.captured_at)
    timestamps = sorted({t.captured_at for t in ordered})
    latest_by_book: dict[str, float] = {}
    series: list[float] = []
    for ts in timestamps:
        for t in ordered:
            if t.captured_at == ts and t.home is not None:
                latest_by_book[t.bookmaker] = t.home
        consensus = _mean(list(latest_by_book.values()))
        if consensus is not None:
            series.append(consensus)
    return series


def _latest_per_bookmaker(h2h: list[OddsTick]) -> list[OddsTick]:
    latest: dict[str, OddsTick] = {}
    for t in sorted(h2h, key=lambda t: t.captured_at):
        latest[t.bookmaker] = t
    return list(latest.values())


def build_odds_features(history: list[OddsTick]) -> dict[str, float]:
    """Compute foundational odds features from a match's full history."""
    features: dict[str, float] = {
        "home_odds": 0.0,
        "draw_odds": 0.0,
        "away_odds": 0.0,
        "odds_movement": 0.0,
        "odds_delta": 0.0,
        "market_count": 0.0,
        "bookmaker_count": 0.0,
    }
    if not history:
        return features

    features["market_count"] = float(len({t.market for t in history}))
    features["bookmaker_count"] = float(len({t.bookmaker for t in history}))

    h2h = [t for t in history if t.market == H2H]
    if not h2h:
        return features

    latest = _latest_per_bookmaker(h2h)
    home_consensus = _mean([t.home for t in latest if t.home is not None])
    draw_consensus = _mean([t.draw for t in latest if t.draw is not None])
    away_consensus = _mean([t.away for t in latest if t.away is not None])
    if home_consensus is not None:
        features["home_odds"] = home_consensus
    if draw_consensus is not None:
        features["draw_odds"] = draw_consensus
    if away_consensus is not None:
        features["away_odds"] = away_consensus

    series = _consensus_home_series(h2h)
    if len(series) >= 2:
        delta = series[-1] - series[-2]
        features["odds_delta"] = delta
        if delta > 0:
            features["odds_movement"] = 1.0
        elif delta < 0:
            features["odds_movement"] = -1.0
    return features
