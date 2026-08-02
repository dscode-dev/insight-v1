"""The four continuous watchers — Sprint 3.6 Parts 3-6.

Each watcher observes EVOLVING state over its window and assembles
Observations (trend inputs + synthetic signals). Detection of the
resulting TRENDS is delegated to the existing detectors through the
standard pipeline — no duplicated logic. The watcher's own thresholds
only govern when a synthetic SIGNAL is worth attaching (deterministic
series math: drift, monotonic growth, accumulation).
"""

from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

from datetime import timedelta

from atlas.market import MarketStateEngine
from atlas.odds.repository import OddsRepository
from atlas.signal_engine import Signal, SignalOrigin, SignalType
from atlas.trends.models import TrendInputs
from atlas.trends.ninja import _consensus_prob_points
from atlas.watchers.base import Observation
from atlas.watchers.series import Sample, SeriesStore

logger = logging.getLogger(__name__)


def _monotonic_growth(samples: list[Sample], *, min_points: int) -> float | None:
    """Total growth across a (mostly) monotonically rising series; None
    when the series is too short or not rising. Deterministic: rising
    means every consecutive step is non-decreasing and the net change
    is positive (55→60→66→71→76)."""
    if len(samples) < min_points:
        return None
    values = [s.value for s in samples]
    for prev, cur in zip(values, values[1:]):
        if cur < prev:
            return None
    growth = values[-1] - values[0]
    return growth if growth > 0 else None


def _synthetic(
    signal_type: SignalType,
    match_id: UUID,
    confidence: float,
    impact: str,
    metadata: dict,
) -> Signal:
    return Signal(
        signal_type=signal_type,
        canonical_match_id=match_id,
        confidence=confidence,
        impact=impact,
        origin=SignalOrigin.synthetic,
        metadata=metadata,
    )


# --- Part 3: MarketWatcher ----------------------------------------------------


class MarketWatcher:
    """Observes the persisted odds timeline per recently active match.
    Trend detection (shift/acceleration/divergence/anomaly/deviation +
    the Magnus-absorption market-intelligence trends) is the existing
    detectors' job — the watcher feeds them the full history AND the
    market_state now/prior pair on a schedule, so GRADUAL movements
    (drift, consensus shifts, volatility growth, confidence decay)
    that never crossed the Hub's change gate in one step still get
    evaluated. Synthetic ODDS_SHIFT signals are attached when the
    window shows meaningful market behavior."""

    def __init__(
        self,
        odds: OddsRepository,
        store: SeriesStore,
        *,
        window_seconds: int = 1800,
        drift_threshold: float = 0.03,
        consensus_shift_threshold: float = 0.10,
        volatility_growth_threshold: float = 0.15,
        sharp_score_threshold: float = 0.6,
        enabled: bool = True,
        max_matches: int = 50,
        market_engine: MarketStateEngine | None = None,
    ) -> None:
        self._odds = odds
        self._store = store
        self._window = window_seconds
        self._drift = drift_threshold
        self._consensus_shift = consensus_shift_threshold
        self._volatility_growth = volatility_growth_threshold
        self._sharp_score = sharp_score_threshold
        self._enabled = enabled
        self._max = max_matches
        # Metrics are observed on the event path; the watcher pass
        # reuses the engines without double-counting score samples.
        self._market = market_engine or MarketStateEngine(observe_metrics=False)

    def name(self) -> str:
        return "market"

    def enabled(self) -> bool:
        return self._enabled

    def _market_states(
        self, history: list
    ) -> tuple[dict | None, dict | None]:
        """market_state over the full window vs over the first half of
        it — the prior/now pair the market-intelligence detectors
        compare. Deterministic: split at latest_ts - window/2."""
        if not history:
            return None, None
        latest_ts = max(t.captured_at for t in history)
        cutoff = latest_ts - timedelta(seconds=self._window / 2)
        earlier = [t for t in history if t.captured_at <= cutoff]
        now_state = self._market.compute(history).as_dict()
        prior_state = (
            self._market.compute(earlier).as_dict() if earlier else None
        )
        return now_state, prior_state

    def _market_signals(
        self,
        match_id,
        now_state: dict | None,
        prior_state: dict | None,
    ) -> list[Signal]:
        """Synthetic signals for meaningful market behavior emerging
        WITHOUT a new sports event: sharp movement, consensus shifts,
        gradual volatility growth."""
        if not now_state:
            return []
        signals: list[Signal] = []
        sharp = now_state.get("sharp_movement_score")
        if isinstance(sharp, (int, float)) and sharp >= self._sharp_score:
            signals.append(_synthetic(
                SignalType.ODDS_SHIFT, match_id,
                confidence=min(1.0, float(sharp)),
                impact="HIGH",
                metadata={"kind": "sharp_market_move",
                          "sharp_movement_score": round(float(sharp), 4),
                          "watcher": self.name()},
            ))
        if prior_state:
            for key, threshold, kind in (
                ("consensus_score", self._consensus_shift, "consensus_shift"),
                ("volatility_score", self._volatility_growth, "volatility_growth"),
            ):
                a, b = prior_state.get(key), now_state.get(key)
                if (
                    isinstance(a, (int, float))
                    and isinstance(b, (int, float))
                    and abs(float(b) - float(a)) >= threshold
                ):
                    signals.append(_synthetic(
                        SignalType.ODDS_SHIFT, match_id,
                        confidence=min(1.0, 0.5 + abs(float(b) - float(a))),
                        impact="MEDIUM",
                        metadata={"kind": kind,
                                  f"{key}_prev": round(float(a), 4),
                                  f"{key}_now": round(float(b), 4),
                                  "watcher": self.name()},
                    ))
        return signals

    async def observe(self) -> list[Observation]:
        matches = await self._store.recent_matches(window_seconds=self._window)
        out: list[Observation] = []
        for match_id in matches[: self._max]:
            history = await self._odds.history(match_id)
            if len(history) < 2:
                continue
            inputs = TrendInputs(
                canonical_match_id=match_id, odds_history=history
            )
            signals: list[Signal] = []
            points = _consensus_prob_points(inputs)
            if len(points) >= 2:
                drift = points[-1][1] - points[0][1]
                if abs(drift) >= self._drift:
                    signals.append(_synthetic(
                        SignalType.ODDS_SHIFT, match_id,
                        confidence=min(1.0, 0.5 + abs(drift)),
                        impact="HIGH",
                        metadata={"drift": round(drift, 4),
                                  "window_seconds": self._window,
                                  "watcher": self.name()},
                    ))
            now_state, prior_state = self._market_states(history)
            signals.extend(
                self._market_signals(match_id, now_state, prior_state)
            )
            out.append(Observation(
                inputs=TrendInputs(
                    canonical_match_id=match_id,
                    odds_history=history,
                    context={"market_state": now_state} if now_state else None,
                    prior_context=(
                        {"market_state": prior_state} if prior_state else None
                    ),
                    signals=signals,
                ),
                signals=signals,
            ))
        return out


