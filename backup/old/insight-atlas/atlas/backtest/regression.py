"""Replay regression detection (ATLAS-BACKTEST-A, Stage 6).

Compares a baseline replay to a candidate replay and reports what changed —
the mandatory quality gate for any future detector / heuristic / similarity /
reasoning change. Pure + deterministic; no thresholds, no ML.
"""

from __future__ import annotations

from atlas.backtest.contracts import RegressionDiff, ReplayResult, TrendEvaluation

_EPS = 1e-6


def _index(result: ReplayResult) -> dict[tuple[int, str], TrendEvaluation]:
    # (step, trend_type) → evaluation. If a detector fires the same type twice at
    # one step (it shouldn't), the last wins — regression still surfaces via hash.
    return {(e.step_index, e.trend_type): e for e in result.trends}


def diff_replays(baseline: ReplayResult, candidate: ReplayResult) -> RegressionDiff:
    base = _index(baseline)
    cand = _index(candidate)
    base_keys = set(base)
    cand_keys = set(cand)

    new = [
        {"step": k[0], "trend_type": k[1], "confidence": cand[k].confidence}
        for k in sorted(cand_keys - base_keys)
    ]
    lost = [
        {"step": k[0], "trend_type": k[1], "confidence": base[k].confidence}
        for k in sorted(base_keys - cand_keys)
    ]

    confidence_changes: list[dict] = []
    strength_changes: list[dict] = []
    for k in sorted(base_keys & cand_keys):
        b, c = base[k], cand[k]
        if abs(b.confidence - c.confidence) > _EPS:
            confidence_changes.append(
                {"step": k[0], "trend_type": k[1],
                 "from": b.confidence, "to": c.confidence}
            )
        if abs(b.strength - c.strength) > _EPS:
            strength_changes.append(
                {"step": k[0], "trend_type": k[1],
                 "from": b.strength, "to": c.strength}
            )

    trend_changes: list[dict] = []
    for label, rows in (("new", new), ("lost", lost),
                        ("confidence", confidence_changes), ("strength", strength_changes)):
        if rows:
            trend_changes.append({"kind": label, "count": len(rows)})

    return RegressionDiff(
        identical=baseline.deterministic_hash == candidate.deterministic_hash,
        baseline_hash=baseline.deterministic_hash,
        candidate_hash=candidate.deterministic_hash,
        new_detections=new,
        lost_detections=lost,
        confidence_changes=confidence_changes,
        strength_changes=strength_changes,
        trend_changes=trend_changes,
    )
