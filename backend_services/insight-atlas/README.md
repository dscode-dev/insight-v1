# insight-atlas — ML Context Layer (Layer M)

Atlas is the only surface in Insight that runs machine-learning models.
It produces **contextual intelligence** — descriptive observations,
behavioural clusters, anomaly flags, historical resemblances — and
never produces betting predictions, win-probability outputs, or tipster
behaviour.

## Forbidden outputs

The service is built so that the following are physically impossible to
return, because no model in Atlas is trained for them:

- "Bet on X"
- "Team X has Y% chance of winning"
- "Guaranteed movement"
- "Safe prediction"

## Allowed outputs

- "Momentum increase detected"
- "Historical patterns indicate elevated pressure behaviour"
- "Community activity increased significantly"
- "Unusual market movement detected"
- "This match resembles previous high-volatility events"

## Models

| Model                | Family                | Purpose                                          |
|----------------------|-----------------------|--------------------------------------------------|
| IsolationForest      | unsupervised anomaly  | market / behaviour anomaly score                 |
| HDBSCAN              | density clustering    | discover variable-density behaviour clusters     |
| KMeans               | flat clustering       | stable cluster IDs across re-fits                |
| XGBoost classifier   | gradient boosting     | contextual class (balanced / late-pressure …)    |
| LightGBM ranker      | gradient boosting     | contextual ranking (used by Radar)               |
| CosineSimilarity     | numpy                 | nearest historical matches for a feature vector  |

No LLM. No neural network. No black box.

## Explainability

**Every** Atlas output carries:

- `context_confidence` ∈ [0, 1] — model's own confidence (raw signal)
- `data_confidence` ∈ [0, 1] — fraction of features that came from real
  upstream data (vs registry-default imputed)
- `source_confidence` — dict `{source_id: trust}` of every declared
  upstream source contributing to the snapshot
- `final_confidence` ∈ [0, 1] — combined score via a pluggable
  `ConfidencePolicy`. Default = `feature_quality × min(source_confidence) × data_confidence`
- `top_factors` — ordered list of `(feature_name, contribution)` pairs
- `model_version` — semver of the model that produced the output
- `model_name` — semantic name (e.g. `anomaly_isolation_forest`)
- `feature_schema_version` — schema version of the feature vector (currently `2`)
- `feature_window_origin` — `rolling | live | historical | static | aggregated | unknown`
- `sources` — list of `SourceRef(source_id, source_type, confidence)`

There is no path through Atlas that yields a black-box scalar.

### Confidence policy (Sprint 0.1)

The combination formula is **not hardcoded**. `ConfidencePolicy` is a
runtime-checkable Protocol in `atlas/inference/confidence_policy.py`.
The default `ConservativeProductPolicy` multiplies the three axes
using `min(source_confidence)` as the reducer over the source dict.

Custom reducers are injectable without subclassing:

```python
from atlas.inference.confidence_policy import ConservativeProductPolicy

policy = ConservativeProductPolicy(
    source_reducer=lambda d: sum(d.values()) / len(d) if d else 1.0,
)
engine = InferenceEngine(
    registry=registry,
    feature_schema_version=2,
    confidence_policy=policy,
)
```

A future weighted-by-source-type policy would implement the
`ConfidencePolicy` protocol and pass into the engine the same way.

### Source taxonomy (Sprint 0.1)

`atlas/contracts/source.py` declares `SourceType` — the canonical set
of provenance categories, additive-only and mirrored by the upcoming
Sports Data Hub:

| Value             | Meaning                                           |
| ----------------- | ------------------------------------------------- |
| `official_api`    | League-direct API                                 |
| `commercial_api`  | Licensed provider (api_football, sportmonks)      |
| `official_club`   | Club's verified official channel                  |
| `official_league` | League's verified official channel                |
| `trusted_media`   | Vetted press partner                              |
| `internal_bot`    | Atlas/Hub crawler — **CANDIDATE ONLY**            |
| `community`       | User-generated (signals, posts, sentiment)        |
| `unknown`         | Ingested before provenance was tagged             |

`SourceType.candidate_sources()` returns the subset
(`internal_bot`, `community`, `unknown`) that must never be promoted
to "official fact" by downstream consumers.

#### SourceRef shape (Sprint 0.1.1)

`SourceRef` carries the full provenance of each declared source.
Additive-only over Sprint 0.1 — V1 payloads (just `source_id` +
`source_type` + `confidence`) still validate; new fields are filled
with sensible defaults.

