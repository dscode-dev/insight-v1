"""Deterministic historical football intelligence for administrators.

No inference model, LLM, prediction, recommendation, or publication path is
used here. Every sentence is selected from measured dataset statistics.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from atlas.intelligence_workspace.regimes import detect_regime, regime_inventory

_METRICS = Path(__file__).with_name("model_metrics.json")


def analyze(
    dataset_path: str, analysis_type: str, query: str,
    explorer_root: str | None = None,
) -> dict[str, Any]:
    if analysis_type not in {"competition", "team", "season", "dataset", "trend"}:
        raise ValueError("unsupported_analysis_type")
    rows = _load_rows(Path(dataset_path))
    selected = _select(rows, analysis_type, query)
    stats = _statistics(selected)
    competition = _dominant_competition(selected, query)
    regime = detect_regime(competition)
    confidence = _confidence(stats)
    tendencies = _tendencies(stats)
    missing = _missing(stats)
    risks = _risks(stats, confidence)
    report = {
        "analysis_type": analysis_type, "query": query,
        "scope": "historical statistical intelligence",
        "context": {
            "sample_size": stats["sample_size"],
            "source_coverage": stats["sources"],
            "competition_coverage": stats["competitions"],
            "season_coverage": stats["seasons"],
        },
        "regime_intelligence": {
            **regime.to_dict(),
            "competition": competition,
            "inventory": regime_inventory(),
            "statistics": {
                "draw_rate": stats.get("draw_rate"),
                "home_win_rate": stats.get("home_win_rate"),
                "away_win_rate": stats.get("away_win_rate"),
                "goals_per_match": stats.get("goals_per_match"),
                "odds_coverage": stats.get("odds_coverage"),
                "market_entropy": stats.get("market_entropy"),
            },
        },
        "tendencies": tendencies,
        "regimes": _regimes(stats, confidence),
        "signals": _signals(stats, analysis_type),
        "confidence": {
            "confidence": round(confidence, 4),
            "uncertainty": round(1 - confidence, 4),
            "calibration": compare_models()["models"]["outcome_v3"]["ece"],
            "basis": "sample depth, source diversity and feature coverage",
            "regime_modifier": regime.confidence_modifier,
            "modified_confidence": round(confidence * regime.confidence_modifier, 4),
        },
        "risks": risks,
        "missing_information": missing,
        "improvement_suggestions": _improvements(missing, risks),
        "measurements": stats,
        "guardrails": {
            "predictions": False, "betting": False, "recommendations": False,
            "llm": False, "publication": False,
        },
    }
    if analysis_type == "dataset" and explorer_root:
        report["dataset_generations"] = _generation_context(Path(explorer_root), query)
    return report


def compare_models() -> dict[str, Any]:
    body = json.loads(_METRICS.read_text("utf-8"))
    return {
        "models": body,
        "interpretation": [
            "outcome_v3 improved holdout and balanced accuracy over outcome_v2",
            "outcome_v4 improved draw recall but regressed accuracy and uncertainty",
            "ML-E.0 regime candidates improve draw sensitivity but are not promotable",
            "regime routing is implemented for review, not activated for runtime serving",
        ],
        "promotion": "none",
    }


def knowledge(dataset_path: str) -> dict[str, Any]:
    report = analyze(dataset_path, "dataset", "official baseline")
    return {
        "patterns": report["tendencies"],
        "regime_intelligence": report["regime_intelligence"],
        "tendencies": report["tendencies"],
        "risks": report["risks"],
        "signals_that_matter": report["signals"],
        "missing": report["missing_information"],
        "should_improve": report["improvement_suggestions"],
        "evolution": compare_models(),
        "guardrails": report["guardrails"],
    }


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text("utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if {"home", "away", "home_score", "away_score"} <= row.keys():
            rows.append(row)
    return rows


def _select(rows: list[dict[str, Any]], kind: str, query: str) -> list[dict[str, Any]]:
    q = _norm(query)
    if kind == "competition":
        aliases = {
            "brasileirao": "brasileirao_serie_a", "brasileirao_serie_a": "brasileirao_serie_a",
            "premier_league": "premier_league", "la_liga": "la_liga",
            "serie_a": "serie_a", "bundesliga": "bundesliga", "ligue_1": "ligue_1",
            "champions_league": "champions_league", "europa_league": "europa_league",
            "libertadores": "libertadores", "sul_americana": "sudamericana",
            "sudamericana": "sudamericana", "world_cup": "world_cup",
            "copa_america": "copa_america", "euro": "euro",
        }
        competition = next((value for alias, value in aliases.items() if alias in q), q)
        year = next(iter(re.findall(r"\b(?:19|20)\d{2}\b", query)), None)
        return [
            r for r in rows
            if competition in _norm(str(r.get("competition", "")))
            and (year is None or year in str(r.get("season", "")))
        ]
    if kind == "team":
        return [r for r in rows if q in _norm(str(r.get("home", ""))) or
                q in _norm(str(r.get("away", "")))]
    if kind == "season":
        return [r for r in rows if q in _norm(str(r.get("season", ""))) or
                q in _norm(str(r.get("competition", "")) + " " + str(r.get("season", "")))]
    if kind == "trend" and "draw" in q:
        return rows
    return rows


def _statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(rows, key=lambda r: str(r.get("scheduled_at") or r.get("kickoff_at") or ""))
    outcomes = Counter()
    totals: list[int] = []
    sources = Counter()
    competitions = Counter()
    seasons = Counter()
    team_points: list[int] = []
    odds_rows = 0
    market_entropy_values: list[float] = []
    for r in rows:
        h, a = int(r["home_score"]), int(r["away_score"])
        totals.append(h + a)
        outcomes["home_win" if h > a else "away_win" if a > h else "draw"] += 1
        row_sources = r.get("sources")
        if isinstance(row_sources, list) and row_sources:
            for source in row_sources:
                sources[str(source)] += 1
        else:
            sources[str(r.get("source", "unknown"))] += 1
        competitions[str(r.get("competition", "unknown"))] += 1
        seasons[str(r.get("season", "unknown"))] += 1
        team_points.append(3 if h > a else 1 if h == a else 0)
        if r.get("has_odds"):
            odds_rows += 1
        features = r.get("features") or {}
        if float(features.get("odds_available", 0.0)) > 0:
            odds_rows += 1
            market_entropy_values.append(float(features.get("market_entropy", 0.0)))
    n = len(rows)
    split = max(1, n // 2)
    first, second = rows[:split], rows[split:]
    return {
        "sample_size": n, "sources": dict(sources), "competitions": dict(competitions),
        "seasons": dict(seasons), "outcomes": dict(outcomes),
        "home_win_rate": round(outcomes["home_win"] / n, 4) if n else None,
        "draw_rate": round(outcomes["draw"] / n, 4) if n else None,
        "away_win_rate": round(outcomes["away_win"] / n, 4) if n else None,
        "goals_per_match": round(sum(totals) / n, 3) if n else None,
        "scoring_volatility": round(statistics.pstdev(totals), 3) if len(totals) > 1 else None,
        "first_half": _period(first), "second_half": _period(second),
        "odds_coverage": round(min(1.0, odds_rows / n), 4) if n else 0.0,
        "statistics_coverage": 0.0,
        "market_entropy": (
            round(sum(market_entropy_values) / len(market_entropy_values), 4)
            if market_entropy_values else 0.0
        ),
        "recent_form_points": team_points[-5:],
    }


def _period(rows: list[dict[str, Any]]) -> dict[str, float | int | None]:
    n = len(rows)
    if not n:
        return {"matches": 0, "home_win_rate": None, "draw_rate": None, "goals_per_match": None}
    h = d = goals = 0
    for r in rows:
        hs, aws = int(r["home_score"]), int(r["away_score"])
        h += hs > aws
        d += hs == aws
        goals += hs + aws
    return {"matches": n, "home_win_rate": round(h / n, 4),
            "draw_rate": round(d / n, 4), "goals_per_match": round(goals / n, 3)}


def _confidence(stats: dict[str, Any]) -> float:
    n = stats["sample_size"]
    sample = min(1.0, math.log10(max(1, n)) / 3)
    source = min(1.0, len(stats["sources"]) / 3)
    feature = (stats["odds_coverage"] + stats["statistics_coverage"]) / 2
    return min(0.95, 0.65 * sample + 0.2 * source + 0.15 * feature)


def _tendencies(s: dict[str, Any]) -> list[dict[str, Any]]:
    if not s["sample_size"]:
        return []
    first, second = s["first_half"], s["second_half"]
    out = []
    for key, label_up, label_down in (
        ("home_win_rate", "increasing home advantage", "declining home advantage"),
        ("draw_rate", "draw growth", "declining draw frequency"),
        ("goals_per_match", "increasing scoring", "declining scoring"),
    ):
        a, b = first.get(key), second.get(key)
        if a is None or b is None:
            continue
        delta = float(b) - float(a)
        out.append({
            "tendency": label_up if delta > 0.015 else label_down if delta < -0.015 else f"stable {key}",
            "delta": round(delta, 4), "basis": f"first-half vs second-half {key}",
        })
    return out


def _regimes(s: dict[str, Any], confidence: float) -> list[str]:
    regimes = []
    if s["sample_size"] < 100 or confidence < 0.55:
        regimes.append("uncertain")
    volatility = s.get("scoring_volatility")
    regimes.append("volatile" if volatility and volatility > 1.8 else "stable")
    if s.get("home_win_rate") is not None and s.get("away_win_rate") is not None:
        if abs(s["home_win_rate"] - s["away_win_rate"]) > 0.15:
            regimes.append("asymmetric")
    return regimes


def _signals(s: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    signals = [{
        "signal": "home advantage", "strength": s.get("home_win_rate"),
        "evidence": f"{s['outcomes'].get('home_win', 0)} home wins",
    }]
    recent = s.get("recent_form_points") or []
    if kind == "team" and recent:
        signals.append({
            "signal": "form", "strength": round(sum(recent) / (len(recent) * 3), 4),
            "evidence": f"{sum(recent)} points-equivalent across latest {len(recent)} observations",
        })
    signals.extend([
        {
            "signal": "market",
            "strength": s.get("odds_coverage"),
            "evidence": f"{s.get('odds_coverage', 0)} odds coverage; entropy {s.get('market_entropy', 0)}",
        },
        {"signal": "h2h", "strength": None, "evidence": "not isolated in this aggregate scope"},
    ])
    return signals


def _missing(s: dict[str, Any]) -> list[str]:
    out = []
    if s["sample_size"] < 100:
        out.append("insufficient samples")
    if s["odds_coverage"] < 0.5:
        out.append("missing odds")
    if s["statistics_coverage"] < 0.5:
        out.append("insufficient statistics")
    if len(s["sources"]) < 2:
        out.append("weak source coverage")
    return out


def _risks(s: dict[str, Any], confidence: float) -> list[str]:
    out = []
    if confidence < 0.65:
        out.append("low evidence confidence")
    if len(s["sources"]) < 2:
        out.append("single-source bias")
    if s["sample_size"] == 0:
        out.append("query has no matching historical records")
    return out


def _improvements(missing: list[str], risks: list[str]) -> list[str]:
    mapping = {
        "missing odds": "increase odds coverage",
        "insufficient statistics": "collect player and match statistics",
        "weak source coverage": "add a corroborating crawler-friendly source",
        "insufficient samples": "increase historical depth",
        "single-source bias": "improve cross-source reconciliation depth",
    }
    return list(dict.fromkeys(mapping[x] for x in [*missing, *risks] if x in mapping))


def _generation_context(root: Path, query: str) -> list[dict[str, Any]]:
    out = []
    q = _norm(query)
    for path in root.glob("generations/*/reports/manifests/generation.json"):
        try:
            body = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if q in _norm(str(body.get("generation_id", ""))) or q in {"mld5", "dataset"}:
            out.append(body)
    return out


def _dominant_competition(rows: list[dict[str, Any]], query: str) -> str | None:
    aliases = {
        "brasileirao": "brasileirao_serie_a",
        "brasileirao_serie_a": "brasileirao_serie_a",
        "premier_league": "premier_league",
        "la_liga": "la_liga",
        "serie_a": "serie_a",
        "bundesliga": "bundesliga",
        "ligue_1": "ligue_1",
        "champions_league": "champions_league",
        "europa_league": "europa_league",
        "libertadores": "libertadores",
        "sul_americana": "sudamericana",
        "sudamericana": "sudamericana",
        "world_cup": "world_cup",
        "copa_america": "copa_america",
        "euro": "euro",
    }
    q = _norm(query)
    for alias, competition in aliases.items():
        if alias in q:
            return competition
    counts = Counter(str(row.get("competition", "")) for row in rows if row.get("competition"))
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _norm(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", ascii_value.lower())).strip("_")
