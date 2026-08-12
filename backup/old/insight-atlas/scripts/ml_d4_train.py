"""ML-D.4 offline recovery from already-collected Football-Data raw rows."""

from __future__ import annotations

import glob
import hashlib
import json
import pickle
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from atlas.outcome.projection import HistoricalMatch
from atlas.outcome.projection_v3 import HistoricalProjectionV3, vector_v3
from atlas.outcome.schema import OUTCOME_LABEL_TO_ID
from atlas.outcome.schema_v3 import (
    FEATURE_NAMES_OUTCOME_V3,
    FEATURE_SCHEMA_VERSION_V3,
    OUTCOME_VERSION_V3,
)
from scripts.ml_d3_train import (
    calibrate,
    confidence_buckets,
    evaluate,
    expected_calibration_error,
    reliability_svg,
    train_model,
)

ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = Path("/private/tmp/mld4-raw/raw")
OUT = ROOT / "artifacts/ml-d4"
DATASET_VERSION = "market_v1-football-data-mld1-20260622"
RUN_ID = "mld4-atlas-outcome-v3-20260622"


def slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")


def number(row: dict[str, Any], key: str) -> float | None:
    try:
        value = float(row.get(key))
        return value if value > 1.0 else None
    except (TypeError, ValueError):
        return None


def triplet(row: dict[str, Any], candidates: list[tuple[str, str, str]]) -> dict[str, float] | None:
    for home_key, draw_key, away_key in candidates:
        values = [number(row, key) for key in (home_key, draw_key, away_key)]
        if all(value is not None for value in values):
            return {
                "home": float(values[0]),
                "draw": float(values[1]),
                "away": float(values[2]),
            }
    return None


def parse_date(value: str) -> datetime:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"invalid Football-Data date {value!r}")


def load_raw() -> tuple[list[HistoricalMatch], dict[str, dict[str, dict[str, float]]], dict[str, Any]]:
    matches: list[HistoricalMatch] = []
    odds_by_uid: dict[str, dict[str, dict[str, float]]] = {}
    competitions: Counter[str] = Counter()
    seasons: Counter[str] = Counter()
    bookmaker_coverage: Counter[str] = Counter()
    missing_odds = 0
    source_files = sorted(glob.glob(str(RAW_ROOT / "**/football_data/**/*.jsonl"), recursive=True))
    lineage = []

    for filename in source_files:
        path = Path(filename)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        file_rows = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            envelope = json.loads(line)
            row = envelope["raw"]
            uid = envelope["external_id"]
            home_score = int(float(row["FTHG"]))
            away_score = int(float(row["FTAG"]))
            competition = envelope["competition_key"]
            season = envelope["season"]
            opening = triplet(
                row,
                [
                    ("B365H", "B365D", "B365A"),
                    ("PSH", "PSD", "PSA"),
                    ("AvgH", "AvgD", "AvgA"),
                    ("BbAvH", "BbAvD", "BbAvA"),
                ],
            )
            closing = triplet(
                row,
                [
                    ("PSCH", "PSCD", "PSCA"),
                    ("AvgCH", "AvgCD", "AvgCA"),
                    ("MaxCH", "MaxCD", "MaxCA"),
                ],
            )
            if opening:
                bookmaker_coverage["opening"] += 1
            if closing:
                bookmaker_coverage["closing"] += 1
            for name, keys in (
                ("bet365", ("B365H", "B365D", "B365A")),
                ("pinnacle_open", ("PSH", "PSD", "PSA")),
                ("pinnacle_close", ("PSCH", "PSCD", "PSCA")),
                ("market_avg_open", ("AvgH", "AvgD", "AvgA")),
                ("market_avg_close", ("AvgCH", "AvgCD", "AvgCA")),
                ("legacy_avg", ("BbAvH", "BbAvD", "BbAvA")),
            ):
                if all(number(row, key) is not None for key in keys):
                    bookmaker_coverage[name] += 1
            if opening or closing:
                odds_by_uid[uid] = {
                    "opening": opening or closing,
                    "closing": closing or opening,
                }
            else:
                missing_odds += 1
            matches.append(
                HistoricalMatch(
                    uid=uid,
                    kickoff_at=parse_date(row["Date"]),
                    competition=competition,
                    season=season,
                    home=f"football_data:{competition}:{slug(row['HomeTeam'])}",
                    away=f"football_data:{competition}:{slug(row['AwayTeam'])}",
                    home_score=home_score,
                    away_score=away_score,
                )
            )
            competitions[competition] += 1
            seasons[f"{competition}/{season}"] += 1
            file_rows += 1
        lineage.append(
            {
                "file": str(path),
                "rows": file_rows,
                "sha256": f"sha256:{digest}",
            }
        )
    matches.sort(key=lambda match: (match.kickoff_at, match.uid))
    audit = {
        "raw_rows": len(matches),
        "source_files": len(source_files),
        "matches_with_odds": len(odds_by_uid),
        "missing_odds": missing_odds,
        "odds_coverage": len(odds_by_uid) / len(matches),
        "competitions": dict(sorted(competitions.items())),
        "competition_seasons": dict(sorted(seasons.items())),
        "bookmaker_coverage": dict(sorted(bookmaker_coverage.items())),
        "lineage": lineage,
    }
    return matches, odds_by_uid, audit


