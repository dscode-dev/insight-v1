"""TrendLifecycleEngine — the per-tick lifecycle pass.

Order of operations for one match tick (deterministic):

  1. EXPIRE  — open instances not reinforced within the expiry window.
  2. CONFIRM — open instances whose confirming impact category landed
               this tick (e.g. a goal confirms pressure_building).
  3. FAIL    — open instances reversed by this tick's trends.
  4. OBSERVE — fold this tick's trends into instances (open new ones,
               reinforce existing, evaluate STRENGTHENING/WEAKENING,
               and apply sustain-based confirmation).

The engine is pure over (open instances ⨯ tick inputs); persistence is
the repository's job. Every state transition increments
trend_lifecycle_total{state} and is recorded on the instance.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from prometheus_client import Counter

from atlas.trends.lifecycle.models import (
    DEFAULT_LIFECYCLE_RULES,
    LifecycleRule,
    TrendInstance,
    TrendLifecycleState,
)
from atlas.trends.models import Trend, TrendType

logger = logging.getLogger(__name__)

TREND_LIFECYCLE_TOTAL = Counter(
    "trend_lifecycle_total",
    "Trend lifecycle state transitions.",
    ["state"],
)


def _mark(instance: TrendInstance, state: TrendLifecycleState) -> None:
    instance.current_state = state
    instance.state_history.append(state.value)
    TREND_LIFECYCLE_TOTAL.labels(state=state.value).inc()


class TrendLifecycleEngine:
    """Pure lifecycle state machine. All thresholds configurable."""

    def __init__(
        self,
        *,
        rules: dict[TrendType, LifecycleRule] | None = None,
        expiry_seconds: int = 1800,
        epsilon: float = 0.01,
    ) -> None:
        self._rules = rules if rules is not None else dict(DEFAULT_LIFECYCLE_RULES)
        self._expiry_seconds = expiry_seconds
        self._eps = epsilon

    def process(
        self,
        *,
        open_instances: list[TrendInstance],
        trends: list[Trend],
        impact_category: str | None,
        now: datetime | None = None,
    ) -> tuple[list[TrendInstance], dict[str, TrendLifecycleState]]:
        """Run one lifecycle pass.

        Returns (every touched instance — closed AND open — for the
        repository to persist, and a map trend_id → lifecycle state for
        the trends observed this tick so the scorer can read it).
        """
        ts = now or datetime.now(timezone.utc)
        touched: dict[str, TrendInstance] = {}
        by_type: dict[TrendType, TrendInstance] = {}
        for inst in open_instances:
            by_type[inst.trend_type] = inst

        # 1. Expire stale instances.
        for inst in list(by_type.values()):
            if (ts - inst.last_seen_at).total_seconds() > self._expiry_seconds:
                _mark(inst, TrendLifecycleState.EXPIRED)
                touched[str(inst.instance_id)] = inst
                del by_type[inst.trend_type]

        # 2. Confirm by impact category (e.g. goal → pressure_building).
        if impact_category:
            for inst in list(by_type.values()):
                rule = self._rules.get(inst.trend_type)
                if rule and impact_category in rule.confirm_categories:
                    inst.confirmed_by = f"impact:{impact_category}"
                    _mark(inst, TrendLifecycleState.CONFIRMED)
                    touched[str(inst.instance_id)] = inst
                    del by_type[inst.trend_type]

        # 3. Fail reversed instances (this tick's trends as reversal
        # evidence against OTHER open instances).
        for trend in trends:
            for inst in list(by_type.values()):
                if self._reverses(inst, trend):
                    inst.failed_by = f"trend:{trend.trend_type.value}"
                    _mark(inst, TrendLifecycleState.FAILED)
                    touched[str(inst.instance_id)] = inst
                    del by_type[inst.trend_type]

        # 4. Observe this tick's trends.
        states: dict[str, TrendLifecycleState] = {}
        for trend in trends:
            inst = by_type.get(trend.trend_type)
            if inst is None:
                inst = TrendInstance.open(
                    canonical_match_id=trend.canonical_match_id,
                    trend_type=trend.trend_type,
                    direction=trend.direction,
                    now=ts,
                )
                by_type[trend.trend_type] = inst
                self._append(inst, trend, ts)
                _mark(inst, TrendLifecycleState.ACTIVE)
            else:
                prev_conf = inst.confidence_history[-1]
                prev_str = inst.strength_history[-1]
                self._append(inst, trend, ts)
                conf_d = trend.confidence - prev_conf
                str_d = trend.strength - prev_str
                if conf_d > self._eps and str_d > self._eps:
                    _mark(inst, TrendLifecycleState.STRENGTHENING)
                elif conf_d < -self._eps and str_d < -self._eps:
                    _mark(inst, TrendLifecycleState.WEAKENING)
                else:
                    _mark(inst, TrendLifecycleState.ACTIVE)
                # Sustain-based confirmation ("sustained movement",
                # "continued superiority").
                rule = self._rules.get(inst.trend_type)
                if (
                    rule
                    and rule.confirm_sustain is not None
                    and inst.observation_count >= rule.confirm_sustain
                ):
                    inst.confirmed_by = (
                        f"sustain:{inst.observation_count}_observations"
                    )
                    _mark(inst, TrendLifecycleState.CONFIRMED)
                    del by_type[inst.trend_type]
            touched[str(inst.instance_id)] = inst
            states[str(trend.trend_id)] = inst.current_state

        return list(touched.values()), states

    # ---- helpers ----------------------------------------------------------

    def _append(self, inst: TrendInstance, trend: Trend, ts: datetime) -> None:
        inst.trend_ids.append(str(trend.trend_id))
        inst.strength_history.append(trend.strength)
        inst.confidence_history.append(trend.confidence)
        inst.evidence_history.append(dict(trend.evidence))
        inst.last_seen_at = ts
        if trend.direction != 0:
            inst.direction = trend.direction

    def _reverses(self, inst: TrendInstance, trend: Trend) -> bool:
        rule = self._rules.get(inst.trend_type)
        if rule is None:
            return False
        # Same-type reversal: the trend flipped direction.
        if (
            rule.fail_on_reverse_direction
            and trend.trend_type == inst.trend_type
            and inst.direction != 0
            and trend.direction != 0
            and trend.direction == -inst.direction
        ):
            return True
        # Cross-type failure (e.g. momentum_shift vs pressure_building).
        require_opposite = rule.fail_types.get(trend.trend_type)
        if require_opposite is None:
            return False
        if not require_opposite:
            return True
        if inst.direction != 0:
            return trend.direction == -inst.direction
        # Direction-less instance: a sign-flipping momentum swing
        # counts as the reversal.
        return bool(trend.evidence.get("sign_flip"))
