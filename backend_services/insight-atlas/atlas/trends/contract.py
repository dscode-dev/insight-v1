"""Trend Contract V1 enrichment — deterministic, template-driven.

`title` and `summary` are rendered from fixed templates over the
trend's own evidence. Pure string formatting: no LLM, no external
calls, no randomness — the same trend always renders the same text.
The text is structured description for downstream consumers, NOT
social copy (Atlas never generates posts).
"""

from __future__ import annotations

from typing import Callable

from atlas.signal_engine import Signal
from atlas.trends.models import Trend, TrendType


def _pp(value: object) -> str:
    """Probability → percentage-points string ('0.0841' → '8.4pp')."""
    try:
        return f"{abs(float(value)) * 100:.1f}pp"
    except (TypeError, ValueError):
        return "?"


def _pct(value: object) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "?"


def _side(direction: int) -> str:
    if direction > 0:
        return "home side"
    if direction < 0:
        return "away side"
    return "match"


def _market_shift(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        f"Market shift toward the {_side(t.direction)}",
        f"Consensus implied probability moved from {_pct(e.get('implied_prob_prev'))} "
        f"to {_pct(e.get('implied_prob_now'))} ({_pp(e.get('prob_delta'))}) "
        f"across {e.get('bookmaker_count', '?')} bookmaker(s).",
    )


def _market_acceleration(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Market move is accelerating",
        f"Latest consensus move of {_pp(e.get('last_delta'))} is "
        f"{e.get('acceleration_factor', '?')}x the recent baseline of "
        f"{_pp(e.get('baseline_delta'))} over {e.get('samples', '?')} snapshots.",
    )


def _market_disagreement(t: Trend) -> tuple[str, str]:
    e = t.evidence
    books = e.get("bookmaker_probs") or {}
    return (
        "Bookmakers disagree on this match",
        f"Home implied probabilities span {_pp(e.get('prob_spread'))} "
        f"across {len(books)} bookmaker(s).",
    )


def _market_anomaly(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        f"Bookmaker {e.get('bookmaker', '?')} is detached from the market",
        f"{e.get('bookmaker', '?')} prices the home side at "
        f"{_pct(e.get('bookmaker_prob'))} vs a market median of "
        f"{_pct(e.get('median_prob'))} ({_pp(e.get('deviation'))} apart).",
    )


def _momentum_shift(t: Trend) -> tuple[str, str]:
    e = t.evidence
    flip = " (sign flip)" if e.get("sign_flip") else ""
    return (
        f"Momentum swinging to the {_side(t.direction)}",
        f"Momentum moved from {e.get('momentum_prev', '?')} to "
        f"{e.get('momentum_now', '?')}{flip}.",
    )


def _pressure_building(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Pressure building",
        f"Match pressure rose from {e.get('pressure_prev', '?')} to "
        f"{e.get('pressure_now', '?')} across recalculations.",
    )


def _tempo_change(t: Trend) -> tuple[str, str]:
    e = t.evidence
    verb = "accelerated" if t.direction > 0 else "slowed"
    return (
        f"Match tempo has {verb}",
        f"Event density moved from {e.get('signal_density_prev', '?')} to "
        f"{e.get('signal_density_now', '?')}.",
    )


def _dominance_pattern(t: Trend) -> tuple[str, str]:
    e = t.evidence
    basis = e.get("basis", "pressure")
    return (
        f"The {_side(t.direction)} is dominating",
        f"Sustained one-sided dominance detected from {basis} "
        f"(score {e.get('dominance_score', e.get('pressure_delta', '?'))}).",
    )


def _historical_deviation(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Match has drifted from its pre-match baseline",
        f"Consensus implied probability deviated from {_pct(e.get('opening_prob'))} "
        f"at open to {_pct(e.get('current_prob'))} now "
        f"({_pp(e.get('deviation'))}) over {e.get('snapshots', '?')} snapshots.",
    )


def _historical_pattern(t: Trend) -> tuple[str, str]:
    return (
        "Historical pattern detected",
        f"Match state matches a known historical pattern "
        f"(evidence: {t.evidence}).",
    )


def _historical_similarity(t: Trend) -> tuple[str, str]:
    return (
        "Similar historical matches found",
        f"Match profile is close to prior matches "
        f"(evidence: {t.evidence}).",
    )


def _impact_assessment(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        f"{str(e.get('impact', '')).capitalize()} impact event: {e.get('category', '?')}",
        f"A {str(e.get('impact', '?')).lower()}-impact {e.get('category', 'event')} "
        f"landed; co-occurring signals: {', '.join(e.get('signals') or []) or 'none'}.",
    )


def _game_state_change(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        f"Game state: {e.get('from', '?')} → {e.get('to', '?')}",
        f"The match moved from {e.get('from', '?')} to {e.get('to', '?')}.",
    )