def matrix(rows) -> tuple[np.ndarray, np.ndarray]:  # type: ignore[no-untyped-def]
    return (
        np.asarray([vector_v3(row) for row in rows], dtype=np.float32),
        np.asarray([OUTCOME_LABEL_TO_ID[row.label] for row in rows], dtype=np.int64),
    )


def feature_definition(name: str) -> dict[str, str]:
    if name.startswith(("opening_", "closing_", "implied_", "market_", "favorite_")):
        source = "Football-Data pre-kickoff 1X2 CSV columns"
        null = "0 with odds_available=0"
    elif "elo" in name or name in {"home_rating", "away_rating"}:
        source = "sequential historical result ELO before target kickoff"
        null = "1500 rating normalized to 0.5"
    elif "attack_strength" in name or "defense_strength" in name:
        source = "last ten prior scores relative to competition-season goal rate"
        null = "0 until prior history exists"
    elif name in {"league_strength", "competition_weight"}:
        source = "pre-match participant ELO / documented competition prior"
        null = "0.5 / 0.75 default"
    else:
        source = "feature_schema_v2"
        null = "inherited feature_schema_v2 handling"
    return {
        "source": source,
        "null_handling": null,
        "leakage_protection": "strictly prior kickoff state; timestamp batches recorded after projection",
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    matches, odds_by_uid, audit = load_raw()
    projected = HistoricalProjectionV3(odds_by_uid).project(matches)
    n = len(projected)
    train_end = int(n * 0.70)
    validation_end = int(n * 0.85)
    train_rows = projected[:train_end]
    validation_rows = projected[train_end:validation_end]
    holdout_rows = projected[validation_end:]
    X_train, y_train = matrix(train_rows)
    X_validation, y_validation = matrix(validation_rows)
    X_holdout, y_holdout = matrix(holdout_rows)

    trials = []
    best = None
    for strategy in ("none", "sqrt_balanced", "draw_1.25", "draw_1.50", "balanced"):
        for depth, estimators, learning_rate in (
            (2, 180, 0.05),
            (3, 220, 0.04),
            (4, 220, 0.035),
        ):
            model = train_model(
                X_train,
                y_train,
                strategy=strategy,
                depth=depth,
                estimators=estimators,
                learning_rate=learning_rate,
            )
            metrics = evaluate(y_validation, model.predict_proba(X_validation))
            score = (
                metrics["accuracy"]
                + 0.25 * metrics["balanced_accuracy"]
                - 0.05 * metrics["log_loss"]
                if metrics["balanced_accuracy"] >= 0.45
                else -1.0
            )
            params = {
                "weight_strategy": strategy,
                "max_depth": depth,
                "n_estimators": estimators,
                "learning_rate": learning_rate,
            }
            trials.append({"params": params, "selection_score": score, "validation": metrics})
            if best is None or score > best[0]:
                best = (score, model, params, metrics)
    assert best is not None
    _, model, params, validation_metrics = best
    raw_train = evaluate(y_train, model.predict_proba(X_train))
    raw_holdout_prob = model.predict_proba(X_holdout)
    raw_validation_prob = model.predict_proba(X_validation)
    raw_holdout = evaluate(y_holdout, raw_holdout_prob)
    calibrated_prob, calibration = calibrate(
        raw_validation_prob, y_validation, raw_holdout_prob
    )
    calibrated_holdout = evaluate(y_holdout, calibrated_prob)
    raw_buckets = confidence_buckets(y_holdout, raw_holdout_prob)
    calibrated_buckets = confidence_buckets(y_holdout, calibrated_prob)
    calibration.update(
        {
            "raw_buckets": raw_buckets,
            "calibrated_buckets": calibrated_buckets,
            "raw_ece": expected_calibration_error(raw_buckets, len(y_holdout)),
            "calibrated_ece": expected_calibration_error(
                calibrated_buckets, len(y_holdout)
            ),
        }
    )

    variances = X_train.var(axis=0)
    importance = {
        name: float(value)
        for name, value in sorted(
            zip(FEATURE_NAMES_OUTCOME_V3, model.feature_importances_, strict=True),
            key=lambda item: item[1],
            reverse=True,
        )
    }
    market_names = {
        name
        for name in FEATURE_NAMES_OUTCOME_V3
        if name.startswith(("opening_", "closing_", "implied_", "market_", "favorite_"))
        or name in {"bookmaker_spread", "odds_available"}
    }
    strength_names = {
        "home_elo_rating",
        "away_elo_rating",
        "elo_difference",
        "home_attack_strength",
        "away_attack_strength",
        "home_defense_strength",
        "away_defense_strength",
        "home_rating",
        "away_rating",
        "league_strength",
        "competition_weight",
    }

    def ablation(names: set[str]) -> dict[str, Any]:
        indices = [
            index for index, name in enumerate(FEATURE_NAMES_OUTCOME_V3) if name in names
        ]
        train = X_train.copy()
        validation = X_validation.copy()
        holdout = X_holdout.copy()
        train[:, indices] = 0
        validation[:, indices] = 0
        holdout[:, indices] = 0
        ablated_model = train_model(
            train,
            y_train,
            strategy=params["weight_strategy"],
            depth=params["max_depth"],
            estimators=params["n_estimators"],
            learning_rate=params["learning_rate"],
        )
        return {
            "removed_features": sorted(names),
            "validation": evaluate(y_validation, ablated_model.predict_proba(validation)),
            "holdout": evaluate(y_holdout, ablated_model.predict_proba(holdout)),
        }

    ablations = {
        "without_market": ablation(market_names),
        "without_elo_team_competition_strength": ablation(strength_names),
    }
    candidate_dir = OUT / "candidates"
    candidate_dir.mkdir(exist_ok=True)
    artifact = candidate_dir / "outcome_v3-football-data-mld1-20260622.pkl"
    artifact.write_bytes(
        pickle.dumps(
            {
                "booster": model,
                "temperature": calibration["temperature"],
                "feature_names": FEATURE_NAMES_OUTCOME_V3,
                "feature_schema_version": FEATURE_SCHEMA_VERSION_V3,
                "outcome_version": OUTCOME_VERSION_V3,
                "competition_weights": __import__(
                    "atlas.outcome.projection_v3", fromlist=["COMPETITION_WEIGHTS"]
                ).COMPETITION_WEIGHTS,
            }
        )
    )
    candidate = {
        "status": "candidate",
        "promoted": False,
        "artifact": str(artifact),
        "artifact_sha256": "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    schema = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION_V3,
        "outcome_version": OUTCOME_VERSION_V3,
        "feature_count": len(FEATURE_NAMES_OUTCOME_V3),
        "features": {
            name: feature_definition(name) for name in FEATURE_NAMES_OUTCOME_V3
        },
    }
    (OUT / "feature_schema_v3.json").write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    reliability_svg(raw_buckets, calibrated_buckets, OUT / "reliability_diagram.svg")
    result = {
        "run_id": RUN_ID,
        "dataset_version": DATASET_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION_V3,
        "outcome_version": OUTCOME_VERSION_V3,
        "recovery": audit,
        "rows": n,
        "feature_count": len(FEATURE_NAMES_OUTCOME_V3),
        "split": {
            "strategy": "chronological_70_15_15",
            "train_rows": len(train_rows),
            "validation_rows": len(validation_rows),
            "holdout_rows": len(holdout_rows),
            "train_end": train_rows[-1].kickoff_at.isoformat(),
            "validation_end": validation_rows[-1].kickoff_at.isoformat(),
            "holdout_end": holdout_rows[-1].kickoff_at.isoformat(),
        },
        "selected_params": params,
        "trials": sorted(trials, key=lambda trial: trial["selection_score"], reverse=True),
        "train": raw_train,
        "validation": validation_metrics,
        "holdout_raw": raw_holdout,
        "holdout_calibrated": calibrated_holdout,
        "calibration": calibration,
        "feature_variance": {
            name: float(variances[index])
            for index, name in enumerate(FEATURE_NAMES_OUTCOME_V3)
        },
        "feature_importance": importance,
        "ablations": ablations,
        "candidate": candidate,
        "comparison_mld3": {
            "accuracy_delta": calibrated_holdout["accuracy"] - 0.49924242424242427,
            "balanced_accuracy_delta": calibrated_holdout["balanced_accuracy"]
            - 0.4158015453587573,
            "uncertainty_delta": calibrated_holdout["mean_uncertainty"]
            - 0.9423883557319641,
            "ece_delta": calibration["calibrated_ece"] - 0.04506066680857631,
        },
    }
    (OUT / "ml_d4_results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (candidate_dir / "outcome_v3-football-data-mld1-20260622.manifest.json").write_text(
        json.dumps(
            {
                **candidate,
                "dataset_version": DATASET_VERSION,
                "feature_schema_version": FEATURE_SCHEMA_VERSION_V3,
                "outcome_version": OUTCOME_VERSION_V3,
                "label_source": "historical_outcome",
                "odds_coverage": audit["odds_coverage"],
                "selected_params": params,
                "metrics": {
                    "train": raw_train,
                    "validation": validation_metrics,
                    "holdout": calibrated_holdout,
                    "calibration": calibration,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "recovery": {key: value for key, value in audit.items() if key != "lineage"},
                "selected_params": params,
                "holdout": calibrated_holdout,
                "calibration": calibration,
                "candidate": candidate,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
