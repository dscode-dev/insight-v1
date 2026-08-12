"""Deterministic causal-link reasoning over Atlas intelligence contracts."""

from __future__ import annotations

from dataclasses import dataclass

from atlas.intelligence.contracts import (
    BehaviorPattern,
    BehaviorType,
    ConfidenceExplanation,
    ConflictInsight,
    Evidence,
    IntelligenceEdge,
    IntelligenceEdgeType,
    IntelligenceGraph,
    IntelligenceNode,
    IntelligenceNodeType,
    IntelligenceSignal,
    MarketInsight,
    ReasoningInsight,
    ReasoningStatement,
    RegimeInsight,
    SignalState,
    SimilarityInsight,
    TrendInsight,
    UncertaintyExplanation,
    UncertaintyInsight,
)
from atlas.intelligence.historical import stable_id
from atlas.memory import HierarchicalMemoryInsight


@dataclass(frozen=True, slots=True)
class ReasoningResult:
    reasoning: ReasoningInsight
    graph: IntelligenceGraph
    conflicts: list[ConflictInsight]
    confidence: ConfidenceExplanation
    uncertainty: UncertaintyExplanation


class DeterministicReasoningEngine:
    def analyze(
        self,
        *,
        signals: list[IntelligenceSignal],
        evidence: list[Evidence],
        trends: list[TrendInsight],
        regime: RegimeInsight,
        market: MarketInsight | None,
        memory: HierarchicalMemoryInsight,
        similarity: SimilarityInsight,
        behaviors: list[BehaviorPattern],
        uncertainty: UncertaintyInsight,
        scope_key: str,
        signal_states: list[SignalState] | None = None,
    ) -> ReasoningResult:
        nodes = self._nodes(
            signals=signals,
            signal_states=signal_states,
            evidence=evidence,
            trends=trends,
            regime=regime,
            market=market,
            memory=memory,
            behaviors=behaviors,
            uncertainty=uncertainty,
        )
        edges = self._base_edges(
            signals=signals,
            signal_states=signal_states,
            trends=trends,
            regime=regime,
            market=market,
            memory=memory,
            behaviors=behaviors,
            uncertainty=uncertainty,
        )
        conflicts = self._conflicts(
            signals=signals,
            signal_states=signal_states,
            market=market,
            memory=memory,
            behaviors=behaviors,
            scope_key=scope_key,
        )
        for conflict in conflicts:
            if len(conflict.node_ids) >= 2:
                edges.append(
                    IntelligenceEdge(
                        source_node_id=conflict.node_ids[0],
                        target_node_id=conflict.node_ids[1],
                        edge_type=IntelligenceEdgeType.conflicts_with,
                        weight=conflict.severity,
                        rationale=conflict.description,
                    )
                )
        statements = self._rules(
            signals=signals,
            market=market,
            memory=memory,
            similarity=similarity,
            behaviors=behaviors,
        )
        behavior_explanations = self._behavior_explanations(
            signals=signals,
            signal_states=signal_states,
            market=market,
            memory=memory,
            behaviors=behaviors,
        )
        confidence = self._confidence(
            signals=signals,
            signal_states=signal_states,
            evidence=evidence,
            market=market,
            memory=memory,
            behaviors=behaviors,
            conflicts=conflicts,
        )
        uncertainty_explanation = self._uncertainty(
            uncertainty=uncertainty,
            market=market,
            memory=memory,
            similarity=similarity,
            conflicts=conflicts,
        )
        supporting = [
            item.description
            for item in sorted(
                evidence,
                key=lambda item: (
                    -(item.confidence * item.weight),
                    item.description,
                ),
            )[:5]
        ]
        return ReasoningResult(
            reasoning=ReasoningInsight(
                statements=statements,
                behavior_explanations=behavior_explanations,
                top_supporting_evidence=supporting,
            ),
            graph=IntelligenceGraph(nodes=nodes, edges=_unique_edges(edges)),
            conflicts=conflicts,
            confidence=confidence,
            uncertainty=uncertainty_explanation,
        )

    def _nodes(
        self,
        *,
        signals,
        signal_states,
        evidence,
        trends,
        regime,
        market,
        memory,
        behaviors,
        uncertainty,
    ) -> list[IntelligenceNode]:
        state_by_id = {
            state.signal_id: state
            for state in signal_states or []
        }
        nodes = [
            IntelligenceNode(
                node_id=_signal_node(signal),
                node_type=IntelligenceNodeType.signal,
                label=signal.signal_name,
                confidence=(
                    state_by_id[str(signal.signal_id)].effective_confidence
                    if str(signal.signal_id) in state_by_id
                    else signal.confidence
                ),
                attributes={
                    "strength": signal.strength,
                    **(
                        {
                            "status": state_by_id[str(signal.signal_id)].status.value,
                            "effective_weight": state_by_id[
                                str(signal.signal_id)
                            ].effective_weight,
                            "stability": state_by_id[
                                str(signal.signal_id)
                            ].signal_stability,
                            "reinforced": state_by_id[
                                str(signal.signal_id)
                            ].reinforced,
                            "conflicting": state_by_id[
                                str(signal.signal_id)
                            ].conflicting,
                        }
                        if str(signal.signal_id) in state_by_id
                        else {}
                    ),
                },
            )
            for signal in signals
        ]
        nodes.extend(
            IntelligenceNode(
                node_id=_evidence_node(item),
                node_type=IntelligenceNodeType.evidence,
                label=item.description,
                confidence=item.confidence,
                attributes={"type": item.evidence_type.value, "source": item.source},
            )
            for item in evidence
        )
        nodes.extend(
            IntelligenceNode(
                node_id=_trend_node(trend),
                node_type=IntelligenceNodeType.trend,
                label=trend.trend_type,
                confidence=trend.confidence,
                attributes={
                    "direction": trend.direction.value,
                    "strength": trend.strength,
                },
            )
            for trend in trends
        )
        nodes.extend(
            IntelligenceNode(
                node_id=_behavior_node(behavior),
                node_type=IntelligenceNodeType.behavior,
                label=behavior.type.value,
                confidence=behavior.confidence,
                attributes={
                    "strength": behavior.strength,
                    "uncertainty": behavior.uncertainty,
                },
            )
            for behavior in behaviors
        )
        nodes.extend(
            [
                IntelligenceNode(
                    node_id="memory:head_to_head",
                    node_type=IntelligenceNodeType.memory,
                    label="head-to-head memory",
                    confidence=memory.memory_confidence.h2h_coverage,
                    attributes={
                        "matches": memory.head_to_head.matches,
                        "draws": memory.head_to_head.draws,
                        "goals": memory.head_to_head.goals,
                    },
                ),
                IntelligenceNode(
                    node_id="memory:home_team",
                    node_type=IntelligenceNodeType.memory,
                    label=f"{memory.home_team} memory",
                    confidence=memory.memory_confidence.home_team_coverage,
                    attributes={
                        "matches": memory.home_team_memory.matches,
                        "draw_rate": memory.home_team_memory.draw_rate,
                    },
                ),
                IntelligenceNode(
                    node_id="memory:away_team",
                    node_type=IntelligenceNodeType.memory,
                    label=f"{memory.away_team} memory",
                    confidence=memory.memory_confidence.away_team_coverage,
                    attributes={
                        "matches": memory.away_team_memory.matches,
                        "draw_rate": memory.away_team_memory.draw_rate,
                    },
                ),
                IntelligenceNode(
                    node_id="memory:competition",
                    node_type=IntelligenceNodeType.memory,
                    label=f"{memory.competition} memory",
                    confidence=memory.memory_confidence.competition_coverage,
                    attributes={
                        "matches": memory.competition_memory.matches,
                        "draw_rate": memory.competition_memory.draw_rate,
                    },
                ),
                IntelligenceNode(
                    node_id="regime:current",
                    node_type=IntelligenceNodeType.regime,
                    label=regime.regime_type.value,
                    confidence=regime.confidence,
                    attributes={"characteristics": regime.characteristics},
                ),
                IntelligenceNode(
                    node_id="uncertainty:report",
                    node_type=IntelligenceNodeType.uncertainty,
                    label="report uncertainty",
                    confidence=1.0 - uncertainty.uncertainty_score,
                    attributes={
                        "score": uncertainty.uncertainty_score,
                        "missing": uncertainty.missing_signals,
                    },
                ),
            ]
        )
        if market:
            nodes.append(
                IntelligenceNode(
                    node_id="market:current",
                    node_type=IntelligenceNodeType.market,
                    label=f"market {market.movement.direction.value}",
                    confidence=market.confidence,
                    attributes={
                        "favorite_pressure": market.favorite_pressure,
                        "disagreement": market.disagreement,
                        "volatility": market.volatility,
                    },
                )
            )
        return nodes

    def _base_edges(
        self,
        *,
        signals,
        signal_states,
        trends,
        regime,
        market,
        memory,
        behaviors,
        uncertainty,
    ) -> list[IntelligenceEdge]:
        edges: list[IntelligenceEdge] = []
        for signal in signals:
            for item in signal.evidence:
                edges.append(
                    IntelligenceEdge(
                        source_node_id=_evidence_node(item),
                        target_node_id=_signal_node(signal),
                        edge_type=IntelligenceEdgeType.derived_from,
                        weight=item.weight,
                        rationale=f"{signal.signal_name} is derived from this evidence",
                    )
                )
        signal_map = {signal.signal_name: signal for signal in signals}
        state_by_key = {
            state.signal_key: state
            for state in signal_states or []
        }
        signal_node_by_key = {
            _key(signal.signal_name): _signal_node(signal) for signal in signals
        }
        for state in signal_states or []:
            child = signal_node_by_key.get(state.signal_key)
            if not child:
                continue
            for edge in state.dependency_edges:
                parent = signal_node_by_key.get(edge.parent_signal)
                if not parent:
                    continue
                edges.append(
                    IntelligenceEdge(
                        source_node_id=parent,
                        target_node_id=child,
                        edge_type=(
                            IntelligenceEdgeType.weakens
                            if edge.relation == "weakens"
                            else IntelligenceEdgeType.supports
                        ),
                        weight=abs(edge.confidence_effect),
                        rationale=edge.rationale,
                    )
                )
            for supporter in state.reinforced_by:
                parent = signal_node_by_key.get(supporter)
                if parent:
                    edges.append(
                        IntelligenceEdge(
                            source_node_id=parent,
                            target_node_id=child,
                            edge_type=IntelligenceEdgeType.increases_confidence,
                            weight=state.effective_weight,
                            rationale=(
                                f"{supporter} reinforces {state.signal_key}"
                            ),
                        )
                    )
            for conflict in state.conflicts_with:
                other = signal_node_by_key.get(conflict)
                if other:
                    edges.append(
                        IntelligenceEdge(
                            source_node_id=other,
                            target_node_id=child,
                            edge_type=IntelligenceEdgeType.conflicts_with,
                            weight=1.0 - state.effective_confidence,
                            rationale=(
                                f"{conflict} conflicts with {state.signal_key}"
                            ),
                        )
                    )
        trend_map = {trend.trend_type: trend for trend in trends}
        for behavior in behaviors:
            behavior_node = _behavior_node(behavior)
            for item in behavior.evidence:
                edges.append(
                    IntelligenceEdge(
                        source_node_id=_evidence_node(item),
                        target_node_id=behavior_node,
                        edge_type=IntelligenceEdgeType.explains,
                        weight=item.weight,
                        rationale=item.description,
                    )
                )
                edges.append(
                    IntelligenceEdge(
                        source_node_id=_evidence_node(item),
                        target_node_id=behavior_node,
                        edge_type=IntelligenceEdgeType.increases_confidence,
                        weight=item.confidence,
                        rationale=(
                            "direct behavioral evidence increases confidence "
                            "in the detected pattern"
                        ),
                    )
                )
            for name in _behavior_signal_names(behavior.type):
                if name in signal_map:
                    signal = signal_map[name]
                    state = state_by_key.get(_key(name))
                    edges.append(
                        IntelligenceEdge(
                            source_node_id=_signal_node(signal),
                            target_node_id=behavior_node,
                            edge_type=IntelligenceEdgeType.supports,
                            weight=(
                                state.effective_weight if state else signal.strength
                            ),
                            rationale=(
                                f"{name} signal state supports "
                                f"{behavior.type.value} behavior"
                            ),
                        )
                    )
            for name in _behavior_trend_names(behavior.type):
                if name in trend_map:
                    trend = trend_map[name]
                    edges.append(
                        IntelligenceEdge(
                            source_node_id=_trend_node(trend),
                            target_node_id=behavior_node,
                            edge_type=IntelligenceEdgeType.explains,
                            weight=trend.strength,
                            rationale=(
                                f"{name} contributes temporal context to "
                                f"{behavior.type.value}"
                            ),
                        )
                    )
            for memory_node, confidence, description in (
                (
                    "memory:head_to_head",
                    memory.memory_confidence.h2h_coverage,
                    "exact matchup history",
                ),
                (
                    "memory:home_team",
                    memory.memory_confidence.home_team_coverage,
                    "home-team history",
                ),
                (
                    "memory:away_team",
                    memory.memory_confidence.away_team_coverage,
                    "away-team history",
                ),
                (
                    "memory:competition",
                    memory.memory_confidence.competition_coverage,
                    "competition history",
                ),
            ):
                edges.append(
                    IntelligenceEdge(
                        source_node_id=memory_node,
                        target_node_id=behavior_node,
                        edge_type=IntelligenceEdgeType.supports,
                        weight=confidence,
                        rationale=(
                            f"{description} contextualizes "
                            f"{behavior.type.value}"
                        ),
                    )
                )
                edges.append(
                    IntelligenceEdge(
                        source_node_id=memory_node,
                        target_node_id=behavior_node,
                        edge_type=IntelligenceEdgeType.increases_confidence,
                        weight=confidence,
                        rationale=(
                            f"{description} coverage increases behavior "
                            "confidence"
                        ),
                    )
                )
            edges.append(
                IntelligenceEdge(
                    source_node_id="regime:current",
                    target_node_id=behavior_node,
                    edge_type=IntelligenceEdgeType.explains,
                    weight=regime.confidence,
                    rationale="competition regime explains expected behavior",
                )
            )
            edges.append(
                IntelligenceEdge(
                    source_node_id="uncertainty:report",
                    target_node_id=behavior_node,
                    edge_type=IntelligenceEdgeType.weakens,
                    weight=uncertainty.uncertainty_score,
                    rationale="report uncertainty limits behavior confidence",
                )
            )
            if market and behavior.type in {
                BehaviorType.favorite_pressure,
                BehaviorType.favorite_instability,
                BehaviorType.market_agreement,
                BehaviorType.market_disagreement,
                BehaviorType.market_uncertainty,
                BehaviorType.volatile,
            }:
                edges.append(
                    IntelligenceEdge(
                        source_node_id="market:current",
                        target_node_id=behavior_node,
                        edge_type=IntelligenceEdgeType.supports,
                        weight=market.confidence,
                        rationale="current market structure supports this behavior",
                    )
                )
        if market and market.disagreement > 0:
            edges.append(
                IntelligenceEdge(
                    source_node_id="market:current",
                    target_node_id="uncertainty:report",
                    edge_type=IntelligenceEdgeType.increases_uncertainty,
                    weight=market.disagreement,
                    rationale="market disagreement increases report uncertainty",
                )
            )
        if memory.memory_confidence.uncertainty > 0:
            edges.append(
                IntelligenceEdge(
                    source_node_id="memory:head_to_head",
                    target_node_id="uncertainty:report",
                    edge_type=IntelligenceEdgeType.increases_uncertainty,
                    weight=memory.memory_confidence.uncertainty,
                    rationale="incomplete hierarchical memory increases uncertainty",
                )
            )
        return edges

    def _rules(self, *, signals, market, memory, similarity, behaviors):
        signal = {item.signal_name: item for item in signals}
        behavior = {item.type: item for item in behaviors}
        statements: list[ReasoningStatement] = []

        if (
            BehaviorType.low_scoring in behavior
            and BehaviorType.draw_tendency in behavior
            and BehaviorType.stable in behavior
        ):
            statements.append(
                ReasoningStatement(
                    rule_id="low-scoring-draw-stability",
                    conclusion=(
                        "Low-scoring, draw-oriented and stable evidence "
                        "reinforces a low-volatility match pattern."
                    ),
                    confidence=_mean_confidence(
                        behavior[BehaviorType.low_scoring].confidence,
                        behavior[BehaviorType.draw_tendency].confidence,
                        behavior[BehaviorType.stable].confidence,
                    ),
                    supporting_node_ids=[
                        _behavior_node(behavior[BehaviorType.low_scoring]),
                        _behavior_node(behavior[BehaviorType.draw_tendency]),
                        _behavior_node(behavior[BehaviorType.stable]),
                    ],
                    confidence_effect=0.12,
                    uncertainty_effect=-0.08,
                )
            )

        h2h_draw_rate = (
            memory.head_to_head.draws / memory.head_to_head.matches
            if memory.head_to_head.matches
            else 0.0
        )
        if (
            h2h_draw_rate >= 0.30
            and memory.home_team_memory.draw_rate >= 0.28
            and memory.away_team_memory.draw_rate >= 0.28
            and memory.competition_memory.draw_rate >= 0.24
        ):
            statements.append(
                ReasoningStatement(
                    rule_id="draw-memory-convergence",
                    conclusion=(
                        "H2H, both team histories and competition memory "
                        "converge on elevated draw behavior."
                    ),
                    confidence=min(0.95, memory.memory_confidence.overall),
                    supporting_node_ids=[
                        "memory:head_to_head",
                        "memory:home_team",
                        "memory:away_team",
                        "memory:competition",
                    ],
                    confidence_effect=0.16,
                    uncertainty_effect=-0.10,
                )
            )

        if (
            market
            and market.disagreement >= 0.20
            and market.favorite_pressure >= 0.50
            and memory.memory_confidence.overall < 0.75
        ):
            statements.append(
                ReasoningStatement(
                    rule_id="market-pressure-thin-memory",
                    conclusion=(
                        "Market disagreement and favorite pressure are not "
                        "fully corroborated by team memory."
                    ),
                    confidence=market.confidence,
                    supporting_node_ids=["market:current", "memory:head_to_head"],
                    confidence_effect=-0.12,
                    uncertainty_effect=0.20,
                )
            )

        if memory.memory_confidence.overall >= 0.75:
            statements.append(
                ReasoningStatement(
                    rule_id="deep-hierarchical-memory",
                    conclusion=(
                        "Deep matchup, team and competition history increases "
                        "contextual confidence."
                    ),
                    confidence=memory.memory_confidence.overall,
                    supporting_node_ids=[
                        "memory:head_to_head",
                        "memory:home_team",
                        "memory:away_team",
                        "memory:competition",
                    ],
                    confidence_effect=0.18,
                    uncertainty_effect=-0.12,
                )
            )

        if similarity.actual_neighbor_count < 5:
            statements.append(
                ReasoningStatement(
                    rule_id="sparse-similarity-neighborhood",
                    conclusion=(
                        "Few threshold-qualified analogues limit behavioral "
                        "generalization."
                    ),
                    confidence=0.9,
                    supporting_node_ids=["memory:competition"],
                    confidence_effect=-0.15,
                    uncertainty_effect=0.18,
                )
            )

        draw_signal = signal.get("draw_tendency")
        if draw_signal and BehaviorType.draw_tendency in behavior:
            statements.append(
                ReasoningStatement(
                    rule_id="draw-signal-behavior-link",
                    conclusion=(
                        "The draw signal and retained historical contexts "
                        "jointly explain draw-oriented behavior."
                    ),
                    confidence=_mean_confidence(
                        draw_signal.confidence,
                        behavior[BehaviorType.draw_tendency].confidence,
                    ),
                    supporting_node_ids=[
                        _signal_node(draw_signal),
                        _behavior_node(behavior[BehaviorType.draw_tendency]),
                    ],
                    confidence_effect=0.08,
                    uncertainty_effect=-0.04,
                )
            )
        return statements

    def _conflicts(self, *, signals, signal_states, market, memory, behaviors, scope_key):
        signal = {item.signal_name: item for item in signals}
        behavior = {item.type: item for item in behaviors}
        conflicts = []
        signal_node_by_key = {
            _key(item.signal_name): _signal_node(item) for item in signals
        }

        for state in signal_states or []:
            for other in state.conflicts_with:
                node_ids = [
                    signal_node_by_key.get(state.signal_key),
                    signal_node_by_key.get(other),
                ]
                node_ids = [node_id for node_id in node_ids if node_id]
                if len(node_ids) >= 2:
                    conflicts.append(
                        _conflict(
                            scope_key,
                            f"signal-state-{state.signal_key}-{other}",
                            1.0 - state.effective_confidence,
                            (
                                f"SignalState marks {state.signal_key} as "
                                f"conflicting with {other}."
                            ),
                            node_ids,
                        )
                    )

        if market and market.favorite_pressure >= 0.5 and market.disagreement >= 0.2:
            conflicts.append(
                _conflict(
                    scope_key,
                    "market-pressure-disagreement",
                    min(1.0, (market.favorite_pressure + market.disagreement) / 2),
                    (
                        "The market identifies favorite pressure while its "
                        "movement remains meaningfully disputed."
                    ),
                    ["market:current", "uncertainty:report"],
                )
            )

        scoring = signal.get("scoring_tendency")
        if (
            scoring
            and scoring.strength >= 0.6
            and BehaviorType.low_scoring in behavior
        ):
            conflicts.append(
                _conflict(
                    scope_key,
                    "scoring-signal-low-scoring-behavior",
                    max(scoring.strength, behavior[BehaviorType.low_scoring].strength),
                    (
                        "Current scoring tendency is strong while historical "
                        "analogues support low-scoring behavior."
                    ),
                    [
                        _signal_node(scoring),
                        _behavior_node(behavior[BehaviorType.low_scoring]),
                    ],
                )
            )

        home_form = signal.get("home_form")
        away_form = signal.get("away_form")
        if home_form and away_form and home_form.strength >= 0.6 and away_form.strength >= 0.6:
            conflicts.append(
                _conflict(
                    scope_key,
                    "dual-strong-form",
                    min(home_form.strength, away_form.strength),
                    "Both teams carry strong form, reducing directional clarity.",
                    [_signal_node(home_form), _signal_node(away_form)],
                )
            )

        h2h_draw_rate = (
            memory.head_to_head.draws / memory.head_to_head.matches
            if memory.head_to_head.matches
            else 0.0
        )
        draw_signal = signal.get("draw_tendency")
        if draw_signal and draw_signal.strength >= 0.3 and h2h_draw_rate < 0.2:
            conflicts.append(
                _conflict(
                    scope_key,
                    "draw-signal-h2h-resistance",
                    draw_signal.strength,
                    (
                        "Current draw tendency is elevated but exact matchup "
                        "memory has a low draw rate."
                    ),
                    [_signal_node(draw_signal), "memory:head_to_head"],
                )
            )
        return conflicts

    def _behavior_explanations(self, *, signals, signal_states, market, memory, behaviors):
        signal = {item.signal_name: item for item in signals}
        states = {_key(item.signal_name): item for item in signal_states or []}
        explanations = {}
        for behavior in behaviors:
            reasons = []
            for name in _behavior_signal_names(behavior.type):
                if name in signal:
                    state = states.get(_key(name))
                    if state:
                        reasons.append(
                            f"{name} state {state.status.value}; effective "
                            f"confidence {state.effective_confidence:.1%}"
                        )
                    reasons.append(
                        f"{name} strength {signal[name].strength:.1%}"
                    )
            reasons.append(
                f"{memory.head_to_head.matches} prior H2H matches"
            )
            reasons.append(
                f"team memory depth {memory.home_team_memory.matches}/"
                f"{memory.away_team_memory.matches}"
            )
            reasons.append(
                f"competition draw rate "
                f"{memory.competition_memory.draw_rate:.1%}"
            )
            if market and behavior.type in {
                BehaviorType.favorite_pressure,
                BehaviorType.market_disagreement,
                BehaviorType.volatile,
            }:
                reasons.append(
                    f"market disagreement {market.disagreement:.1%}"
                )
            explanations[behavior.type.value] = reasons
        return explanations

    def _confidence(
        self, *, signals, signal_states, evidence, market, memory, behaviors, conflicts
    ):
        behavior_confidence = _mean(
            [behavior.confidence for behavior in behaviors], default=0.4
        )
        evidence_support = min(1.0, len(evidence) / 20)
        source_count = len(
            {
                source.source_id
                for signal in signals
                for source in signal.sources
            }
        )
        source_support = min(1.0, source_count / 2)
        market_support = market.confidence if market else 0.0
        state_support = _mean(
            [
                state.effective_confidence
                for state in signal_states or []
                if state.active and not state.expired
            ],
            default=0.5,
        )
        conflict_penalty = min(
            0.25, sum(conflict.severity for conflict in conflicts) * 0.08
        )
        score = _clamp(
            0.25 * behavior_confidence
            + 0.18 * evidence_support
            + 0.20 * memory.memory_confidence.overall
            + 0.15 * market_support
            + 0.12 * source_support
            + 0.10 * state_support
            - conflict_penalty
        )
        level = "high" if score >= 0.75 else "medium" if score >= 0.45 else "low"
        positive = [
            f"{len(evidence)} linked evidence items",
            f"hierarchical memory confidence {memory.memory_confidence.overall:.1%}",
        ]
        if source_count >= 2:
            positive.append(f"{source_count} corroborating sources")
        if market:
            positive.append(f"market confidence {market.confidence:.1%}")
        if signal_states:
            positive.append(f"signal-state confidence {state_support:.1%}")
        limiting = [conflict.description for conflict in conflicts]
        if source_count < 2:
            limiting.append("fewer than two corroborating sources")
        if memory.memory_confidence.overall < 0.75:
            limiting.append("thin hierarchical memory")
        return ConfidenceExplanation(
            level=level,
            score=round(score, 6),
            positive_factors=positive,
            limiting_factors=limiting,
        )

    def _uncertainty(
        self, *, uncertainty, market, memory, similarity, conflicts
    ):
        reasons = list(uncertainty.conflicting_signals)
        reasons.extend(conflict.description for conflict in conflicts)
        if memory.memory_confidence.uncertainty > 0.2:
            reasons.append(
                f"memory uncertainty {memory.memory_confidence.uncertainty:.1%}"
            )
        if similarity.actual_neighbor_count < 5:
            reasons.append(
                f"only {similarity.actual_neighbor_count} similarity neighbors"
            )
        reasons.append("no live match-state data")
        reducing = []
        if memory.memory_confidence.overall >= 0.75:
            reducing.append("deep hierarchical memory")
        if market:
            reducing.append("request market data available")
        if similarity.actual_neighbor_count >= 25:
            reducing.append("broad similarity neighborhood")
        return UncertaintyExplanation(
            score=uncertainty.uncertainty_score,
            reasons=list(dict.fromkeys(reasons)),
            missing_inputs=list(uncertainty.missing_signals),
            reducing_factors=reducing,
        )


