"""Leakage-safe hierarchical retrieval over certified historical records."""

from __future__ import annotations

import statistics
from collections import Counter

from atlas.intelligence.contracts import EvidenceType, SimilarMatch
from atlas.intelligence.evidence_engine import EvidenceEngine
from atlas.intelligence.historical import (
    HistoricalDataset,
    HistoricalRecord,
    stable_id,
)
from atlas.intelligence.similarity_engine import (
    HistoricalMemory,
    profile_from_record,
)
from atlas.intelligence.similarity_engine.engine import structural_regime
from atlas.memory.contracts import (
    BehaviorMemory,
    CompetitionMemory,
    HeadToHeadMemory,
    HierarchicalMemoryInsight,
    MemoryConfidence,
    MemoryLayer,
    TeamMemoryProfile,
    TeamRoleBehavior,
)

RETRIEVAL_ORDER = [
    MemoryLayer.head_to_head,
    MemoryLayer.home_team,
    MemoryLayer.away_team,
    MemoryLayer.competition,
    MemoryLayer.behavior,
    MemoryLayer.generic_similarity,
]


class HierarchicalMemoryRetrievalEngine:
    def __init__(
        self,
        dataset: HistoricalDataset,
        evidence: EvidenceEngine | None = None,
    ) -> None:
        self._dataset = dataset
        self._evidence = evidence or EvidenceEngine()
        self._similarity = HistoricalMemory(dataset)

    def retrieve(
        self,
        query: HistoricalRecord,
        *,
        minimum_similarity: float = 0.97,
        generic_limit: int = 50,
    ) -> HierarchicalMemoryInsight:
        prior = [
            row
            for row in self._dataset.records
            if row.uid != query.uid and row.kickoff_at < query.kickoff_at
        ]
        competition_rows = [
            row for row in prior if row.competition == query.competition
        ]
        h2h_rows = [
            row
            for row in competition_rows
            if {row.home, row.away} == {query.home, query.away}
        ]
        home_rows = [
            row
            for row in competition_rows
            if query.home in {row.home, row.away}
        ]
        away_rows = [
            row
            for row in competition_rows
            if query.away in {row.home, row.away}
        ]

        h2h = self._head_to_head(query, h2h_rows)
        home_memory = self._team_profile(query.home, query, home_rows)
        away_memory = self._team_profile(query.away, query, away_rows)
        competition_memory = self._competition(query, competition_rows)

        all_generic_hits = [
            hit
            for hit in self._similarity.retrieve_similar_contexts(
                profile_from_record(query),
                minimum_score=minimum_similarity,
            )
            if hit.record.competition == query.competition
        ]
        generic_hits = all_generic_hits[:generic_limit]
        behavior_hits = [
            hit
            for hit in all_generic_hits
            if query.home in {hit.record.home, hit.record.away}
            or query.away in {hit.record.home, hit.record.away}
        ][:generic_limit]
        behavior = self._behavior(query, behavior_hits, minimum_similarity)
        generic = [self._similar_match(hit) for hit in generic_hits]
        confidence = self._confidence(
            query, h2h_rows, home_rows, away_rows, competition_rows
        )
        evidence = _unique(
            [
                *h2h.evidence,
                *home_memory.evidence,
                *away_memory.evidence,
                *competition_memory.evidence,
                *behavior.evidence,
            ]
        )
        return HierarchicalMemoryInsight(
            query_match_id=stable_id("match", query.uid),
            home_team=query.home,
            away_team=query.away,
            competition=query.competition,
            as_of=query.kickoff_at,
            retrieval_order=RETRIEVAL_ORDER,
            head_to_head=h2h,
            home_team_memory=home_memory,
            away_team_memory=away_memory,
            competition_memory=competition_memory,
            behavior_memory=behavior,
            generic_similarity=generic,
            memory_confidence=confidence,
            evidence=evidence,
        )

    def _head_to_head(
        self, query: HistoricalRecord, rows: list[HistoricalRecord]
    ) -> HeadToHeadMemory:
        home_wins = away_wins = draws = 0
        for row in rows:
            if row.label == "DRAW":
                draws += 1
            else:
                winner = row.home if row.label == "HOME_WIN" else row.away
                if winner == query.home:
                    home_wins += 1
                elif winner == query.away:
                    away_wins += 1
        goals = _mean([row.total_goals for row in rows])
        trends, behaviors = _context_labels(rows)
        confidence = _coverage(len(rows), 8)
        evidence = [
            self._evidence.create(
                scope_key=f"{query.uid}:h2h",
                evidence_type=EvidenceType.historical,
                source="certified historical matchup memory",
                description=(
                    f"{query.home} vs {query.away}: {len(rows)} strictly prior "
                    f"{query.competition} matches"
                ),
                observed_at=query.kickoff_at,
                weight=1.0,
                confidence=confidence,
                attributes={
                    "layer": MemoryLayer.head_to_head.value,
                    "strictly_prior": True,
                    "same_competition": True,
                    "draws": draws,
                    "goals_per_match": round(goals, 6),
                },
            )
        ]
        return HeadToHeadMemory(
            home_team_id=stable_id("team", query.home),
            away_team_id=stable_id("team", query.away),
            home_team=query.home,
            away_team=query.away,
            competition=query.competition,
            matches=len(rows),
            home_team_wins=home_wins,
            away_team_wins=away_wins,
            draws=draws,
            goals=round(goals, 6),
            trends=trends,
            behaviors=behaviors,
            evidence=evidence,
        )

    def _team_profile(
        self,
        team: str,
        query: HistoricalRecord,
        rows: list[HistoricalRecord],
    ) -> TeamMemoryProfile:
        home_rows = [row for row in rows if row.home == team]
        away_rows = [row for row in rows if row.away == team]
        goals_for = [
            row.home_score if row.home == team else row.away_score for row in rows
        ]
        goals_against = [
            row.away_score if row.home == team else row.home_score for row in rows
        ]
        draw_rate = (
            sum(row.label == "DRAW" for row in rows) / len(rows) if rows else 0.0
        )
        totals = [row.total_goals for row in rows]
        volatility = min(
            1.0, statistics.pstdev(totals) / 3.0 if len(totals) > 1 else 0.0
        )
        trends, _ = _context_labels(rows)
        confidence = _coverage(len(rows), 20)
        evidence = [
            self._evidence.create(
                scope_key=f"{query.uid}:team:{team}",
                evidence_type=EvidenceType.historical,
                source="certified historical team memory",
                description=(
                    f"{team}: {len(rows)} strictly prior {query.competition} "
                    f"matches, {draw_rate:.1%} draws"
                ),
                observed_at=query.kickoff_at,
                weight=0.9,
                confidence=confidence,
                attributes={
                    "layer": (
                        MemoryLayer.home_team.value
                        if team == query.home
                        else MemoryLayer.away_team.value
                    ),
                    "team_participation_required": True,
                    "strictly_prior": True,
                    "same_competition": True,
                },
            )
        ]
        return TeamMemoryProfile(
            team_id=stable_id("team", team),
            team=team,
            competition=query.competition,
            regime=structural_regime(query.competition),
            matches=len(rows),
            draw_rate=round(draw_rate, 6),
            goals_for=round(_mean(goals_for), 6),
            goals_against=round(_mean(goals_against), 6),
            home_behavior=_role_behavior(home_rows, team),
            away_behavior=_role_behavior(away_rows, team),
            volatility=round(volatility, 6),
            trends=trends,
            evidence=evidence,
        )

    def _competition(
        self, query: HistoricalRecord, rows: list[HistoricalRecord]
    ) -> CompetitionMemory:
        draw_rate = (
            sum(row.label == "DRAW" for row in rows) / len(rows) if rows else 0.0
        )
        totals = [row.total_goals for row in rows]
        volatility = min(
            1.0, statistics.pstdev(totals) / 3.0 if len(totals) > 1 else 0.0
        )
        trends, _ = _context_labels(rows)
        evidence = [
            self._evidence.create(
                scope_key=f"{query.uid}:competition",
                evidence_type=EvidenceType.regime,
                source="certified competition memory",
                description=(
                    f"{query.competition}: {len(rows)} strictly prior matches"
                ),
                observed_at=query.kickoff_at,
                weight=0.75,
                confidence=_coverage(len(rows), 100),
                attributes={
                    "layer": MemoryLayer.competition.value,
                    "strictly_prior": True,
                    "same_competition": True,
                },
            )
        ]
        return CompetitionMemory(
            competition=query.competition,
            regime=structural_regime(query.competition),
            matches=len(rows),
            draw_rate=round(draw_rate, 6),
            goals_per_match=round(_mean(totals), 6),
            volatility=round(volatility, 6),
            trends=trends,
            evidence=evidence,
        )

    def _behavior(self, query, hits, threshold: float) -> BehaviorMemory:
        matches = [self._similar_match(hit) for hit in hits]
        patterns = Counter(
            pattern for hit in hits for pattern in hit.shared_patterns
        )
        shared = sorted(
            name
            for name, count in patterns.items()
            if count >= max(1, int(len(hits) * 0.4))
        )
        average = _mean([hit.score for hit in hits])
        evidence = [
            self._evidence.create(
                scope_key=f"{query.uid}:behavior-memory",
                evidence_type=EvidenceType.behavioral,
                source="team-participating deterministic similarity",
                description=(
                    f"{len(hits)} behavior analogues include at least one "
                    "query team"
                ),
                observed_at=query.kickoff_at,
                weight=0.7,
                confidence=min(0.95, average * _coverage(len(hits), 10)),
                attributes={
                    "layer": MemoryLayer.behavior.value,
                    "team_participation_required": True,
                    "same_competition": True,
                    "minimum_similarity": threshold,
                },
            )
        ]
        return BehaviorMemory(
            matches=matches,
            threshold=threshold,
            average_similarity=round(average, 6),
            shared_behaviors=shared,
            evidence=evidence,
        )

    def _confidence(self, query, h2h, home, away, competition) -> MemoryConfidence:
        h2h_score = _coverage(len(h2h), 8)
        home_score = _coverage(len(home), 20)
        away_score = _coverage(len(away), 20)
        competition_score = _coverage(len(competition), 100)
        dates = [
            row.kickoff_at
            for row in {row.uid: row for row in [*home, *away]}.values()
        ]
        depth = (
            min(1.0, (max(dates) - min(dates)).days / (5 * 365))
            if len(dates) > 1
            else 0.0
        )
        overall = min(
            0.95,
            0.35 * h2h_score
            + 0.20 * home_score
            + 0.20 * away_score
            + 0.15 * competition_score
            + 0.10 * depth,
        )
        reasons = []
        if h2h_score < 0.5:
            reasons.append("limited head-to-head history")
        if min(home_score, away_score) < 0.5:
            reasons.append("limited team history")
        if competition_score < 0.5:
            reasons.append("limited competition history")
        if depth < 0.5:
            reasons.append("limited historical depth")
        return MemoryConfidence(
            h2h_coverage=round(h2h_score, 6),
            home_team_coverage=round(home_score, 6),
            away_team_coverage=round(away_score, 6),
            competition_coverage=round(competition_score, 6),
            historical_depth=round(depth, 6),
            overall=round(overall, 6),
            uncertainty=round(1.0 - overall, 6),
            reasons=reasons,
        )

    @staticmethod
    def _similar_match(hit) -> SimilarMatch:
        return SimilarMatch(
            match_id=stable_id("match", hit.record.uid),
            competition=hit.record.competition,
            kickoff_at=hit.record.kickoff_at,
            home=hit.record.home,
            away=hit.record.away,
            similarity_score=round(hit.score, 6),
            shared_patterns=list(hit.shared_patterns),
            shared_signals=list(hit.shared_signals),
            shared_trends=list(hit.shared_trends),
            historical_outcome=hit.record.label,
            total_goals=hit.record.total_goals,
        )


