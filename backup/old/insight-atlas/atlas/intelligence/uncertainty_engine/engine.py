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
        # NOTE: the old `else` branch appended `max(0.0, 0.5 - odds_coverage)`,
        # which is ALWAYS exactly 0.0 here (this branch means
        # odds_coverage >= 0.5). Under the previous mean-based combiner
        # that dead component still diluted the average; it is removed
        # rather than kept as a no-op that silently lowers uncertainty.

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

        # Saturating (noisy-OR) combiner, NOT a mean. Averaging
        # heterogeneous deficiencies made the score NON-MONOTONIC:
        # every additional problem grew the denominator, so adding a
        # smaller deficiency DILUTED a larger one. Measured on the old
        # code: "no odds" scored 1.00, while "no odds AND only one
        # source" — strictly worse data — scored 0.75. Uncertainty fed
        # behaviour-pattern confidence, the reasoning graph's `weakens`
        # edge weight and the published explanation, so a report with
        # fewer problems could look more uncertain than one with more.
        # 1 - Π(1 - cᵢ) is monotonic by construction: each component can
        # only ever push the score up, never down.
        score = 1.0
        for component in components:
            score *= 1.0 - max(0.0, min(1.0, component))
        score = min(1.0, 1.0 - score)
        return UncertaintyInsight(
            insight_id=InsightID(stable_id(scope_key, "uncertainty")),
            uncertainty_score=round(score, 6),
            missing_signals=missing,
            conflicting_signals=conflicts,
            low_coverage=odds_coverage < 0.5 or source_count < 2 or sample_size < 25,
            recommendations=list(dict.fromkeys(recommendations)),
            created_at=created_at,
        )
