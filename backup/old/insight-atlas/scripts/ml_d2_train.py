"""ML-D.2 frozen-dataset certification, projection, training, and candidate gate.

This job is deliberately offline. It reads a copied Explorer validated lake,
never calls a collection adapter, never publishes, and never promotes a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    log_loss,
)

from atlas.outcome.model import OutcomeClassifier
from atlas.outcome.projection import HistoricalMatch, HistoricalProjection
from atlas.outcome.schema import (
    FEATURE_NAMES_OUTCOME,
    OUTCOME_LABELS,
    OUTCOME_SCHEMA_VERSION,
)

RUN_ID = "mld1-collection-20260622-031848"
RUN_START = datetime.fromisoformat("2026-06-22T03:18:50.457102+00:00")
RUN_END = datetime.fromisoformat("2026-06-22T11:10:37.278914+00:00")
DATASET_VERSION = "outcome_v1-mld1-20260622"
LABEL_SOURCE = "historical_outcome"


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def canonical_row(envelope: dict[str, Any]) -> dict[str, Any] | None:
    payload = envelope.get("payload") or {}
    score = payload.get("score") or {}
    home = payload.get("home_team") or {}
    away = payload.get("away_team") or {}
    if (
        envelope.get("entity_type") != "fixture"
        or payload.get("status") != "finished"
        or score.get("home") is None
        or score.get("away") is None
        or not payload.get("scheduled_at")
        or not (home.get("club_id") or home.get("name"))
        or not (away.get("club_id") or away.get("name"))
    ):
        return None
    competition = (envelope.get("competition") or {}).get("competition_key")
    return {
        "external_id": str(envelope.get("external_id") or ""),
        "scheduled_at": payload["scheduled_at"],
        "competition": competition or payload.get("competition_key") or "",
        "season": str(envelope.get("season") or payload.get("season") or ""),
        "source": str(envelope.get("source") or ""),
        "home": home.get("club_id") or home.get("name"),
        "away": away.get("club_id") or away.get("name"),
        "home_score": int(score["home"]),
        "away_score": int(score["away"]),
        "neutral": (competition == "world_cup"),
        "captured_at": envelope.get("captured_at"),
        "record_checksum": envelope.get("_checksum")
        or (envelope.get("provenance") or {}).get("checksum"),
    }


def load_generation(lake: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    physical_rows = 0
    entity_counts: Counter[str] = Counter()
    rejected_projection = 0
    lineage: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, str]] = set()

    for path in sorted(lake.rglob("*.jsonl")):
        file_rows = 0
        file_selected = 0
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for raw in handle:
                digest.update(raw)
                if not raw.strip():
                    continue
                physical_rows += 1
                file_rows += 1
                envelope = json.loads(raw)
                captured = envelope.get("captured_at")
                if not captured:
                    continue
                captured_at = parse_dt(captured)
                if not (RUN_START <= captured_at <= RUN_END):
                    continue
                entity_counts[str(envelope.get("entity_type") or "unknown")] += 1
                row = canonical_row(envelope)
                if row is None:
                    rejected_projection += 1
                    continue
                key = (row["source"], row["external_id"])
                if key in seen:
                    continue
                seen.add(key)
                selected.append(row)
                file_selected += 1
        if file_selected:
            lineage[str(path)] = {
                "physical_rows": file_rows,
                "selected_rows": file_selected,
                "sha256": f"sha256:{digest.hexdigest()}",
            }

    selected.sort(key=lambda row: (row["scheduled_at"], row["external_id"]))
    stats = {
        "physical_lake_rows": physical_rows,
        "generation_entity_counts": dict(sorted(entity_counts.items())),
        "projection_rejected_rows": rejected_projection,
        "source_files": len(lineage),
        "lineage": lineage,
    }
    return selected, stats


def load_jobs(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    jobs: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            job = json.loads(line)
            started = job.get("started_at")
            if started and RUN_START <= parse_dt(started) <= RUN_END:
                jobs.append(job)
    return {
        "jobs": len(jobs),
        "contributed": sum(int(job.get("records_validated") or 0) > 0 for job in jobs),
        "validated": sum(int(job.get("records_validated") or 0) for job in jobs),
        "rejected": sum(int(job.get("records_rejected") or 0) for job in jobs),
        "review": sum(int(job.get("records_review") or 0) for job in jobs),
        "failed": sum(job.get("status") == "failed" for job in jobs),
    }


def load_operations(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    events = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("run_id") == RUN_ID:
                events.append(event)
    parent = [
        event
        for event in events
        if event.get("event_type")
        in {"explorer.source.completed", "explorer.source.partial"}
    ]
    attempts = [
        attempt
        for event in parent
        for attempt in (event.get("metadata") or {}).get("per_source", [])
    ]
    completed = next(
        (
            event
            for event in events
            if event.get("event_type") == "explorer.collection.completed"
        ),
        {},
    )
    summary = completed.get("metadata") or {}
    return {
        "jobs": int(summary.get("done") or len(parent)),
        "planned": int(summary.get("planned") or len(parent)),
        "contributed": int(
            summary.get("contributed")
            or sum(event.get("event_type") == "explorer.source.completed" for event in parent)
        ),
        "validated": int(
            summary.get("total_validated")
            or sum(int((event.get("metadata") or {}).get("validated") or 0) for event in parent)
        ),
        "source_attempts": len(attempts),
        "rejected": sum(int(attempt.get("rejected") or 0) for attempt in attempts),
        "review": sum(int(attempt.get("review") or 0) for attempt in attempts),
        "failed": sum(attempt.get("status") == "failed" for attempt in attempts),
        "events": len(events),
    }


def write_dataset(rows: list[dict[str, Any]], out_dir: Path, audit: dict[str, Any]) -> dict[str, Any]:
    dataset_dir = out_dir / "datasets" / DATASET_VERSION
    dataset_dir.mkdir(parents=True, exist_ok=True)
    matches_path = dataset_dir / "matches.jsonl"
    content = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
    ).encode()
    matches_path.write_bytes(content)
    content_hash = f"sha256:{hashlib.sha256(content).hexdigest()}"
    competitions: Counter[str] = Counter(row["competition"] for row in rows)
    seasons: Counter[str] = Counter(row["season"] for row in rows)
    sources: Counter[str] = Counter(row["source"] for row in rows)
    comp_seasons: Counter[str] = Counter(
        f"{row['competition']}/{row['season']}" for row in rows
    )
    labels = Counter(
        "HOME_WIN" if row["home_score"] > row["away_score"]
        else "DRAW" if row["home_score"] == row["away_score"]
        else "AWAY_WIN"
        for row in rows
    )
    manifest = {
        "dataset_version": DATASET_VERSION,
        "source_run_id": RUN_ID,
        "immutable": True,
        "rows": len(rows),
        "content_hash": content_hash,
        "label_source": LABEL_SOURCE,
        "feature_schema_version": OUTCOME_SCHEMA_VERSION,
        "label_definition": "result_v1",
        "competitions": dict(sorted(competitions.items())),
        "seasons": dict(sorted(seasons.items())),
        "competition_seasons": dict(sorted(comp_seasons.items())),
        "sources": dict(sorted(sources.items())),
        "label_distribution": dict(sorted(labels.items())),
        "odds_coverage_rows": 0,
        "statistics_coverage_rows": 0,
        "lineage": audit["lineage"],
    }
    (dataset_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (dataset_dir / "SHA256SUMS").write_text(
        f"{content_hash.removeprefix('sha256:')}  matches.jsonl\n", encoding="utf-8"
    )
    return manifest


def project(rows: list[dict[str, Any]]) -> tuple[list[Any], dict[str, Any]]:
    matches = [
        HistoricalMatch(
            uid=row["external_id"],
            kickoff_at=parse_dt(row["scheduled_at"]),
            competition=row["competition"],
            season=row["season"],
            home=row["home"],
            away=row["away"],
            home_score=row["home_score"],
            away_score=row["away_score"],
            neutral=row["neutral"],
        )
        for row in rows
    ]
    projected = HistoricalProjection().project(matches)
    X = np.asarray([row.vector() for row in projected], dtype=float)
    variances = X.var(axis=0)
    missing = int(np.isnan(X).sum() + np.isinf(X).sum())
    return projected, {
        "rows": len(projected),
        "features": len(FEATURE_NAMES_OUTCOME),
        "feature_variance": {
            name: float(variances[i]) for i, name in enumerate(FEATURE_NAMES_OUTCOME)
        },
        "zero_variance_features": [
            name for i, name in enumerate(FEATURE_NAMES_OUTCOME) if variances[i] == 0.0
        ],
        "missing_or_infinite_values": missing,
        "cold_start_rows": sum(row.prior_matches == 0 for row in projected),
        "leakage_protection": "strict kickoff_at < target kickoff; update history after projection",
        "label_source": LABEL_SOURCE,
        "label_distribution": dict(sorted(Counter(row.label for row in projected).items())),
    }


def metrics(model: OutcomeClassifier, rows: list[Any]) -> dict[str, Any]:
    X = np.asarray([row.vector() for row in rows], dtype=float)
    y = np.asarray([model.label_id(row.label) for row in rows], dtype=int)
    pred = model.booster.predict(X).astype(int)
    prob = model.booster.predict_proba(X)
    confidences = prob.max(axis=1)
    entropy = -np.sum(prob * np.log(prob + 1e-9), axis=1) / np.log(len(OUTCOME_LABELS))
    return {
        "rows": len(rows),
        "accuracy": float(accuracy_score(y, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)),
        "log_loss": float(log_loss(y, prob, labels=list(range(len(OUTCOME_LABELS))))),
        "mean_confidence": float(confidences.mean()),
        "mean_uncertainty": float(entropy.mean()),
        "confusion_matrix": confusion_matrix(
            y, pred, labels=list(range(len(OUTCOME_LABELS)))
        ).tolist(),
        "labels": OUTCOME_LABELS,
    }


def train(projected: list[Any], out_dir: Path, dataset: dict[str, Any]) -> dict[str, Any]:
    n = len(projected)
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)
    train_rows = projected[:train_end]
    val_rows = projected[train_end:val_end]
    holdout_rows = projected[val_end:]
    X_train = np.asarray([row.vector() for row in train_rows], dtype=float)
    y_train = np.asarray(
        [OutcomeClassifier.label_id(row.label) for row in train_rows], dtype=int
    )
    model = OutcomeClassifier.train(X_train, y_train)
    majority_id, majority_count = Counter(y_train.tolist()).most_common(1)[0]
    holdout_y = np.asarray(
        [OutcomeClassifier.label_id(row.label) for row in holdout_rows], dtype=int
    )
    baseline_accuracy = float((holdout_y == majority_id).mean())
    result = {
        "split": {
            "strategy": "chronological_70_15_15",
            "train_end": train_rows[-1].kickoff_at.isoformat(),
            "validation_end": val_rows[-1].kickoff_at.isoformat(),
            "holdout_end": holdout_rows[-1].kickoff_at.isoformat(),
        },
        "train": metrics(model, train_rows),
        "validation": metrics(model, val_rows),
        "holdout": metrics(model, holdout_rows),
        "majority_baseline": {
            "class": OUTCOME_LABELS[majority_id],
            "train_rows": majority_count,
            "holdout_accuracy": baseline_accuracy,
        },
        "previous_candidate": {
            "dataset_version": "outcome_v1-20260621",
            "holdout_accuracy": 0.4358,
            "holdout_baseline": 0.5028,
            "beats_baseline": False,
        },
        "feature_importance": dict(
            sorted(model.feature_importance.items(), key=lambda item: item[1], reverse=True)
        ),
    }
    result["beats_baseline"] = (
        result["holdout"]["accuracy"] > result["majority_baseline"]["holdout_accuracy"]
    )
    result["holdout_lift"] = (
        result["holdout"]["accuracy"] - result["majority_baseline"]["holdout_accuracy"]
    )

    candidate_dir = out_dir / "candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    if result["beats_baseline"]:
        artifact_path = candidate_dir / f"{DATASET_VERSION}.pkl"
        with artifact_path.open("wb") as handle:
            pickle.dump(model.to_state(), handle)
        artifact_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        candidate = {
            "status": "candidate",
            "promoted": False,
            "artifact": str(artifact_path),
            "artifact_sha256": f"sha256:{artifact_hash}",
            "dataset_version": DATASET_VERSION,
            "dataset_content_hash": dataset["content_hash"],
            "label_source": LABEL_SOURCE,
            "feature_schema_version": OUTCOME_SCHEMA_VERSION,
            "metrics": dict(result),
        }
        (candidate_dir / f"{DATASET_VERSION}.manifest.json").write_text(
            json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        result["candidate"] = candidate
    else:
        result["candidate"] = {
            "status": "rejected",
            "promoted": False,
            "reason": "holdout accuracy did not exceed the majority-class baseline",
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("lake", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--jobs", type=Path)
    parser.add_argument("--events", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    rows, audit = load_generation(args.lake)
    jobs = load_jobs(args.jobs)
    audit["jobs"] = jobs
    operations = load_operations(args.events)
    audit["operations"] = operations
    generation_rows = sum(audit["generation_entity_counts"].values())
    expected_validated = operations.get("validated") or jobs.get("validated")
    if expected_validated and expected_validated != generation_rows:
        raise SystemExit(
            "certification failed: "
            f"operations validated={expected_validated} generation rows={generation_rows}"
        )
    if not rows:
        raise SystemExit("certification failed: no ML-D.1 rows")

    dataset = write_dataset(rows, args.out, audit)
    projected, projection = project(rows)
    if projection["missing_or_infinite_values"] or projection["zero_variance_features"]:
        raise SystemExit(f"projection failed: {projection}")
    training = train(projected, args.out, dataset)
    report = {
        "certification": audit,
        "dataset": dataset,
        "projection": projection,
        "training": training,
    }
    (args.out / "ml_d2_results.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
