"""Historical facts transformed into canonical IntelligenceSignal records."""

from __future__ import annotations

from datetime import datetime

from atlas.contracts import SourceRef, SourceType
from atlas.intelligence.contracts import (
    Evidence,
    EvidenceType,
    IntelligenceSignal,
    SignalType,
    UncertaintyInsight,
)
from atlas.intelligence.evidence_engine import EvidenceEngine
from atlas.intelligence.historical import HistoricalRecord, mean_feature, stable_id, summarize
from atlas.intelligence.kernel import Coverage, SignalID


class HistoricalSignalEngine:
    def __init__(self, evidence: EvidenceEngine | None = None) -> None:
        self._evidence = evidence or EvidenceEngine()

    def generate(
        self,
        rows: list[HistoricalRecord],
        *,
        scope_key: str,
        as_of: datetime,
        report_uncertainty: UncertaintyInsight,
        market_disagreement: float = 0.0,
        favorite_pressure: float = 0.0,
    ) -> list[IntelligenceSignal]:
        if not rows:
            return []
        stats = summarize(rows)
        recent = rows[-min(10, len(rows)) :]
        confidence = _confidence(len(rows), stats["source_count"])
        sources = _sources(rows, as_of)
        coverage = _coverage(sources)
        signals: list[IntelligenceSignal] = []

        signals.extend(
            [
                self._signal(
                    scope_key,
                    "home_form",
                    SignalType.form,
                    mean_feature(recent, "home_points_5"),
                    confidence,
                    self._fact(
                        scope_key,
                        EvidenceType.statistical,
                        "leakage-safe form projection",
                        (
                            f"mean home five-match points strength "
                            f"{mean_feature(recent, 'home_points_5'):.3f}"
                        ),
                        as_of,
                        confidence,
                        {"window_matches": len(recent)},
                    ),
                    report_uncertainty,
                    coverage,
                    sources,
                    as_of,
                ),
                self._signal(
                    scope_key,
                    "away_form",
                    SignalType.form,
                    mean_feature(recent, "away_points_5"),
                    confidence,
                    self._fact(
                        scope_key,
                        EvidenceType.statistical,
                        "leakage-safe form projection",
                        (
                            f"mean away five-match points strength "
                            f"{mean_feature(recent, 'away_points_5'):.3f}"
                        ),
                        as_of,
                        confidence,
                        {"window_matches": len(recent)},
                    ),
                    report_uncertainty,
                    coverage,
                    sources,
                    as_of,
                ),
            ]
        )
        form_gap = abs(mean_feature(recent, "form_strength_gap"))
        signals.append(
            self._signal(
                scope_key,
                "momentum",
                SignalType.momentum,
                min(1.0, form_gap),
                confidence,
                self._fact(
                    scope_key,
                    EvidenceType.behavioral,
                    "recent form comparison",
                    f"mean recent form-strength gap {form_gap:.3f}",
                    as_of,
                    confidence,
                    {"window_matches": len(recent)},
                ),
                report_uncertainty,
                coverage,
                sources,
                as_of,
            )
        )
        signals.append(
            self._signal(
                scope_key,
                "streak",
                SignalType.form,
                _streak_strength(recent),
                confidence,
                self._fact(
                    scope_key,
                    EvidenceType.historical,
                    "certified match outcomes",
                    f"longest repeated result in latest {len(recent)} matches",
                    as_of,
                    confidence,
                    {"streak_strength": round(_streak_strength(recent), 6)},
                ),
                report_uncertainty,
                coverage,
                sources,
                as_of,
            )
        )

        if stats["odds_coverage"] > 0:
            signals.extend(
                [
                    self._signal(
                        scope_key,
                        "favorite_pressure",
                        SignalType.market,
                        favorite_pressure,
                        confidence * stats["odds_coverage"],
                        self._fact(
                            scope_key,
                            EvidenceType.market,
                            "historical market projection",
                            f"favorite pressure {favorite_pressure:.3f}",
                            as_of,
                            confidence,
                            {"odds_coverage": stats["odds_coverage"]},
                        ),
                        report_uncertainty,
                        coverage,
                        sources,
                        as_of,
                    ),
                    self._signal(
                        scope_key,
                        "market_consensus",
                        SignalType.market,
                        max(0.0, 1.0 - market_disagreement),
                        confidence * stats["odds_coverage"],
                        self._fact(
                            scope_key,
                            EvidenceType.market,
                            "historical bookmaker observations",
                            f"market consensus {1.0 - market_disagreement:.3f}",
                            as_of,
                            confidence,
                            {"market_disagreement": market_disagreement},
                        ),
                        report_uncertainty,
                        coverage,
                        sources,
                        as_of,
                    ),
                    self._signal(
                        scope_key,
                        "market_disagreement",
                        SignalType.market,
                        market_disagreement,
                        confidence * stats["odds_coverage"],
                        self._fact(
                            scope_key,
                            EvidenceType.market,
                            "historical bookmaker observations",
                            f"market disagreement {market_disagreement:.3f}",
                            as_of,
                            confidence,
                            {"market_disagreement": market_disagreement},
                        ),
                        report_uncertainty,
                        coverage,
                        sources,
                        as_of,
                    ),
                ]
            )

        signals.extend(
            [
                self._signal(
                    scope_key,
                    "competition_volatility",
                    SignalType.volatility,
                    min(1.0, stats["goal_volatility"] / 2.5),
                    confidence,
                    self._fact(
                        scope_key,
                        EvidenceType.statistical,
                        "certified match outcomes",
                        f"goal-total standard deviation {stats['goal_volatility']:.3f}",
                        as_of,
                        confidence,
                        {"sample_size": len(rows)},
                    ),
                    report_uncertainty,
                    coverage,
                    sources,
                    as_of,
                ),
                self._signal(
                    scope_key,
                    "draw_tendency",
                    SignalType.behavior,
                    stats["draw_rate"],
                    confidence,
                    self._fact(
                        scope_key,
                        EvidenceType.historical,
                        "certified match outcomes",
                        f"{stats['draw_rate']:.1%} draw rate across {len(rows)} matches",
                        as_of,
                        confidence,
                        {"draw_rate": stats["draw_rate"], "sample_size": len(rows)},
                    ),
                    report_uncertainty,
                    coverage,
                    sources,
                    as_of,
                ),
                self._signal(
                    scope_key,
                    "scoring_tendency",
                    SignalType.behavior,
                    min(1.0, stats["goals_per_match"] / 4.0),
                    confidence,
                    self._fact(
                        scope_key,
                        EvidenceType.statistical,
                        "certified match outcomes",
                        f"{stats['goals_per_match']:.3f} goals per match",
                        as_of,
                        confidence,
                        {"sample_size": len(rows)},
                    ),
                    report_uncertainty,
                    coverage,
                    sources,
                    as_of,
                ),
                self._signal(
                    scope_key,
                    "defensive_instability",
                    SignalType.behavior,
                    min(
                        1.0,
                        (
                            mean_feature(recent, "home_goals_against_5")
                            + mean_feature(recent, "away_goals_against_5")
                        )
                        / 5.0,
                    ),
                    confidence,
                    self._fact(
                        scope_key,
                        EvidenceType.behavioral,
                        "leakage-safe goal history",
                        "recent goals-against rates for both match roles",
                        as_of,
                        confidence,
                        {"window_matches": len(recent)},
                    ),
                    report_uncertainty,
                    coverage,
                    sources,
                    as_of,
                ),
                self._signal(
                    scope_key,
                    "goal_distribution",
                    SignalType.behavior,
                    min(1.0, stats["goal_volatility"] / 2.5),
                    confidence,
                    self._fact(
                        scope_key,
                        EvidenceType.behavioral,
                        "certified goal totals",
                        (
                            f"mean {stats['goals_per_match']:.3f}, standard deviation "
                            f"{stats['goal_volatility']:.3f}"
                        ),
                        as_of,
                        confidence,
                        {"sample_size": len(rows)},
                    ),
                    report_uncertainty,
                    coverage,
                    sources,
                    as_of,
                ),
            ]
        )
        return signals

    def _fact(
        self,
        scope_key: str,
        evidence_type: EvidenceType,
        source: str,
        description: str,
        as_of: datetime,
        confidence: float,
        attributes: dict,
    ) -> Evidence:
        return self._evidence.create(
            scope_key=scope_key,
            evidence_type=evidence_type,
            source=source,
            description=description,
            observed_at=as_of,
            weight=0.8,
            confidence=confidence,
            attributes=attributes,
        )

    @staticmethod
    def _signal(
        scope_key: str,
        name: str,
        signal_type: SignalType,
        strength: float,
        confidence: float,
        evidence: Evidence,
        uncertainty: UncertaintyInsight,
        coverage: Coverage,
        sources: list[SourceRef],
        as_of: datetime,
    ) -> IntelligenceSignal:
        return IntelligenceSignal(
            signal_id=SignalID(stable_id(scope_key, "signal", name)),
            signal_name=name,
            signal_type=signal_type,
            strength=round(_clamp(strength), 6),
            confidence=round(_clamp(confidence), 6),
            uncertainty=uncertainty,
            evidence=[evidence],
            coverage=coverage,
            sources=sources,
            created_at=as_of,
        )


def _confidence(sample_size: int, source_count: int) -> float:
    return min(0.95, 0.4 + 0.4 * min(1.0, sample_size / 100) + 0.15 * min(1.0, source_count / 2))


def _coverage(sources: list[SourceRef]) -> Coverage:
    count = len(sources)
    expected = max(2, count)
    return Coverage(
        expected=expected,
        observed=count,
        ratio=count / expected,
        source_count=count,
    )


def _sources(rows: list[HistoricalRecord], as_of: datetime) -> list[SourceRef]:
    names = sorted({source for row in rows for source in row.sources})
    return [
        SourceRef(
            source_id=name[:64],
            source_name=name,
            source_type=SourceType.internal_bot,
            confidence=0.8,
            observed_at=as_of,
            metadata={"dataset_role": "certified historical observation"},
        )
        for name in names
    ]


def _streak_strength(rows: list[HistoricalRecord]) -> float:
    longest = current = 0
    previous = None
    for row in rows:
        if row.label == previous:
            current += 1
        else:
            previous = row.label
            current = 1
        longest = max(longest, current)
    return min(1.0, longest / max(len(rows), 1))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