| Field             | Type           | Required by producer | Notes                                                                                                |
| ----------------- | -------------- | -------------------- | ---------------------------------------------------------------------------------------------------- |
| `source_id`       | str            | yes                  | canonical id (≤64 chars)                                                                             |
| `source_name`     | str            | recommended          | human label (≤128 chars); falls back to `source_id` if empty                                         |
| `source_type`     | `SourceType`   | yes                  | enum slug                                                                                            |
| `confidence`      | float ∈ [0,1]  | yes                  | trust this run had IN the source                                                                     |
| `observed_at`     | datetime       | recommended          | tz-aware; defaults to `now(UTC)` if omitted — quarantine may flag default-filled values in Sprint 1  |
| `adapter_version` | str?           | optional             | `"{adapter}@{semver}"` e.g. `"api_football@1.4.2"`                                                   |
| `metadata`        | dict[str, Any] | optional             | opaque per-adapter bag (endpoint, etag, rate-limit headers, …)                                       |

The Sports Data Hub (Go) will populate every field for adapter-sourced
events. Community/user-sourced refs typically leave `adapter_version`
null and `metadata` empty.

### Feature window origin (Sprint 0.1)

`atlas/contracts/window.py` — `FeatureWindowOrigin` declares HOW a
snapshot's window was assembled:

- `rolling` — periodic worker on fixed cadence (worker default)
- `live` — on-demand build during a REST inference call
- `historical` — back-fill / replay
- `static` — features that don't vary within a match
- `aggregated` — multi-match summary
- `unknown` — ingested before tagging

## Architecture

```text
Insight Gateway          →   Anvil analytics API   →   feature pipeline
      │                                                     │
      │ HTTPS + Atlas API key                               ▼
      └──────────────────────────────────────────── feature store (Redis)
                                                            │
                                                            ▼
                                                    model engine
                                                            │
                                            ┌───────────────┼───────────────┐
                                            ▼               ▼               ▼
                                   REST inference   ML_CONTEXT events    model registry
                                   (Gateway)        (derived stream)     (Postgres)
```

Inference runs ONLY inside Atlas. Training is strictly
asynchronous.

## Migration notes — schema v1 → v2 (Sprint 0.1)

`FEATURE_SCHEMA_VERSION` default in `atlas/config/settings.py` bumped
from `1` to `2`. The change removes `engagement_rate` from
`FEATURE_NAMES` (it was always emitting its registry default — a
constant — because the upstream `feed_reactions` rollup never landed,
contaminating cluster/anomaly distance metrics).

**Operational impact:**

- Models trained against schema v1 are filtered out by the engine's
  schema-mismatch guard (`atlas/inference/engine.py:_get`). They stay
  inert until retrained. No compatibility shim.
- Cached snapshots in Redis with `schema_version=1` are now caught by
  the Sprint 0 quarantine layer (`schema_version_mismatch`).
- `bootstrap_labels()` no longer references `engagement_rate`. The
  `high_engagement` label still exists; it now fires solely from
  `signal_density >= 1.5`.
- `bootstrap_relevance()` in the ranker dropped its
  `engagement_rate * 0.05` term — replaced with a marginal bump from
  `signal_density * 0.25` so the ranker still rewards crowded matches.

**Retrain checklist on deploy:**

1. Roll the new code (services boot on schema v2 by default).
2. Old v1 models stop serving inference automatically. There is no
   degradation in correctness — they simply stop responding.
3. Trigger training for each family against schema v2 via
   `POST /v1/internal/training/{family}` (synthetic data path
   continues to work; production analytics are read through the
   Gateway-mediated Anvil API).
4. Promote the new v2 versions via
   `POST /v1/internal/models/{version_id}/promote`.

## Contract surface (Sprint 0.1)

| Field on FeatureSnapshot / ContextOutput | Type | Added in | Notes |
| --- | --- | --- | --- |
| `feature_snapshot_id` / `output_id` | UUID | Sprint 0 | identity |
| `sport` | str (`"football"`) | Sprint 0 | enforced via whitelist |
| `competition_id` | UUID? | Sprint 0 | required by Sprint 0 spec |
| `season` | str? | Sprint 0 | nullable for back-fill |
| `feature_version` / `feature_schema_version` | int | Sprint 0 | aliased; v2 default |
| `data_confidence` | float [0,1] | Sprint 0 | fraction of real (non-imputed) features |
| `source_confidence` | dict[str, float] | Sprint 0.1 | computed projection of `sources` |
| `sources` | list[SourceRef] | Sprint 0.1 | canonical typed provenance |
| `feature_window_origin` | enum | Sprint 0.1 | how the window was built |
| `final_confidence` | float [0,1]? | Sprint 0.1 | policy-combined; only on ContextOutput |
| `model_name` | str? | Sprint 0 | semantic model name |
| `label_source` | enum (on ModelVersion) | Sprint 0 | lineage of training labels |

## Targets

- Inference: p95 < 50ms
- Training: async only
- Feature snapshot cadence (live matches): 30s

## Running

```bash
poetry install
poetry run uvicorn atlas.main:app --host 0.0.0.0 --port 8085
```

## Testing

```bash
poetry run pytest -q
```

Tests cover each model wrapper, the explainer, the training pipeline,
the inference engine, the Anvil analytics port, and the registry.
Postgres / Redis integrations are mocked or replaced with
`fakeredis` / `aiosqlite`.
