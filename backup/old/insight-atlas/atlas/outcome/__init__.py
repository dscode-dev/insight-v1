"""Outcome Learning Track (ML-C.5b Stage 1).

An ISOLATED historical learning track that learns from real football OUTCOMES.
It coexists with — and never touches — the live intelligence engine:

  * It does NOT import or modify atlas.features (the live 11-feature schema),
    atlas.inference, atlas.trends, atlas.market, or atlas.intelligence.
  * It is NOT wired into the live API / inference / trend / Nexus paths.
  * It learns ONLY from real match results (atlas.outcome.labels), never from
    any Atlas output (prediction / confidence / trend / recommendation).

Components:
  schema       — outcome_v1 feature names + labels + defaults
  labels       — result label derived strictly from final score
  projection   — leakage-safe pre-match feature projection (as_of < kickoff)
  model        — OutcomeClassifier (XGBoost) with probabilities + confidence

This package is the home of the track; training is driven by an offline job /
script, mirroring the live track's staged-candidate + explicit-promotion model.
"""

from atlas.outcome.schema import (
    FEATURE_NAMES_OUTCOME,
    OUTCOME_LABELS,
    OUTCOME_SCHEMA_VERSION,
    outcome_defaults,
)
from atlas.outcome.labels import result_label
from atlas.outcome.projection import HistoricalProjection, ProjectedRow
from atlas.outcome.model import OutcomeClassifier, OutcomePrediction

__all__ = [
    "FEATURE_NAMES_OUTCOME",
    "OUTCOME_LABELS",
    "OUTCOME_SCHEMA_VERSION",
    "outcome_defaults",
    "result_label",
    "HistoricalProjection",
    "ProjectedRow",
    "OutcomeClassifier",
    "OutcomePrediction",
]
