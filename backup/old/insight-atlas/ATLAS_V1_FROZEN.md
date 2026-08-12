# ATLAS V1 — FROZEN BASELINE

**Status:** Architecture FROZEN (2026-07-02). Certification: **PARTIAL** — the deterministic intelligence,
replay and quality-gate core is certified READY; live pgvector/deploy/real-dataset verification is the
operator's remaining gate (see ATLAS_CERTIFY_A_REPORT.md). The *architecture* is frozen regardless: the
remaining items are operational verification, not structural change.

## Frozen architecture
```
Explorer history ─► Atlas Intelligence (Signal State · Behavior · Reasoning · Regime · Evidence)
                         │
Hub streams ─► Canonical Consumer ─► TrendInputs ─► Trend Engine (22 detectors, incl. Oracle)
                         │                                   │
             Similarity Capability                    insight:stream:trends ─► IOC
             ├─ Online  (pgvector: Service→Cache→Repository)
             └─ Offline (dataset: DeterministicVectorIndex / SimilarityEngine)
                         │
             Deterministic Replay ─► Quality Gate (Manifest · Detector/Pipeline eval ·
             Quality metrics · Regression · Promotion · Explainability) ─► IOC events + artifacts
```

## Frozen versions
trend v4 · intelligence atlas.intelligence.v1 · similarity/embedding atlas-memory-embedding-v1 ·
feature_schema feature_schema_v2 · operational_event insight.operational_event.v1 · replay_engine 1.0.0 ·
22 detectors.

## Supported capabilities (V1)
Deterministic descriptive intelligence (trends: market/momentum/historical/impact/narrative/meta),
online + offline similarity, Oracle historical similarity/pattern/deviation, deterministic replay over
real Explorer history, quality gate with promotion recommendations + explainability, canonical IOC events.

## Official contracts (stable)
- `TrendInputs`, `Trend` (schema v4), `insight:stream:trends` envelope.
- `SimilarityContext` / `SimilarityCapability` (context/batch/health/capabilities) — ADR-0001.
- Replay: `ReplayScenario/Result/Manifest/Artifacts/Execution`, `QualityEvaluation` (Detector/Quality/
  Regression/Promotion/Explainability reports).
- `insight.operational_event.v1` operational event envelope.

## Compatibility guarantees
- Wire enums are ADDITIVE-ONLY (trend types, similarity domains, event types).
- Contracts extend by ADDING optional fields; existing fields/serialization are stable.
- The online-vector read path has ONE source of truth (SimilarityService); offline similarity is a
  separate, documented domain (ADR-0001) and must not be merged.
- Detectors, thresholds, Oracle/Behavior/Reasoning/Similarity logic and embeddings are FROZEN for V1.

## Extension policy — V1.1 roadmap (built ON TOP, not restructuring)
- Memory, Calibration, Explainability enhancements, new detectors, outcome-labelled precision/recall,
  learning capabilities → V1.1. Every new detector/heuristic MUST pass the Quality Gate (regression +
  promotion) against the frozen baseline before promotion. Human approval remains mandatory.

## Explicitly OUTSIDE V1 scope
- ML/LLM predictions, win-probability/betting outputs (physically absent by design).
- Detector-labelled (outcome ground-truth) precision/recall.
- The `atlas/outcome` ML training pipeline (experimental; no promoted production model).

## Regression baseline
Record a real-dataset replay `ReplayManifest` + `ReplayHash` + `QualityEvaluation` from Google Cloud as
the frozen baseline; all future replays diff against it via the Quality Gate regression report.