def _risk_increase(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Risk rising in a tight match",
        f"Pressure climbed from {e.get('pressure_prev', '?')} to "
        f"{e.get('pressure_now', '?')} at minute {e.get('minute', '?')} "
        f"with a probability gap of {e.get('prob_gap', '?')}.",
    )


def _narrative_conflict(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Crowd and market disagree",
        f"Sentiment direction ({e.get('sentiment_direction', '?')}) opposes "
        f"the market's latest move ({e.get('market_direction', '?')}).",
    )


def _sentiment_shift(t: Trend) -> tuple[str, str]:
    mood = "positive" if t.direction > 0 else "negative"
    return (
        f"Community sentiment swinging {mood}",
        f"Sentiment delta of {t.evidence.get('sentiment_delta', '?')} "
        f"over the feature window.",
    )


def _community_signal(t: Trend) -> tuple[str, str]:
    return (
        "Community converging on this match",
        f"Community confidence at "
        f"{_pct(t.evidence.get('community_confidence'))}.",
    )


def _members_of(t: Trend) -> str:
    members = t.evidence.get("member_types") or []
    return " + ".join(members) if members else "correlated trends"


def _market_conviction(t: Trend) -> tuple[str, str]:
    return (
        f"Market conviction building toward the {_side(t.direction)}",
        f"Correlated market movement: {_members_of(t)} within "
        f"{t.evidence.get('window_seconds', '?')}s of each other.",
    )


def _imminent_breakthrough(t: Trend) -> tuple[str, str]:
    return (
        "Breakthrough conditions forming",
        f"Sustained pressure and dominance are co-occurring "
        f"({_members_of(t)}).",
    )


def _risk_escalation(t: Trend) -> tuple[str, str]:
    return (
        "Match risk is escalating",
        f"Rising risk coincides with a game-state change "
        f"({_members_of(t)}).",
    )


def _narrative_divergence(t: Trend) -> tuple[str, str]:
    return (
        "Crowd narrative diverging from the market",
        f"A narrative conflict is co-occurring with a market move "
        f"({_members_of(t)}).",
    )


def _consensus_growing(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Market agreement strengthening",
        f"Bookmaker consensus rose from {_pct(e.get('consensus_prev'))} to "
        f"{_pct(e.get('consensus_now'))} across "
        f"{e.get('bookmaker_count', '?')} bookmaker(s).",
    )


def _consensus_weakening(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Market agreement weakening",
        f"Bookmaker consensus fell from {_pct(e.get('consensus_prev'))} to "
        f"{_pct(e.get('consensus_now'))} across "
        f"{e.get('bookmaker_count', '?')} bookmaker(s).",
    )


def _market_divergence_t(t: Trend) -> tuple[str, str]:
    e = t.evidence
    outliers = e.get("outliers") or []
    who = f" Detached: {', '.join(outliers)}." if outliers else ""
    return (
        "Bookmakers are diverging",
        f"Market divergence climbed from {_pct(e.get('divergence_prev'))} to "
        f"{_pct(e.get('divergence_now'))}.{who}",
    )


def _market_fragmentation(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Market is fragmented",
        f"High divergence ({_pct(e.get('divergence_now'))}) with low "
        f"consensus ({_pct(e.get('consensus_now'))}) — the market holds "
        f"no unified view of this match.",
    )


def _confidence_acceleration(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Market confidence is accelerating",
        f"Market confidence at {_pct(e.get('confidence_score'))} and firming "
        f"(velocity {e.get('confidence_velocity', '?')}).",
    )


def _confidence_decay(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Market confidence is decaying",
        f"Market confidence at {_pct(e.get('confidence_score'))} and fading "
        f"(velocity {e.get('confidence_velocity', '?')}).",
    )


def _volatility_increase(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Market volatility rising",
        f"Volatility moved from {_pct(e.get('volatility_prev'))} to "
        f"{_pct(e.get('volatility_now'))} — the market view is churning.",
    )


def _volatility_decrease(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Market settling down",
        f"Volatility eased from {_pct(e.get('volatility_prev'))} to "
        f"{_pct(e.get('volatility_now'))} — the market view is stabilising.",
    )


def _sharp_market_move(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        f"Sharp market move toward the {_side(t.direction)}",
        f"Fast, coordinated market movement (score "
        f"{_pct(e.get('sharp_movement_score'))}) across "
        f"{e.get('bookmaker_count', '?')} bookmaker(s).",
    )


def _market_uncertainty(t: Trend) -> tuple[str, str]:
    return (
        "Market uncertainty rising",
        f"A fragmented market is co-occurring with rising volatility "
        f"({_members_of(t)}).",
    )


def _market_reaction(t: Trend) -> tuple[str, str]:
    return (
        "Market reacting to on-pitch developments",
        f"A sharp market move is co-occurring with building pressure "
        f"({_members_of(t)}).",
    )


def _market_underestimation(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        f"Market repeatedly underestimating {e.get('team', '?')}",
        f"The market repriced toward {e.get('team', '?')} "
        f"{e.get('samples', '?')} time(s) and those moves confirmed "
        f"{_pct(e.get('confirmed_rate'))} of the time.",
    )


