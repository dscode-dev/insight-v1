"""Deterministic interpretation of Atlas and Explorer signals.

Explorer owns signal generation.  Atlas owns signal understanding: lifecycle,
dependencies, reinforcement, conflict, stability and confidence propagation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from atlas.intelligence.contracts import (
    Evidence,
    EvidenceType,
    IntelligenceSignal,
    SignalDependencyEdge,
    SignalLifecycleStatus,
    SignalState,
    SignalStateSummary,
)
from atlas.intelligence.evidence_engine import EvidenceEngine

# Parents MUST be names the signal engine actually emits. The previous
# table declared 12 parents that no engine ever produces
# (implied_home_strength, odds_gap, market_entropy, bookmaker_spread,
# historical_balance, market_uncertainty, home_points_5, home_streak,
# away_points_5, away_streak, goal_volatility, plus `low_scoring` which
# is a BehaviorType, not a signal). Those were FEATURE and BEHAVIOUR
# names, not signal names. Every permanently-absent parent applied a
# 0.92 multiplier, so signals were deflated by up to 64% on perfect
# input — market_disagreement fell from 0.8 to 0.289 — and the reason
# was buried in a dependency_edges string instead of being logged or
# ticketed. Structural, permanent, silent degradation.
#
# The emitted vocabulary is: home_form, away_form, momentum, streak,
# favorite_pressure, market_consensus, market_disagreement,
# competition_volatility, draw_tendency, scoring_tendency,
# defensive_instability, goal_distribution. Signals with no real parent
# in that vocabulary are roots and simply have no entry.
DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "favorite_pressure": ("market_consensus",),
    "draw_tendency": ("scoring_tendency",),
    "competition_volatility": ("market_disagreement",),
    "home_form": ("streak",),
    "away_form": ("streak",),
    "momentum": ("home_form", "away_form"),
}

# Same vocabulary rule as DEPENDENCIES — names that are never emitted
# can never reinforce anything, so they only made the groups look
# richer than they were.
REINFORCEMENT_GROUPS: tuple[tuple[str, ...], ...] = (
    ("favorite_pressure", "market_consensus"),
    ("draw_tendency", "scoring_tendency", "goal_distribution"),
    ("home_form", "away_form", "momentum", "streak"),
    ("competition_volatility", "market_disagreement"),
)

CONFLICT_RULES: tuple[tuple[str, str, str], ...] = (
    (
        "favorite_pressure",
        "market_disagreement",
        "market identifies pressure while market disagreement remains elevated",
    ),
    (
        "market_consensus",
        "market_disagreement",
        "market consensus and market disagreement cannot both dominate",
    ),
    (
        "scoring_tendency",
        "low_scoring",
        "scoring tendency conflicts with low-scoring behavior",
    ),
    (
        "home_form",
        "away_form",
        "both teams have strong form, reducing directional clarity",
    ),
    (
        "competition_volatility",
        "market_consensus",
        "high competition volatility weakens market-consensus confidence",
    ),
)

MIN_ACTIVE_CONFIDENCE = 0.05
WEAK_CONFIDENCE = 0.35
WEAK_STRENGTH = 0.15


@dataclass(frozen=True, slots=True)
class _RawSignal:
    signal_id: str
    signal_key: str
    signal_name: str
    signal_type: str
    strength: float
    confidence: float
    weight: float
    generated_at: datetime
    expires_at: datetime | None
    explanation: str
    evidence: list[Evidence]
    metadata: dict[str, Any]


class SignalStateEngine:
    def __init__(self, evidence: EvidenceEngine | None = None) -> None:
        self._evidence = evidence or EvidenceEngine()

    def evaluate(
        self,
        signals: list[IntelligenceSignal],
        *,
        as_of: datetime,
        scope_key: str,
        explorer_signals: list[dict[str, Any]] | None = None,
    ) -> SignalStateSummary:
        raw = [
            *(_from_intelligence_signal(signal) for signal in signals),
            *(
                _from_explorer_payload(payload, as_of)
                for payload in explorer_signals or []
            ),
        ]
        by_key = _deduplicate(raw)
        initial = {
            key: self._initial_state(item, as_of=as_of, scope_key=scope_key)
            for key, item in by_key.items()
        }
        with_dependencies = self._propagate_dependencies(initial, scope_key, as_of)
        with_reinforcement = self._apply_reinforcement(
            with_dependencies, scope_key, as_of
        )
        final = self._apply_conflicts(with_reinforcement, scope_key, as_of)
        states = sorted(
            final.values(),
            key=lambda item: (
                item.status.value,
                -item.effective_confidence,
                item.signal_key,
            ),
        )
        evidence = _unique_evidence(
            [item for state in states for item in state.evidence]
        )
        active = [state for state in states if state.active and not state.expired]
        strongest = [
            state.signal_key
            for state in sorted(
                active,
                key=lambda item: (
                    -(item.effective_confidence * item.effective_weight),
                    item.signal_key,
                ),
            )[:8]
        ]
        weakest = [
            state.signal_key
            for state in sorted(
                active,
                key=lambda item: (
                    item.effective_confidence * item.effective_weight,
                    item.signal_key,
                ),
            )[:8]
        ]
        dependency_explanation = {
            state.signal_key: [edge.rationale for edge in state.dependency_edges]
            for state in states
            if state.dependency_edges
        }
        return SignalStateSummary(
            states=states,
            strongest_signals=strongest,
            weakest_signals=weakest,
            expired_signals=[
                state.signal_key for state in states if state.expired
            ],
            conflicting_signals=[
                state.signal_key for state in states if state.conflicting
            ],
            reinforced_signals=[
                state.signal_key for state in states if state.reinforced
            ],
            dependency_explanation=dependency_explanation,
            average_stability=round(
                sum(state.signal_stability for state in states) / len(states),
                6,
            )
            if states
            else 0.0,
            average_effective_confidence=round(
                sum(state.effective_confidence for state in states) / len(states),
                6,
            )
            if states
            else 0.0,
            evidence=evidence,
        )

    def _initial_state(
        self, raw: _RawSignal, *, as_of: datetime, scope_key: str
    ) -> SignalState:
        expired = raw.expires_at is not None and raw.expires_at <= as_of
        inactive = raw.confidence <= MIN_ACTIVE_CONFIDENCE or raw.strength <= 0.0
        weak = raw.confidence < WEAK_CONFIDENCE or raw.strength < WEAK_STRENGTH
        if expired:
            status = SignalLifecycleStatus.expired
            active = False
            effective_confidence = 0.0
            effective_weight = 0.0
            effective_strength = 0.0
        elif inactive:
            status = SignalLifecycleStatus.inactive
            active = False
            effective_confidence = raw.confidence
            effective_weight = raw.weight
            effective_strength = raw.strength
        elif weak:
            status = SignalLifecycleStatus.weak
            active = True
            effective_confidence = raw.confidence
            effective_weight = raw.weight
            effective_strength = raw.strength
        else:
            status = SignalLifecycleStatus.active
            active = True
            effective_confidence = raw.confidence
            effective_weight = raw.weight
            effective_strength = raw.strength

        stability = _stability(
            confidence=effective_confidence,
            coverage=float(raw.metadata.get("coverage_ratio", 0.5)),
            source_count=int(raw.metadata.get("source_count", 1)),
            conflict_penalty=0.0,
            expired=expired,
        )
        evidence = self._evidence.create(
            scope_key=scope_key,
            evidence_type=EvidenceType.statistical,
            source="signal_state_engine",
            description=(
                f"{raw.signal_key} classified as {status.value}; "
                f"confidence {effective_confidence:.3f}, weight "
                f"{effective_weight:.3f}"
            ),
            observed_at=as_of,
            weight=max(0.1, effective_weight),
            confidence=max(0.0, effective_confidence),
            attributes={
                "signal_key": raw.signal_key,
                "status": status.value,
                "expired": expired,
                "source_signal_id": raw.signal_id,
            },
        )
        return SignalState(
            signal_id=raw.signal_id,
            signal_key=raw.signal_key,
            signal_name=raw.signal_name,
            signal_type=raw.signal_type,
            status=status,
            active=active,
            expired=expired,
            weak=weak and not expired,
            base_strength=round(_clamp(raw.strength), 6),
            effective_strength=round(_clamp(effective_strength), 6),
            base_confidence=round(_clamp(raw.confidence), 6),
            effective_confidence=round(_clamp(effective_confidence), 6),
            base_weight=round(_clamp(raw.weight), 6),
            effective_weight=round(_clamp(effective_weight), 6),
            signal_stability=stability,
            dependencies=list(DEPENDENCIES.get(raw.signal_key, ())),
            evidence=[evidence, *raw.evidence],
            generated_at=raw.generated_at,
            expires_at=raw.expires_at,
            explanation=raw.explanation,
            metadata=raw.metadata,
        )

    def _propagate_dependencies(
        self,
        states: dict[str, SignalState],
        scope_key: str,
        as_of: datetime,
    ) -> dict[str, SignalState]:
        updated: dict[str, SignalState] = {}
        for key, state in states.items():
            edges: list[SignalDependencyEdge] = []
            multiplier = 1.0
            for parent_key in state.dependencies:
                parent = states.get(parent_key)
                if parent is None:
                    multiplier *= 0.92
                    edges.append(
                        SignalDependencyEdge(
                            parent_signal=parent_key,
                            child_signal=key,
                            relation="requires",
                            confidence_effect=-0.08,
                            rationale=(
                                f"{key} expects {parent_key}, but no active "
                                "parent signal is available"
                            ),
                        )
                    )
                    continue
                if not parent.active:
                    multiplier *= 0.75
                    edges.append(
                        SignalDependencyEdge(
                            parent_signal=parent_key,
                            child_signal=key,
                            relation="weakens",
                            parent_status=parent.status,
                            confidence_effect=-0.25,
                            rationale=(
                                f"{parent_key} is {parent.status.value}, so it "
                                f"reduces {key} confidence"
                            ),
                        )
                    )
                else:
                    effect = (parent.effective_confidence - 0.5) * 0.2
                    multiplier *= 0.75 + 0.25 * parent.effective_confidence
                    edges.append(
                        SignalDependencyEdge(
                            parent_signal=parent_key,
                            child_signal=key,
                            relation="supports",
                            parent_status=parent.status,
                            confidence_effect=round(effect, 6),
                            rationale=(
                                f"{parent_key} supports {key} with effective "
                                f"confidence {parent.effective_confidence:.3f}"
                            ),
                        )
                    )
            confidence = _clamp(state.effective_confidence * multiplier)
            weak = state.weak or (state.active and confidence < WEAK_CONFIDENCE)
            status = (
                SignalLifecycleStatus.weak
                if weak and state.active and not state.expired
                else state.status
            )
            evidence = list(state.evidence)
            if edges:
                evidence.insert(
                    0,
                    self._evidence.create(
                        scope_key=scope_key,
                        evidence_type=EvidenceType.statistical,
                        source="signal_dependency_graph",
                        description=(
                            f"{key} dependency confidence propagated through "
                            f"{len(edges)} parent signal(s)"
                        ),
                        observed_at=as_of,
                        weight=0.7,
                        confidence=confidence,
                        attributes={
                            "signal_key": key,
                            "parents": [edge.parent_signal for edge in edges],
                        },
                    ),
                )
            updated[key] = state.model_copy(
                update={
                    "effective_confidence": round(confidence, 6),
                    "weak": weak,
                    "status": status,
                    "dependency_edges": edges,
                    "signal_stability": _stability(
                        confidence=confidence,
                        coverage=float(state.metadata.get("coverage_ratio", 0.5)),
                        source_count=int(state.metadata.get("source_count", 1)),
                        conflict_penalty=0.0,
                        expired=state.expired,
                    ),
                    "evidence": evidence,
                }
            )
        return updated

    def _apply_reinforcement(
        self,
        states: dict[str, SignalState],
        scope_key: str,
        as_of: datetime,
    ) -> dict[str, SignalState]:
        updated = dict(states)
        # Collect supporters across ALL groups FIRST, from a frozen
        # snapshot, then apply one boost per signal.
        #
        # The previous version mutated `updated` inside the group loop,
        # so a signal appearing in two groups (momentum was in both the
        # home_form and away_form groups) got boosted twice, the second
        # time on top of the already-boosted value — it could end up
        # with HIGHER effective confidence than its own base confidence.
        # Boost now scales with the count of DISTINCT supporters, not
        # with how many groups happen to mention the signal.
        supporters_by_signal: dict[str, set[str]] = {}
        for group in REINFORCEMENT_GROUPS:
            present = [
                states[key]
                for key in group
                if key in states and states[key].active and not states[key].expired
            ]
            if len(present) < 2:
                continue
            for state in present:
                supporters_by_signal.setdefault(state.signal_key, set()).update(
                    item.signal_key
                    for item in present
                    if item.signal_key != state.signal_key
                )

        for signal_key, supporter_set in supporters_by_signal.items():
            state = states[signal_key]
            supporters = sorted(supporter_set)
            boost = min(0.18, 0.04 * len(supporters))
            confidence = _clamp(state.effective_confidence + boost)
            weight = _clamp(state.effective_weight + boost / 2)
            evidence = self._evidence.create(
                scope_key=scope_key,
                evidence_type=EvidenceType.statistical,
                source="signal_reinforcement_engine",
                description=(
                    f"{state.signal_key} reinforced by compatible signals: "
                    f"{', '.join(supporters)}"
                ),
                observed_at=as_of,
                weight=weight,
                confidence=confidence,
                attributes={
                    "signal_key": state.signal_key,
                    "reinforced_by": supporters,
                    "confidence_boost": round(boost, 6),
                },
            )
            updated[state.signal_key] = state.model_copy(
                update={
                    # Do NOT overwrite a `weak` signal's status: a weak
                    # signal that gets reinforced was previously
                    # relabelled `reinforced` while `weak` stayed True,
                    # and the reasoning graph publishes only
                    # `status.value` — so the consumer lost the weakness
                    # entirely. Reinforcement is recorded via the
                    # `reinforced` flag either way.
                    "status": (
                        state.status
                        if state.weak
                        else SignalLifecycleStatus.reinforced
                    ),
                    "reinforced": True,
                    "reinforced_by": sorted(set([*state.reinforced_by, *supporters])),
                    "effective_confidence": round(confidence, 6),
                    "effective_weight": round(weight, 6),
                    "signal_stability": _stability(
                        confidence=confidence,
                        coverage=float(state.metadata.get("coverage_ratio", 0.5)),
                        source_count=int(state.metadata.get("source_count", 1)),
                        conflict_penalty=0.0,
                        expired=state.expired,
                    ),
                    "evidence": [evidence, *state.evidence],
                }
            )
        return updated

    def _apply_conflicts(
        self,
        states: dict[str, SignalState],
        scope_key: str,
        as_of: datetime,
    ) -> dict[str, SignalState]:
        updated = dict(states)
        for left, right, rationale in CONFLICT_RULES:
            a = updated.get(left)
            b = updated.get(right)
            if not a or not b or not a.active or not b.active:
                continue
            severity = min(
                1.0,
                (a.effective_strength + b.effective_strength)
                * (a.effective_confidence + b.effective_confidence)
                / 4,
            )
            if severity < 0.18:
                continue
            for state, other in ((a, b), (b, a)):
                penalty = min(0.28, 0.12 + severity * 0.18)
                confidence = _clamp(state.effective_confidence - penalty)
                evidence = self._evidence.create(
                    scope_key=scope_key,
                    evidence_type=EvidenceType.statistical,
                    source="signal_conflict_engine",
                    description=(
                        f"{state.signal_key} conflicts with {other.signal_key}: "
                        f"{rationale}"
                    ),
                    observed_at=as_of,
                    weight=0.75,
                    confidence=max(confidence, 0.1),
                    attributes={
                        "signal_key": state.signal_key,
                        "conflicts_with": other.signal_key,
                        "severity": round(severity, 6),
                        "confidence_penalty": round(penalty, 6),
                    },
                )
                updated[state.signal_key] = state.model_copy(
                    update={
                        "status": SignalLifecycleStatus.conflicting,
                        "conflicting": True,
                        "conflicts_with": sorted(
                            set([*state.conflicts_with, other.signal_key])
                        ),
                        "effective_confidence": round(confidence, 6),
                        "signal_stability": _stability(
                            confidence=confidence,
                            coverage=float(state.metadata.get("coverage_ratio", 0.5)),
                            source_count=int(state.metadata.get("source_count", 1)),
                            conflict_penalty=severity,
                            expired=state.expired,
                        ),
                        "evidence": [evidence, *state.evidence],
                    }
                )
        return updated


def _from_intelligence_signal(signal: IntelligenceSignal) -> _RawSignal:
    return _RawSignal(
        signal_id=str(signal.signal_id),
        signal_key=_key(signal.signal_name),
        signal_name=signal.signal_name,
        signal_type=signal.signal_type.value,
        strength=_clamp(signal.strength),
        confidence=_clamp(signal.confidence),
        weight=_clamp(signal.strength),
        generated_at=signal.created_at,
        expires_at=None,
        explanation=f"Atlas historical signal {signal.signal_name}",
        evidence=list(signal.evidence),
        metadata={
            "coverage_ratio": signal.coverage.ratio,
            "source_count": signal.source_count,
            "origin": "atlas",
        },
    )


def _from_explorer_payload(payload: dict[str, Any], as_of: datetime) -> _RawSignal:
    generated_at = _parse_time(payload.get("generated_at")) or as_of
    signal_key = str(
        payload.get("signal_key")
        or payload.get("signal")
        or payload.get("name")
        or payload.get("signal_name")
        or "unknown_signal"
    )
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return _RawSignal(
        signal_id=str(payload.get("signal_id") or payload.get("id") or signal_key),
        signal_key=_key(signal_key),
        signal_name=str(payload.get("signal_name") or signal_key),
        signal_type=str(payload.get("category") or payload.get("signal_type") or "explorer"),
        strength=_clamp(_number(payload.get("score"), payload.get("strength"), default=0.0)),
        confidence=_clamp(_number(payload.get("confidence"), default=0.5)),
        weight=_clamp(_number(payload.get("weight"), default=0.5)),
        generated_at=generated_at,
        expires_at=_parse_time(payload.get("expires_at")),
        explanation=str(payload.get("explanation") or f"Explorer signal {signal_key}"),
        evidence=[],
        metadata={
            **metadata,
            "coverage_ratio": metadata.get("coverage_ratio", 0.5),
            "source_count": metadata.get("source_count", 1),
            "origin": "explorer",
            "formula": payload.get("formula"),
            "derived_from": payload.get("derived_from"),
            "ttl_seconds": payload.get("ttl_seconds"),
        },
    )


def _deduplicate(raw: list[_RawSignal]) -> dict[str, _RawSignal]:
    by_key: dict[str, _RawSignal] = {}
    for item in raw:
        current = by_key.get(item.signal_key)
        if current is None:
            by_key[item.signal_key] = item
            continue
        current_score = current.confidence * current.weight
        item_score = item.confidence * item.weight
        if item_score > current_score or (
            item_score == current_score and item.generated_at > current.generated_at
        ):
            by_key[item.signal_key] = item
    return by_key


def _stability(
    *,
    confidence: float,
    coverage: float,
    source_count: int,
    conflict_penalty: float,
    expired: bool,
) -> float:
    if expired:
        return 0.0
    source_support = min(1.0, source_count / 3)
    score = (
        0.35 * _clamp(coverage)
        + 0.25 * source_support
        + 0.30 * _clamp(confidence)
        + 0.10 * (1.0 - _clamp(conflict_penalty))
    )
    return round(_clamp(score), 6)


def _key(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _number(*values: Any, default: float) -> float:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return default


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _unique_evidence(evidence: list[Evidence]) -> list[Evidence]:
    seen = set()
    result = []
    for item in evidence:
        if item.evidence_id not in seen:
            seen.add(item.evidence_id)
            result.append(item)
    return result
