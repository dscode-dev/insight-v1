"""IntelligenceWatcher — Maturity Sprint 1.5 Part 11.

Continuously monitors the maturity layer per active competition:

  * competition state (CompetitionProfile)
  * regime changes (append-only history; synthetic signal on change)
  * meta-trend emergence (recurrence aggregates → MetaTrendDetector)
  * cross-match anomalies (synthetic signal on abnormal uncertainty)

The watcher follows the established doctrine: it ASSEMBLES the
intelligence_state context block (engines own the queries, detectors
own the thresholds) and feeds it through the same trend pipeline.
Observations are anchored on the competition's most recent match.
"""

from __future__ import annotations

import logging

from atlas.intelligence.competition import CompetitionIntelligenceEngine
from atlas.intelligence.crossmatch import CrossMatchEngine
from atlas.intelligence.meta_trends import MetaTrendEngine
from atlas.intelligence.regimes import RegimeEngine
from atlas.signal_engine import Signal, SignalOrigin, SignalType
from atlas.trends.models import TrendInputs
from atlas.watchers.base import Observation

logger = logging.getLogger(__name__)


class IntelligenceWatcher:
    def __init__(
        self,
        competition: CompetitionIntelligenceEngine,
        regimes: RegimeEngine,
        meta: MetaTrendEngine,
        crossmatch: CrossMatchEngine,
        *,
        uncertainty_anomaly_rate: float = 0.5,
        uncertainty_min_matches: int = 3,
        enabled: bool = True,
        max_competitions: int = 10,
    ) -> None:
        self._competition = competition
        self._regimes = regimes
        self._meta = meta
        self._crossmatch = crossmatch
        self._uncertainty_rate = uncertainty_anomaly_rate
        self._uncertainty_matches = uncertainty_min_matches
        self._enabled = enabled
        self._max = max_competitions

    def name(self) -> str:
        return "intelligence"

    def enabled(self) -> bool:
        return self._enabled

    async def observe(self) -> list[Observation]:
        out: list[Observation] = []
        competitions = await self._competition.active_competitions(
            limit=self._max
        )
        for competition_id in competitions:
            profile = await self._competition.profile(competition_id)
            if profile is None:
                continue
            anchor = await self._competition.latest_match(competition_id)
            if anchor is None:
                continue
            regime, changed = await self._regimes.observe(profile)
            scan = await self._meta.scan_competition(competition_id)
            cross = await self._crossmatch.competition_profile(competition_id)

            signals: list[Signal] = []
            if changed:
                signals.append(Signal(
                    signal_type=SignalType.ODDS_SHIFT,
                    canonical_match_id=anchor,
                    confidence=0.7,
                    impact="MEDIUM",
                    origin=SignalOrigin.synthetic,
                    metadata={"kind": "regime_change",
                              "regime": regime.value,
                              "competition_id": str(competition_id),
                              "watcher": self.name()},
                ))
            if (
                cross.matches >= self._uncertainty_matches
                and cross.uncertainty_rate >= self._uncertainty_rate
            ):
                signals.append(Signal(
                    signal_type=SignalType.ODDS_SHIFT,
                    canonical_match_id=anchor,
                    confidence=min(1.0, 0.5 + cross.uncertainty_rate / 2),
                    impact="MEDIUM",
                    origin=SignalOrigin.synthetic,
                    metadata={"kind": "crossmatch_uncertainty_anomaly",
                              "uncertainty_rate": round(cross.uncertainty_rate, 4),
                              "matches": cross.matches,
                              "watcher": self.name()},
                ))

            intelligence_state = {
                "meta": scan.to_state(),
                "competition_profile": profile.to_wire(),
                "regime": regime.value,
                "regime_changed": changed,
                "crossmatch": cross.to_wire(),
            }
            out.append(Observation(
                inputs=TrendInputs(
                    canonical_match_id=anchor,
                    competition_id=competition_id,
                    context={"intelligence_state": intelligence_state},
                    signals=signals,
                ),
                signals=signals,
            ))
        return out
