"""Uncertainty decomposition for historical intelligence reports."""

from __future__ import annotations

from datetime import datetime

from atlas.intelligence.contracts import UncertaintyInsight
from atlas.intelligence.historical import stable_id
from atlas.intelligence.kernel import InsightID


class UncertaintyEngine:
    def assess(
        self,
        *,
        scope_key: str,
        sample_size: int,
        odds_coverage: float,
        source_count: int,
        market_disagreement: float,
        conflicting_signals: list[str] | None,
        unavailable_signals: list[str] | None = None,
        created_at: datetime,
    ) -> UncertaintyInsight:
        missing: list[str] = []
        recommendations: list[str] = []
        components: list[float] = []

        if odds_coverage <= 0:
            missing.append("market odds")
            recommendations.append("add historical opening and closing odds")
            components.append(1.0)
        elif odds_coverage < 0.5:
            missing.append("complete market coverage")
            recommendations.append("increase market coverage above 50%")
            components.append(1.0 - odds_coverage)
        else:
            components.append(max(0.0, 0.5 - odds_coverage))

        if sample_size < 25:
            missing.append("sufficient historical sample")
            recommendations.append("increase the historical sample to at least 25 matches")
            components.append(1.0 - sample_size / 25.0)
        elif sample_size < 100:
            components.append((100 - sample_size) / 150.0)

        if source_count < 2:
            missing.append("corroborating source")
            recommendations.append("add a second reconciled source")
            components.append(0.5)

        if market_disagreement > 0.55:
            components.append(min(1.0, market_disagreement))

        conflicts = list(dict.fromkeys(conflicting_signals or []))
        if conflicts:
            recommendations.append("review conflicting signals before operational use")
            components.append(min(1.0, 0.2 * len(conflicts)))

        for signal in unavailable_signals or []:
            missing.append(signal)
            recommendations.append(f"add historical inputs for {signal}")
            components.append(0.35)

        score = min(1.0, sum(components) / max(len(components), 1))
        return UncertaintyInsight(
            insight_id=InsightID(stable_id(scope_key, "uncertainty")),
            uncertainty_score=round(score, 6),
            missing_signals=missing,
            conflicting_signals=conflicts,
            low_coverage=odds_coverage < 0.5 or source_count < 2 or sample_size < 25,
            recommendations=list(dict.fromkeys(recommendations)),
            created_at=created_at,
        )