def _coverage(count: int, target: int) -> float:
    return min(1.0, count / target)


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _role_behavior(rows: list[HistoricalRecord], team: str) -> TeamRoleBehavior:
    wins = draws = losses = 0
    goals_for = []
    goals_against = []
    for row in rows:
        is_home = row.home == team
        team_label = "HOME_WIN" if is_home else "AWAY_WIN"
        if row.label == "DRAW":
            draws += 1
        elif row.label == team_label:
            wins += 1
        else:
            losses += 1
        goals_for.append(row.home_score if is_home else row.away_score)
        goals_against.append(row.away_score if is_home else row.home_score)
    return TeamRoleBehavior(
        matches=len(rows),
        wins=wins,
        draws=draws,
        losses=losses,
        goals_for=round(_mean(goals_for), 6),
        goals_against=round(_mean(goals_against), 6),
    )


def _context_labels(rows: list[HistoricalRecord]) -> tuple[list[str], list[str]]:
    if not rows:
        return [], []
    draw_rate = sum(row.label == "DRAW" for row in rows) / len(rows)
    goals = _mean(row.total_goals for row in rows)
    volatility = (
        statistics.pstdev([row.total_goals for row in rows])
        if len(rows) > 1
        else 0.0
    )
    trends = [
        "high_draw_tendency" if draw_rate >= 0.30 else "draw_resistance",
        "low_scoring" if goals <= 2.5 else "high_scoring",
        "stable" if volatility <= 1.5 else "volatile",
    ]
    return trends, list(trends)


def _unique(evidence):
    seen = set()
    result = []
    for item in evidence:
        if item.evidence_id not in seen:
            seen.add(item.evidence_id)
            result.append(item)
    return result
