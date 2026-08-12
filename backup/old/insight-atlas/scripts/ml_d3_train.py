"""ML-D.3 outcome_v2 feature engineering, weighting, and calibration."""

from __future__ import annotations

import hashlib
import json
import math
import pickle
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import xgboost as xgb
from scipy.optimize import minimize_scalar
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    log_loss,
    precision_recall_fscore_support,
)

from atlas.outcome.projection import HistoricalMatch
from atlas.outcome.projection_v2 import HistoricalProjectionV2
from atlas.outcome.schema import OUTCOME_LABELS, OUTCOME_LABEL_TO_ID
from atlas.outcome.schema_v2 import (
    FEATURE_NAMES_OUTCOME_V2,
    FEATURE_SCHEMA_VERSION_V2,
    OUTCOME_VERSION_V2,
)

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "artifacts/ml-d2/datasets/outcome_v1-mld1-20260622/matches.jsonl"
OUT = ROOT / "artifacts/ml-d3"
RUN_ID = "mld3-atlas-outcome-v2-20260622"
DATASET_VERSION = "outcome_v2-mld1-20260622"


def load_matches() -> list[HistoricalMatch]:
    rows: list[HistoricalMatch] = []
    with DATASET.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            rows.append(
                HistoricalMatch(
                    uid=row["external_id"],
                    kickoff_at=datetime.fromisoformat(
                        row["scheduled_at"].replace("Z", "+00:00")
                    ),
                    competition=row["competition"],
                    season=row["season"],
                    home=row["home"],
                    away=row["away"],
                    home_score=int(row["home_score"]),
                    away_score=int(row["away_score"]),
                    neutral=bool(row["neutral"]),
                )
            )
    return rows


def arrays(rows: list[Any]) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.asarray([row.vector() for row in rows], dtype=np.float32),
        np.asarray([OUTCOME_LABEL_TO_ID[row.label] for row in rows], dtype=np.int64),
    )


def sample_weights(y: np.ndarray, strategy: str) -> np.ndarray:
    counts = np.bincount(y, minlength=3).astype(float)
    balanced = len(y) / (3.0 * counts)
    if strategy == "none":
        weights = np.ones(3)
    elif strategy == "balanced":
        weights = balanced
    elif strategy == "sqrt_balanced":
        weights = np.sqrt(balanced)
    elif strategy == "draw_1.25":
        weights = np.array([1.0, 1.25, 1.0])
    elif strategy == "draw_1.50":
        weights = np.array([1.0, 1.50, 1.0])
    elif strategy == "draw_1.75":
        weights = np.array([1.0, 1.75, 1.0])
    else:
        raise ValueError(strategy)
    return weights[y]


def train_model(
    X: np.ndarray,
    y: np.ndarray,
    *,
    strategy: str,
    depth: int,
    estimators: int,
    learning_rate: float,
) -> xgb.XGBClassifier:
    model = xgb.XGBClassifier(
        n_estimators=estimators,
        max_depth=depth,
        learning_rate=learning_rate,
        min_child_weight=4,
        reg_lambda=2.0,
        reg_alpha=0.05,
        subsample=0.9,
        colsample_bytree=0.85,
        random_state=7,
        n_jobs=1,
        tree_method="hist",
        device="cpu",
        objective="multi:softprob",
        num_class=3,
        eval_metric="mlogloss",
    )
    model.fit(X, y, sample_weight=sample_weights(y, strategy))
    return model


def class_metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    precision, recall, f1, support = precision_recall_fscore_support(
        y, pred, labels=[0, 1, 2], zero_division=0
    )
    return {
        OUTCOME_LABELS[index]: {
            "precision": float(precision[index]),
            "recall": float(recall[index]),
            "f1": float(f1[index]),
            "support": int(support[index]),
        }
        for index in range(3)
    }