def _market_overestimation(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        f"Market repeatedly overestimating {e.get('team', '?')}",
        f"The market repriced against {e.get('team', '?')} "
        f"{e.get('samples', '?')} time(s) and those moves confirmed "
        f"{_pct(e.get('confirmed_rate'))} of the time.",
    )


def _recurring_volatility(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Recurring volatility in this scope",
        f"{e.get('closures', '?')} volatility episodes across "
        f"{e.get('matches', '?')} match(es) in {e.get('scope', '?')}.",
    )


def _recurring_confidence_failure(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Market confidence repeatedly failing",
        f"{e.get('failures', '?')} of {e.get('samples', '?')} confidence "
        f"build-ups failed ({_pct(e.get('failure_rate'))}).",
    )


def _recurring_sharp_reversal(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Sharp moves repeatedly reversing",
        f"{e.get('reversals', '?')} of {e.get('samples', '?')} sharp moves "
        f"reversed ({_pct(e.get('reversal_rate'))}).",
    )


def _strong_historical_alignment(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Market conviction aligned with history",
        f"Market conviction is forming where history confirms "
        f"{_pct(e.get('historical_confirmed_rate'))} of the time "
        f"({e.get('historical_sample', '?')} prior instances).",
    )


def _structural_volatility(t: Trend) -> tuple[str, str]:
    e = t.evidence
    return (
        "Volatility is structural in this competition",
        f"Recurring volatility inside a {e.get('regime', '?')} competition "
        f"regime — churn is the norm here, not the exception.",
    )


def _market_correction(t: Trend) -> tuple[str, str]:
    return (
        "Market correcting a misprice",
        f"A sharp move is unfolding on a team the market has "
        f"repeatedly underestimated ({_members_of(t)}).",
    )


_TEMPLATES: dict[TrendType, Callable[[Trend], tuple[str, str]]] = {
    TrendType.market_shift: _market_shift,
    TrendType.market_acceleration: _market_acceleration,
    TrendType.market_disagreement: _market_disagreement,
    TrendType.market_anomaly: _market_anomaly,
    TrendType.momentum_shift: _momentum_shift,
    TrendType.pressure_building: _pressure_building,
    TrendType.tempo_change: _tempo_change,
    TrendType.dominance_pattern: _dominance_pattern,
    TrendType.historical_pattern: _historical_pattern,
    TrendType.historical_similarity: _historical_similarity,
    TrendType.historical_deviation: _historical_deviation,
    TrendType.impact_assessment: _impact_assessment,
    TrendType.game_state_change: _game_state_change,
    TrendType.risk_increase: _risk_increase,
    TrendType.narrative_conflict: _narrative_conflict,
    TrendType.sentiment_shift: _sentiment_shift,
    TrendType.community_signal: _community_signal,
    TrendType.market_conviction: _market_conviction,
    TrendType.imminent_breakthrough: _imminent_breakthrough,
    TrendType.risk_escalation: _risk_escalation,
    TrendType.narrative_divergence: _narrative_divergence,
    TrendType.market_consensus_growing: _consensus_growing,
    TrendType.market_consensus_weakening: _consensus_weakening,
    TrendType.market_divergence: _market_divergence_t,
    TrendType.market_fragmentation: _market_fragmentation,
    TrendType.confidence_acceleration: _confidence_acceleration,
    TrendType.confidence_decay: _confidence_decay,
    TrendType.volatility_increase: _volatility_increase,
    TrendType.volatility_decrease: _volatility_decrease,
    TrendType.sharp_market_move: _sharp_market_move,
    TrendType.market_uncertainty: _market_uncertainty,
    TrendType.market_reaction: _market_reaction,
    TrendType.market_underestimation: _market_underestimation,
    TrendType.market_overestimation: _market_overestimation,
    TrendType.recurring_volatility: _recurring_volatility,
    TrendType.recurring_confidence_failure: _recurring_confidence_failure,
    TrendType.recurring_sharp_reversal: _recurring_sharp_reversal,
    TrendType.strong_historical_alignment: _strong_historical_alignment,
    TrendType.structural_volatility: _structural_volatility,
    TrendType.market_correction: _market_correction,
}


def render(trend: Trend) -> tuple[str, str]:
    """(title, summary) for a trend — fixed template over its evidence."""
    template = _TEMPLATES[trend.trend_type]
    return template(trend)


def enrich(trend: Trend, *, agent: str, signals: list[Signal]) -> Trend:
    """Fill the Contract V1 fields the detector layer doesn't know:
    the producing agent, the co-occurring signal types, and the
    rendered title/summary. Detector-set title/summary are preserved."""
    title, summary = (trend.title, trend.summary)
    if not title or not summary:
        title, summary = render(trend)
    return trend.model_copy(
        update={
            "agent": agent,
            "signals": sorted({s.signal_type.value for s in signals}),
            "title": title,
            "summary": summary,
        }
    )