# --- Part 4: MatchWatcher -------------------------------------------------------


class MatchWatcher:
    """Observes recorded stat series (possession, shots, dangerous
    attacks, pressure). 55→60→66→71→76 with no event = sustained
    growth → synthetic PRESSURE_SPIKE, plus pulse-detector inputs so
    pressure_building / dominance_pattern trends emerge."""

    GROWTH_SERIES = ("possession_home", "dangerous_attacks_home", "shots_home")

    def __init__(
        self,
        store: SeriesStore,
        *,
        window_seconds: int = 900,
        min_points: int = 3,
        possession_growth: float = 10.0,
        enabled: bool = True,
        max_matches: int = 50,
    ) -> None:
        self._store = store
        self._window = window_seconds
        self._min_points = min_points
        self._growth = possession_growth
        self._enabled = enabled
        self._max = max_matches

    def name(self) -> str:
        return "match"

    def enabled(self) -> bool:
        return self._enabled

    async def observe(self) -> list[Observation]:
        matches = await self._store.recent_matches(window_seconds=self._window)
        out: list[Observation] = []
        for match_id in matches[: self._max]:
            signals: list[Signal] = []
            stats: dict[str, float] = {}
            for series in self.GROWTH_SERIES:
                samples = await self._store.series(
                    match_id, series, window_seconds=self._window
                )
                if not samples:
                    continue
                stats[series] = samples[-1].value
                away = series.replace("_home", "_away")
                away_samples = await self._store.series(
                    match_id, away, window_seconds=self._window
                )
                if away_samples:
                    stats[away] = away_samples[-1].value
                growth = _monotonic_growth(samples, min_points=self._min_points)
                if growth is not None and growth >= self._growth:
                    signals.append(_synthetic(
                        SignalType.PRESSURE_SPIKE, match_id,
                        confidence=min(1.0, 0.55 + growth / 100.0),
                        impact="HIGH",
                        metadata={"series": series,
                                  "growth": round(growth, 2),
                                  "points": len(samples),
                                  "watcher": self.name()},
                    ))
            if not signals and not stats:
                continue
            out.append(Observation(
                inputs=TrendInputs(
                    canonical_match_id=match_id,
                    match_stats=stats or None,
                    signals=signals,
                ),
                signals=signals,
            ))
        return out


# --- Part 5: RiskWatcher ----------------------------------------------------------


