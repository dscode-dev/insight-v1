"""Offline outcome-learning training job (ML-C.5b Stage 1).

Reads Explorer validated fixture JSONL, runs the leakage-safe projection,
temporally splits, trains the OutcomeClassifier, validates on the holdout,
and writes a CANDIDATE artifact (promote=False) + manifest. Mirrors the live
track's staged-candidate model: promotion is a separate, explicit operator step.

Usage:
    python -m atlas.outcome.train <validated_lake_dir> <artifact_out_dir>

This is an OFFLINE job. It is intentionally NOT wired into the live API,
inference, trend, or Nexus paths.
"""

from __future__ import annotations

import glob
import hashlib
import json
import pickle
import sys
import uuid
from datetime import datetime, timezone

import numpy as np

from atlas.ops_emitter import emitter as ops
from atlas.outcome.model import OutcomeClassifier
from atlas.outcome.projection import HistoricalMatch, HistoricalProjection
from atlas.outcome.schema import OUTCOME_LABELS, OUTCOME_SCHEMA_VERSION

_NS = uuid.UUID("00000000-0000-0000-0000-0000a71a5dee")


def _load(lake_dir: str) -> list[HistoricalMatch]:
    out: list[HistoricalMatch] = []
    for path in glob.glob(f"{lake_dir}/**/*.jsonl", recursive=True):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                o = json.loads(line)
                p = o.get("payload") or {}
                if p.get("status") != "finished":
                    continue
                sc = p.get("score") or {}
                if sc.get("home") is None or sc.get("away") is None:
                    continue
                ht = (p.get("home_team") or {}).get("club_id") or (p.get("home_team") or {}).get("name")
                at = (p.get("away_team") or {}).get("club_id") or (p.get("away_team") or {}).get("name")
                if not (ht and at and p.get("scheduled_at")):
                    continue
                comp = (o.get("competition") or {}).get("competition_key")
                out.append(HistoricalMatch(
                    uid=str(uuid.uuid5(_NS, str(o.get("external_id")))),
                    kickoff_at=datetime.fromisoformat(p["scheduled_at"].replace("Z", "+00:00")),
                    competition=comp or "", season=str(o.get("season")),
                    home=ht, away=at, home_score=int(sc["home"]), away_score=int(sc["away"]),
                    neutral=(comp == "world_cup"),
                ))
    return out


def main(lake_dir: str, out_dir: str,
         train_until: int = 2022, val_year: int = 2023, test_year: int = 2024) -> dict:
    run_id = f"atlas_training_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    ops.upsert_run(run_id, kind="training", status="running", run_label=run_id)
    ops.emit_event("atlas.training.started", "outcome_v1 historical training started",
                   run_id=run_id, training_id=run_id)

    rows = HistoricalProjection().project(_load(lake_dir))
    if not rows:
        ops.open_ticket("invalid_dataset", severity="ERROR",
                        impact="no projected rows", recommendation="check Explorer dataset",
                        dedup_key="atlas:outcome:no_rows")
        ops.upsert_run(run_id, kind="training", status="failed", run_label=run_id)
        raise SystemExit("no projected rows")

    def split(pred):
        return [r for r in rows if pred(r.kickoff_at.year)]
    train = split(lambda y: y <= train_until)
    val = split(lambda y: y == val_year)
    test = split(lambda y: y == test_year)
    lid = OutcomeClassifier.label_id

    def mat(rs):
        return (np.array([r.vector() for r in rs], dtype=float),
                np.array([lid(r.label) for r in rs], dtype=int))
    Xtr, ytr = mat(train)
    # ML-C.5e governance: a zero-variance feature matrix means degenerate data
    # (the ML-C.5 failure mode) — raise a CRITICAL ticket, do not silently ship.
    if Xtr.size and float(Xtr.var(axis=0).max()) == 0.0:
        ops.open_ticket("zero_variance", severity="CRITICAL",
                        impact="all features constant — model cannot learn",
                        recommendation="fix projection/dataset; do not promote",
                        dedup_key="atlas:outcome:zero_variance")
    model = OutcomeClassifier.train(Xtr, ytr)

    def acc(rs):
        if not rs:
            return None
        X, y = mat(rs)
        return float((model.booster.predict(X) == y).mean())

    import os
    os.makedirs(f"{out_dir}/candidates", exist_ok=True)
    vid = str(uuid.uuid4())
    artp = f"{out_dir}/candidates/{OUTCOME_SCHEMA_VERSION}-{vid}.pkl"
    with open(artp, "wb") as fh:
        pickle.dump(model.to_state(), fh)
    manifest = {
        "family": "outcome_classifier",
        "feature_schema_version": OUTCOME_SCHEMA_VERSION,
        "label_definition": "result_v1", "labels": OUTCOME_LABELS,
        "label_source": "historical_outcome", "promote": False, "status": "candidate",
        "rows": len(rows), "train": len(train), "val": len(val), "test": len(test),
        "train_acc": acc(train), "val_acc": acc(val), "test_acc": acc(test),
        "artifact": artp,
        "artifact_sha256_16": hashlib.sha256(open(artp, "rb").read()).hexdigest()[:16],
        "feature_importance": model.feature_importance,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    json.dump(manifest, open(f"{out_dir}/candidates/{OUTCOME_SCHEMA_VERSION}-{vid}.manifest.json", "w"), indent=2)

    # ML-C.5e: emit terminal observability.
    ops.emit_event("atlas.validation.completed",
                   f"holdout test_acc={manifest['test_acc']}",
                   run_id=run_id, training_id=run_id,
                   metadata={"train_acc": manifest["train_acc"], "val_acc": manifest["val_acc"],
                             "test_acc": manifest["test_acc"]})
    ops.emit_event("atlas.candidate.created",
                   f"candidate {OUTCOME_SCHEMA_VERSION} {vid[:8]} (promote=false)",
                   run_id=run_id, training_id=run_id,
                   metadata={"artifact_sha256_16": manifest["artifact_sha256_16"],
                             "label_source": "historical_outcome"})
    ops.upsert_run(run_id, kind="training", status="completed", run_label=run_id,
                   summary={"rows": len(rows), "train": len(train), "val": len(val),
                            "test": len(test), "test_acc": manifest["test_acc"]})
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/validated",
         sys.argv[2] if len(sys.argv) > 2 else "/tmp/outcome")
