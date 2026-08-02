"""Cross-source reconciliation + source confidence (ML-B.5 multi-source).

Reads the validated envelopes each source wrote for a (competition, season)
and groups them by a canonical match key. When ≥2 sources carry the same
match it checks score agreement and raises confidence; a single-source match
keeps its source trust. Output is a reconciliation report under
`reports/reconciliation/` — it never mutates the per-source validated layers.
"""

from __future__ import annotations

from typing import Any

from explorer.datalake.lake import DataLake

_TRUST_CONF = {"high": 0.9, "medium": 0.7, "low": 0.45}


def _match_key(env: dict[str, Any]) -> tuple[str, str, str]:
    p = env.get("payload", {})
    home = (p.get("home_team") or {}).get("club_id") or (p.get("home_team") or {}).get("name", "")
    away = (p.get("away_team") or {}).get("club_id") or (p.get("away_team") or {}).get("name", "")
    day = (p.get("scheduled_at") or "")[:10]
    return (str(home), str(away), day)


def _score_tuple(env: dict[str, Any]) -> tuple[int, int] | None:
    sc = (env.get("payload") or {}).get("score")
    if not sc or sc.get("home") is None or sc.get("away") is None:
        return None
    return (sc["home"], sc["away"])


def reconcile(competition: str, season: str, sources: list[str],
              lake: DataLake) -> dict[str, Any]:
    by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for source in sources:
        for env in lake.read("validated", competition, season, source, "fixture"):
            by_key.setdefault(_match_key(env), []).append(env)

    matches = []
    multi = agree = disagree = 0
    for key, envs in by_key.items():
        srcs = sorted({e["source"] for e in envs})
        best_trust = max((_TRUST_CONF.get(e["trust_level"], 0.5) for e in envs), default=0.5)
        confidence = best_trust
        agreement: bool | None = None
        if len(srcs) >= 2:
            multi += 1
            scores = {_score_tuple(e) for e in envs if _score_tuple(e) is not None}
            if len(scores) == 1:
                agreement = True
                agree += 1
                confidence = min(1.0, best_trust + 0.15)  # corroborated
            elif len(scores) > 1:
                agreement = False
                disagree += 1
                confidence = max(0.3, best_trust - 0.2)  # conflict → lower
        matches.append({
            "match_key": list(key), "sources": srcs, "source_count": len(srcs),
            "agreement": agreement, "source_confidence": round(confidence, 3),
        })

    summary = {
        "competition": competition, "season": season, "sources": sources,
        "total_matches": len(by_key), "multi_source_matches": multi,
        "agreements": agree, "disagreements": disagree,
        "single_source_matches": len(by_key) - multi,
        "mean_confidence": round(
            sum(m["source_confidence"] for m in matches) / len(matches), 3) if matches else 0.0,
    }
    payload = {"summary": summary, "matches": matches}
    lake.write_report("reconciliation", competition, season, f"{season}.json", payload=payload)
    return summary
