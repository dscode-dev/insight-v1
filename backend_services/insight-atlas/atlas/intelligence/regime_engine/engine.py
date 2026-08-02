"""Evidence-based structural regime intelligence."""

from __future__ import annotations

from atlas.intelligence.contracts import RegimeInsight, RegimeType
from atlas.intelligence.historical import HistoricalRecord, stable_id, summarize
from atlas.intelligence.kernel import RegimeID

_LEAGUES = {
    "premier_league",
    "la_liga",
    "serie_a",
    "bundesliga",
    "ligue_1",
    "brasileirao_serie_a",
}
_CONTINENTAL = {
    "champions_league",
    "europa_league",
    "libertadores",
    "sudamericana",
}
_INTERNATIONAL = {"world_cup", "euro", "copa_america"}


class HistoricalRegimeEngine:
    def classify(
        self, rows: list[HistoricalRecord], *, competition: str, scope_key: str
    ) -> RegimeInsight:
        stats = summarize(rows)
        if competition in _LEAGUES:
            regime_type = RegimeType.league
        elif competition in _CONTINENTAL:
            regime_type = RegimeType.continental
        elif competition in _INTERNATIONAL:
            regime_type = RegimeType.international
        else:
            regime_type = RegimeType.low_information

        characteristics = [
            f"draw rate {stats['draw_rate']:.1%}",
            f"goal volatility {stats['goal_volatility']:.3f}",
            f"market coverage {stats['odds_coverage']:.1%}",
        ]
        expected = [
            (
                "higher draw behavior"
                if stats["draw_rate"] >= 0.28
                else "lower draw behavior"
            ),
            (
                "higher volatility"
                if stats["goal_volatility"] >= 1.8
                else "more stable scoring"
            ),
            (
                "higher market efficiency"
                if stats["odds_coverage"] >= 0.75
                else "market efficiency cannot be established"
            ),
            (
                "higher confidence"
                if stats["odds_coverage"] >= 0.5 and len(rows) >= 100
                else "lower confidence"
            ),
        ]
        risks = []
        if stats["odds_coverage"] < 0.5:
            risks.append("low market coverage")
        if len(rows) < 100:
            risks.append("limited regime sample")
        if competition in _INTERNATIONAL:
            risks.append("short tournament and opponent-composition shifts")
        confidence = min(
            0.95,
            0.45
            + 0.35 * min(1.0, len(rows) / 100)
            + 0.2 * stats["odds_coverage"],
        )
        return RegimeInsight(
            regime_id=RegimeID(stable_id(scope_key, "regime", regime_type.value)),
            regime_type=regime_type,
            confidence=round(confidence, 6),
            characteristics=characteristics,
            expected_behavior=expected,
            risk_factors=risks,
        )

