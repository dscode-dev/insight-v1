"""Deterministic dataset quality engine (ML-C Part 4).

Computes a reproducible quality_score (0.0–1.0) per competition/season/source
and per competition, from job records + reconciliation summaries. Pure
function of its inputs — same inputs always yield the same score.

Dimensions (weighted):
  completeness        validated / collected
  validation_success  validated / (validated + review + rejected)
  consistency         1 - rejected / considered
  duplicate_cleanliness 1 - duplicate_rate
  agreement           cross-source mean confidence (or trust proxy)
"""

from __future__ import annotations

from typing import Any

_WEIGHTS = {
    "completeness": 0.25,
    "validation_success": 0.30,
    "consistency": 0.20,
    "duplicate_cleanliness": 0.15,
    "agreement": 0.10,
}


def _safe(n: float, d: float) -> float:
    return n / d if d else 0.0


def score_dataset(jobs: list[dict[str, Any]], agreement: float | None) -> dict[str, Any]:
    collected = sum(j.get("records_collected", 0) for j in jobs)
    validated = sum(j.get("records_validated", 0) for j in jobs)
    review = sum(j.get("records_review", 0) for j in jobs)
    rejected = sum(j.get("records_rejected", 0) for j in jobs)
    dups = sum(j.get("duplicates_removed", 0) for j in jobs)
    considered = validated + review + rejected

    dims = {
        "completeness": _safe(validated, collected) if collected else 0.0,
        "validation_success": _safe(validated, considered) if considered else 0.0,
        "consistency": 1.0 - _safe(rejected, considered) if considered else 1.0,
        "duplicate_cleanliness": 1.0 - _safe(dups, collected) if collected else 1.0,
        "agreement": agreement if agreement is not None else 0.7,
    }
    quality = round(sum(dims[k] * w for k, w in _WEIGHTS.items()), 4)
    return {
        "quality_score": quality,
        "grade": "A" if quality >= 0.85 else "B" if quality >= 0.7 else "C" if quality >= 0.5 else "D",
        "dimensions": {k: round(v, 4) for k, v in dims.items()},
        "records": {"collected": collected, "validated": validated, "review": review,
                    "rejected": rejected, "duplicates_removed": dups},
    }