class RiskWatcher:
    """Observes accumulating disciplinary/instability events (cards,
    fouls, injuries) recorded as unit samples in the risk series.
    Accumulation past the window threshold → synthetic MOMENTUM_SWING
    risk signal (disciplinary pressure destabilising the match)."""

    RISK_SERIES = ("risk_yellow_card", "risk_red_card", "risk_foul", "risk_injury")
    WEIGHTS = {"risk_yellow_card": 1.0, "risk_red_card": 3.0,
               "risk_foul": 0.25, "risk_injury": 2.0}

    def __init__(
        self,
        store: SeriesStore,
        *,
        window_seconds: int = 900,
        accumulation_threshold: float = 4.0,
        enabled: bool = True,
        max_matches: int = 50,
    ) -> None:
        self._store = store
        self._window = window_seconds
        self._threshold = accumulation_threshold
        self._enabled = enabled
        self._max = max_matches

    def name(self) -> str:
        return "risk"

    def enabled(self) -> bool:
        return self._enabled

    async def observe(self) -> list[Observation]:
        matches = await self._store.recent_matches(window_seconds=self._window)
        out: list[Observation] = []
        for match_id in matches[: self._max]:
            accumulation = 0.0
            counts: dict[str, int] = {}
            for series in self.RISK_SERIES:
                samples = await self._store.series(
                    match_id, series, window_seconds=self._window
                )
                if samples:
                    counts[series] = len(samples)
                    accumulation += len(samples) * self.WEIGHTS[series]
            if accumulation < self._threshold:
                continue
            signal = _synthetic(
                SignalType.MOMENTUM_SWING, match_id,
                confidence=min(1.0, 0.5 + accumulation / 20.0),
                impact="HIGH",
                metadata={"accumulation": round(accumulation, 2),
                          "counts": counts,
                          "window_seconds": self._window,
                          "watcher": self.name()},
            )
            out.append(Observation(
                inputs=TrendInputs(
                    canonical_match_id=match_id,
                    signals=[signal],
                    impact_label="MEDIUM",
                    impact_category="pressure_change",
                ),
                signals=[signal],
            ))
        return out


# --- Part 6: NarrativeWatcher ----------------------------------------------------


class LowTrustSignalSource(Protocol):
    """Future Explorer integration seam — interface only (the spec
    forbids implementing the integration this sprint). A source returns
    numeric low-trust narrative intensities per match."""

    async def intensity(self, match_id: UUID) -> float | None: ...


class NullLowTrustSource:
    """The Atlas-side default until Explorer exists."""

    async def intensity(self, match_id: UUID) -> float | None:  # noqa: ARG002
        return None


class NarrativeWatcher:
    """Observes the recorded narrative feature series (sentiment,
    community confidence). Growing consensus across the window →
    synthetic MOMENTUM_SWING narrative signal; the echo detectors run
    on the latest features either way."""

    def __init__(
        self,
        store: SeriesStore,
        *,
        low_trust: LowTrustSignalSource | None = None,
        window_seconds: int = 1800,
        consensus_growth: float = 0.2,
        min_points: int = 3,
        enabled: bool = True,
        max_matches: int = 50,
    ) -> None:
        self._store = store
        self._low_trust = low_trust or NullLowTrustSource()
        self._window = window_seconds
        self._growth = consensus_growth
        self._min_points = min_points
        self._enabled = enabled
        self._max = max_matches

    def name(self) -> str:
        return "narrative"

    def enabled(self) -> bool:
        return self._enabled

    async def observe(self) -> list[Observation]:
        matches = await self._store.recent_matches(window_seconds=self._window)
        out: list[Observation] = []
        for match_id in matches[: self._max]:
            community = await self._store.series(
                match_id, "community_confidence", window_seconds=self._window
            )
            sentiment = await self._store.series(
                match_id, "sentiment_delta", window_seconds=self._window
            )
            if not community and not sentiment:
                continue
            features: dict[str, float] = {}
            if community:
                features["community_confidence"] = community[-1].value
            if sentiment:
                features["sentiment_delta"] = sentiment[-1].value
            signals: list[Signal] = []
            growth = _monotonic_growth(community, min_points=self._min_points)
            if growth is not None and growth >= self._growth:
                signals.append(_synthetic(
                    SignalType.MOMENTUM_SWING, match_id,
                    confidence=min(1.0, 0.5 + growth),
                    impact="MEDIUM",
                    metadata={"series": "community_confidence",
                              "growth": round(growth, 4),
                              "watcher": self.name()},
                ))
            out.append(Observation(
                inputs=TrendInputs(
                    canonical_match_id=match_id,
                    features=features,
                    signals=signals,
                ),
                signals=signals,
            ))
        return out