def _behavior_signal_names(behavior_type: BehaviorType) -> tuple[str, ...]:
    mapping = {
        BehaviorType.low_scoring: ("scoring_tendency", "goal_distribution"),
        BehaviorType.high_scoring: ("scoring_tendency", "goal_distribution"),
        BehaviorType.draw_tendency: ("draw_tendency",),
        BehaviorType.draw_resistance: ("draw_tendency",),
        BehaviorType.favorite_pressure: ("favorite_pressure",),
        BehaviorType.favorite_dominance: ("favorite_pressure", "home_form"),
        BehaviorType.favorite_instability: (
            "favorite_pressure",
            "market_disagreement",
        ),
        BehaviorType.stable: ("competition_volatility",),
        BehaviorType.volatile: (
            "competition_volatility",
            "market_disagreement",
        ),
        BehaviorType.chaotic: (
            "competition_volatility",
            "market_disagreement",
        ),
        BehaviorType.market_agreement: ("market_consensus",),
        BehaviorType.market_disagreement: ("market_disagreement",),
        BehaviorType.market_uncertainty: ("market_disagreement",),
    }
    return mapping.get(behavior_type, ())


def _behavior_trend_names(behavior_type: BehaviorType) -> tuple[str, ...]:
    mapping = {
        BehaviorType.low_scoring: ("goal_trend",),
        BehaviorType.high_scoring: ("goal_trend",),
        BehaviorType.draw_tendency: ("draw_trend",),
        BehaviorType.draw_resistance: ("draw_trend",),
        BehaviorType.favorite_pressure: ("favorite_trend", "market_trend"),
        BehaviorType.stable: ("volatility_trend",),
        BehaviorType.volatile: ("volatility_trend",),
        BehaviorType.chaotic: ("volatility_trend",),
        BehaviorType.market_disagreement: ("market_trend",),
    }
    return mapping.get(behavior_type, ())