def evaluate(y: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    prediction = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    uncertainty = -np.sum(probabilities * np.log(probabilities + 1e-9), axis=1)
    uncertainty /= math.log(3)
    return {
        "rows": len(y),
        "accuracy": float(accuracy_score(y, prediction)),
        "balanced_accuracy": float(balanced_accuracy_score(y, prediction)),
        "log_loss": float(log_loss(y, probabilities, labels=[0, 1, 2])),
        "mean_confidence": float(confidence.mean()),
        "mean_uncertainty": float(uncertainty.mean()),
        "confusion_matrix": confusion_matrix(y, prediction, labels=[0, 1, 2]).tolist(),
        "classes": class_metrics(y, prediction),
    }


def selection_score(metrics: dict[str, Any]) -> float:
    if metrics["accuracy"] < 0.48:
        return -1.0
    draw_recall = metrics["classes"]["DRAW"]["recall"]
    return (
        metrics["balanced_accuracy"]
        + 0.20 * draw_recall
        + 0.10 * metrics["accuracy"]
        - 0.05 * metrics["log_loss"]
    )


def calibrate(
    validation_prob: np.ndarray,
    validation_y: np.ndarray,
    holdout_prob: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    def apply_temperature(probabilities: np.ndarray, temperature: float) -> np.ndarray:
        logits = np.log(np.clip(probabilities, 1e-9, 1.0)) / temperature
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        return exp / exp.sum(axis=1, keepdims=True)

    result = minimize_scalar(
        lambda temperature: log_loss(
            validation_y,
            apply_temperature(validation_prob, temperature),
            labels=[0, 1, 2],
        ),
        bounds=(0.25, 4.0),
        method="bounded",
    )
    temperature = float(result.x)
    return apply_temperature(holdout_prob, temperature), {
        "method": "temperature_scaling_on_validation_probabilities",
        "temperature": temperature,
        "validation_log_loss": float(result.fun),
        "preserves_argmax": True,
    }


def confidence_buckets(y: np.ndarray, probabilities: np.ndarray) -> list[dict[str, Any]]:
    pred = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    buckets = []
    for low in np.arange(0.3, 1.0, 0.1):
        high = min(low + 0.1, 1.0)
        mask = (confidence >= low) & (
            confidence <= high if high == 1.0 else confidence < high
        )
        count = int(mask.sum())
        if not count:
            continue
        buckets.append(
            {
                "low": round(float(low), 2),
                "high": round(float(high), 2),
                "count": count,
                "mean_confidence": float(confidence[mask].mean()),
                "accuracy": float((pred[mask] == y[mask]).mean()),
            }
        )
    return buckets


def expected_calibration_error(buckets: list[dict[str, Any]], total: int) -> float:
    return float(
        sum(
            bucket["count"]
            / total
            * abs(bucket["mean_confidence"] - bucket["accuracy"])
            for bucket in buckets
        )
    )


def reliability_svg(
    before: list[dict[str, Any]], after: list[dict[str, Any]], path: Path
) -> None:
    width = height = 640
    margin = 70
    plot = width - 2 * margin

    def point(value: float) -> float:
        return margin + value * plot

    def polyline(buckets: list[dict[str, Any]]) -> str:
        return " ".join(
            f"{point(bucket['mean_confidence']):.1f},{height-point(bucket['accuracy']):.1f}"
            for bucket in buckets
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">
<rect width="100%" height="100%" fill="#0b1020"/>
<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{margin}" stroke="#64748b" stroke-dasharray="8 8"/>
<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" stroke="#cbd5e1"/>
<line x1="{margin}" y1="{height-margin}" x2="{margin}" y2="{margin}" stroke="#cbd5e1"/>
<polyline points="{polyline(before)}" fill="none" stroke="#f59e0b" stroke-width="4"/>
<polyline points="{polyline(after)}" fill="none" stroke="#22c55e" stroke-width="4"/>
<text x="80" y="35" fill="#f8fafc" font-size="24">ML-D.3 holdout reliability</text>
<text x="260" y="625" fill="#cbd5e1" font-size="18">Mean confidence</text>
<text x="10" y="320" fill="#cbd5e1" font-size="18" transform="rotate(-90 20 320)">Accuracy</text>
<text x="420" y="65" fill="#f59e0b" font-size="16">raw</text>
<text x="500" y="65" fill="#22c55e" font-size="16">calibrated</text>
</svg>"""
    path.write_text(svg, encoding="utf-8")


def feature_definition(name: str) -> dict[str, str]:
    if name.startswith(("home_wins_", "home_draws_", "home_losses_", "home_points_",
                        "away_wins_", "away_draws_", "away_losses_", "away_points_")):
        source = "prior team results"
        null = "0 until prior matches exist"
    elif "goals_for_" in name or "goals_against_" in name or "goal_difference_" in name:
        source = "prior final scores"
        null = "0 until prior matches exist"
    elif name in {
        "home_strength", "away_strength", "home_win_rate", "away_win_rate",
        "home_goal_rate", "away_goal_rate",
    }:
        source = "prior venue-conditioned team results"
        null = "0 until venue history exists"
    elif name.startswith(("last_h2h", "h2h_")):
        source = "prior head-to-head final scores"
        null = "0 until a prior head-to-head exists"
    elif "league_" in name or "rank_change" in name:
        source = "derived pre-match competition-season table"
        null = "bottom/zero default before table history exists"
    elif name.startswith(("opening_", "closing_", "implied_", "bookmaker_")) or name == "odds_available":
        source = "pre-kickoff Football-Data 1X2 odds"
        null = "0 with odds_available=0"
    elif name.endswith("rest_days"):
        source = "prior team kickoff timestamps"
        null = "14 days normalized to 30"
    elif name == "home_advantage":
        source = "competition venue context"
        null = "1 except known neutral competitions"
    else:
        source = "derived from prior form features"
        null = "0 from component defaults"
    return {
        "source": source,
        "null_handling": null,
        "leakage_protection": "only records with kickoff_at < target kickoff; target recorded after projection",
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    matches = load_matches()
    projected = HistoricalProjectionV2().project(matches)
    n = len(projected)
    train_end = int(n * 0.70)
    validation_end = int(n * 0.85)
    train_rows = projected[:train_end]
    validation_rows = projected[train_end:validation_end]
    holdout_rows = projected[validation_end:]
    X_train, y_train = arrays(train_rows)
    X_validation, y_validation = arrays(validation_rows)
    X_holdout, y_holdout = arrays(holdout_rows)

    variances = X_train.var(axis=0)
    trials = []
    best: tuple[float, xgb.XGBClassifier, dict[str, Any], dict[str, Any]] | None = None
    for strategy in (
        "none",
        "sqrt_balanced",
        "balanced",
        "draw_1.25",
        "draw_1.50",
        "draw_1.75",
    ):
        for depth, estimators, learning_rate in (
            (2, 180, 0.05),
            (3, 180, 0.05),
            (3, 260, 0.035),
            (4, 180, 0.04),
        ):
            model = train_model(
                X_train,
                y_train,
                strategy=strategy,
                depth=depth,
                estimators=estimators,
                learning_rate=learning_rate,
            )
            validation_metrics = evaluate(y_validation, model.predict_proba(X_validation))
            params = {
                "weight_strategy": strategy,
                "max_depth": depth,
                "n_estimators": estimators,
                "learning_rate": learning_rate,
            }
            score = selection_score(validation_metrics)
            trials.append(
                {"params": params, "selection_score": score, "validation": validation_metrics}
            )
            if best is None or score > best[0]:
                best = (score, model, params, validation_metrics)

    assert best is not None
    _, model, params, validation_metrics = best
    raw_holdout_prob = model.predict_proba(X_holdout)
    raw_validation_prob = model.predict_proba(X_validation)
    calibrated_holdout_prob, calibration = calibrate(
        raw_validation_prob, y_validation, raw_holdout_prob
    )

    raw_train = evaluate(y_train, model.predict_proba(X_train))
    raw_holdout = evaluate(y_holdout, raw_holdout_prob)
    calibrated_holdout = evaluate(y_holdout, calibrated_holdout_prob)
    raw_buckets = confidence_buckets(y_holdout, raw_holdout_prob)
    calibrated_buckets = confidence_buckets(y_holdout, calibrated_holdout_prob)
    calibration["raw_buckets"] = raw_buckets
    calibration["calibrated_buckets"] = calibrated_buckets
    calibration["raw_ece"] = expected_calibration_error(raw_buckets, len(y_holdout))
    calibration["calibrated_ece"] = expected_calibration_error(
        calibrated_buckets, len(y_holdout)
    )

    importance = dict(
        sorted(
            (
                (name, float(value))
                for name, value in zip(
                    FEATURE_NAMES_OUTCOME_V2,
                    model.feature_importances_,
                    strict=True,
                )
            ),
            key=lambda item: item[1],
            reverse=True,
        )
    )
    class_counts = Counter(y_train.tolist())
    class_weights = {
        OUTCOME_LABELS[index]: len(y_train) / (3.0 * class_counts[index])
        for index in range(3)
    }
    feature_audit = {
        name: {
            "variance": float(variances[index]),
            "importance": float(model.feature_importances_[index]),
            "available": bool(variances[index] > 0),
        }
        for index, name in enumerate(FEATURE_NAMES_OUTCOME_V2)
    }

    previous = {
        "accuracy": 0.49242424242424243,
        "balanced_accuracy": 0.3721547246567707,
        "draw_recall": 0.008670520231213872,
        "mean_uncertainty": 0.9325333833694458,
        "log_loss": 1.0329508781433105,
    }
    chosen_holdout = calibrated_holdout
    comparison = {
        "accuracy_delta": chosen_holdout["accuracy"] - previous["accuracy"],
        "balanced_accuracy_delta": (
            chosen_holdout["balanced_accuracy"] - previous["balanced_accuracy"]
        ),
        "draw_recall_delta": (
            chosen_holdout["classes"]["DRAW"]["recall"] - previous["draw_recall"]
        ),
        "uncertainty_delta": (
            chosen_holdout["mean_uncertainty"] - previous["mean_uncertainty"]
        ),
        "log_loss_delta": chosen_holdout["log_loss"] - previous["log_loss"],
    }
    improves = (
        comparison["balanced_accuracy_delta"] > 0
        and comparison["draw_recall_delta"] > 0
        and comparison["log_loss_delta"] < 0
    )

    candidate_dir = OUT / "candidates"
    candidate_dir.mkdir(exist_ok=True)
    candidate: dict[str, Any]
    if improves:
        artifact_path = candidate_dir / f"{OUTCOME_VERSION_V2}-mld1-20260622.pkl"
        state = {
            "booster": model,
            "calibration": calibration,
            "feature_names": FEATURE_NAMES_OUTCOME_V2,
            "feature_schema_version": FEATURE_SCHEMA_VERSION_V2,
            "outcome_version": OUTCOME_VERSION_V2,
            "decision": "argmax_calibrated_probability",
        }
        artifact_path.write_bytes(pickle.dumps(state))
        candidate = {
            "status": "candidate",
            "promoted": False,
            "artifact": str(artifact_path),
            "artifact_sha256": "sha256:"
            + hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        }
    else:
        candidate = {
            "status": "rejected",
            "promoted": False,
            "reason": "outcome_v2 did not improve balanced accuracy, draw recall, and log loss together",
        }

    reliability_svg(raw_buckets, calibrated_buckets, OUT / "reliability_diagram.svg")
    result = {
        "run_id": RUN_ID,
        "dataset_version": DATASET_VERSION,
        "source_dataset": "outcome_v1-mld1-20260622",
        "feature_schema_version": FEATURE_SCHEMA_VERSION_V2,
        "outcome_version": OUTCOME_VERSION_V2,
        "rows": n,
        "feature_count": len(FEATURE_NAMES_OUTCOME_V2),
        "feature_names": FEATURE_NAMES_OUTCOME_V2,
        "feature_audit": feature_audit,
        "zero_variance_features": [
            name
            for index, name in enumerate(FEATURE_NAMES_OUTCOME_V2)
            if variances[index] == 0
        ],
        "odds_coverage_rows": 0,
        "competition_context": {
            "method": "derived pre-match competition-season table",
            "external_official_table_available": False,
        },
        "class_distribution": {
            OUTCOME_LABELS[index]: class_counts[index] for index in range(3)
        },
        "balanced_class_weights": class_weights,
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
        "trials": sorted(trials, key=lambda item: item["selection_score"], reverse=True),
        "train": raw_train,
        "validation": validation_metrics,
        "holdout_raw": raw_holdout,
        "holdout_calibrated": calibrated_holdout,
        "calibration": calibration,
        "feature_importance": importance,
        "previous_candidate": previous,
        "comparison": comparison,
        "candidate": candidate,
    }
    schema = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION_V2,
        "outcome_version": OUTCOME_VERSION_V2,
        "feature_count": len(FEATURE_NAMES_OUTCOME_V2),
        "features": {
            name: feature_definition(name) for name in FEATURE_NAMES_OUTCOME_V2
        },
    }
    (OUT / "feature_schema_v2.json").write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUT / "ml_d3_results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (candidate_dir / f"{OUTCOME_VERSION_V2}-mld1-20260622.manifest.json").write_text(
        json.dumps(
            {
                **candidate,
                "dataset_version": DATASET_VERSION,
                "source_dataset": "outcome_v1-mld1-20260622",
                "feature_schema_version": FEATURE_SCHEMA_VERSION_V2,
                "outcome_version": OUTCOME_VERSION_V2,
                "label_source": "historical_outcome",
                "selected_params": params,
                "metrics": {
                    "train": raw_train,
                    "validation": validation_metrics,
                    "holdout_raw": raw_holdout,
                    "holdout_calibrated": calibrated_holdout,
                    "comparison": comparison,
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
                "selected_params": params,
                "holdout_raw": raw_holdout,
                "holdout_calibrated": calibrated_holdout,
                "comparison": comparison,
                "candidate": candidate,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