def _signal_node(signal: IntelligenceSignal) -> str:
    return f"signal:{signal.signal_id}"


def _evidence_node(evidence: Evidence) -> str:
    return f"evidence:{evidence.evidence_id}"


def _behavior_node(behavior: BehaviorPattern) -> str:
    return f"behavior:{behavior.pattern_id}"


def _trend_node(trend: TrendInsight) -> str:
    return f"trend:{trend.trend_id}"


def _key(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _conflict(scope_key, name, severity, description, nodes):
    return ConflictInsight(
        conflict_id=str(stable_id(scope_key, "conflict", name)),
        severity=round(_clamp(severity), 6),
        description=description,
        node_ids=nodes,
        uncertainty_effect=round(min(1.0, 0.15 + 0.35 * severity), 6),
    )


def _mean_confidence(*values: float) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _mean(values, *, default: float) -> float:
    values = list(values)
    return sum(values) / len(values) if values else default


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _unique_edges(edges: list[IntelligenceEdge]) -> list[IntelligenceEdge]:
    seen = set()
    result = []
    for edge in edges:
        key = (
            edge.source_node_id,
            edge.target_node_id,
            edge.edge_type,
            edge.rationale,
        )
        if key not in seen:
            seen.add(key)
            result.append(edge)
    return result
