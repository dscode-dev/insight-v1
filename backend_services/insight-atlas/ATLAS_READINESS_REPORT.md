# ATLAS READINESS REPORT — Trend Intelligence Foundation (Sprint 0)

**Scope:** Can the current Atlas implementation become the platform's Trend
Intelligence Engine (`Sport Hub → Atlas → Trend Stream → Nexus → Atrium → Azteca`)?

**Verdict:** Yes — the substrate was already strong (canonical consumption,
identity, impact, signals, context recalculation, odds history), but Atlas had
**no trend concept at all**: no trend domain model, no detectors, no trend
stream, no trend persistence. Those were the critical missing components and
they were implemented in this sprint (marked ✅ below). What remains is
detector depth (Oracle pattern/similarity online serving), richer live-event
ingestion upstream, and the consumer-side contract hardening listed in §10.

Hard boundaries verified intact: Atlas calls **no LLMs**, generates **no
posts**, and has **zero knowledge** of users/feed/comments/likes/followers/
notifications/UI. The only social-adjacent input is the numeric
`sentiment_delta` / `community_confidence` features from the Plaza reader —
numbers in, numbers out.

---

## 1. Current Architecture

```
insight:stream:events:{match,context,odds}        (Redis Streams, Hub-published)
        │  CanonicalConsumer (consumer group, DLQ, idempotency ledger,
        │   bounded retry, XAUTOCLAIM reclaim, schema_version gate)
        ▼
handle_envelope (atlas/api/app.py)
        ├─ match.odds → OddsHandler → odds_ticks history (PG) → odds features/context (Redis)
        ├─ IntelligencePipeline (atlas/intelligence)
        │     identity → impact → signals → aggregation → publication → context recalc
        ├─ TrendEngine (atlas/trends)  ✅ NEW — 5 families, 15 detectors
        │     → TrendRepository (atlas.trend_events, PG)        ✅ NEW
        │     → TrendPublisher  (insight:stream:trends, Redis)  ✅ NEW
        └─ FeatureSnapshot pipeline → FeatureStore (Redis hot) → inference context
```

Module inventory and assessed fitness:

| Area | Module | Fitness for trend engine |
|---|---|---|
| Canonical consumption | `atlas/streaming/canonical_consumer.py` | **Strong.** At-least-once, idempotent, DLQ, reclaim, schema-gated. Reused as-is. |
| Identity | `atlas/identity` (+ Hub stamp) | **Strong.** `canonical_match_id` unifies providers; persistent alias registry. Trends key on it. |
| Impact | `atlas/event_impact` | **Strong.** Rule-driven LOW→CRITICAL classification; feeds Sentinel detectors. |
| Signals | `atlas/signal_engine`, `atlas/event_aggregation` | **Strong.** Typed signals + windowed aggregation; evidence for trends. |
| Context | `atlas/context_engine` | **Adequate.** Event/odds/time-triggered recalc of momentum/pressure/game-state/implied probabilities. Momentum currently only decays (see §2). |
| Odds engine | `atlas/odds` | **Strong.** Full snapshot history (`odds_ticks`), `outcomes[]` source of truth, consensus context. The Ninja/Oracle detectors run directly on it. |
| Feature engine | `atlas/features` | **Adequate.** 11 features incl. `sentiment_delta`, `community_confidence`, `signal_density`, `pressure_delta` — Pulse/Echo detectors consume them. Gateway-mediated Anvil reads are graceful-degrade. |
| Historical engine | `atlas/historical` + `atlas/models/similarity.py` | **Offline only.** Dataset/catalogue/splits exist; the similarity index is a registry artifact, not served online (see §2). |
| Persistence | `atlas/registry` + `migrations/sql/000{1..5}` | **Strong.** Idempotent SQL migration discipline established. |
| ML inference | `atlas/inference` | Orthogonal. Descriptive context only; not in the trend path. |

## 2. Gaps

| # | Gap | Status |
|---|---|---|
| G1 | **No Trend domain model** — nothing in Atlas represented "a developing pattern" as a first-class typed output. | ✅ Closed: `atlas/trends/models.py` (`Trend`, `TrendType`×17, `TrendCategory`×5, `TrendInputs`). |
| G2 | **No trend detectors** — signals were single-event; nothing correlated odds series + context transitions + features. | ✅ Closed: 15 detectors across ninja/pulse/oracle/sentinel/echo (`atlas/trends/{ninja,pulse,oracle,sentinel,echo}.py`). |
| G3 | **No trend stream** — Atlas published only ML_CONTEXT onto the derived stream; no contract for Nexus. | ✅ Closed: `TrendPublisher` → `insight:stream:trends` (envelope in §7). |
| G4 | **No trend persistence** — no durable, replayable trend history. | ✅ Closed: `atlas.trend_events` + migration `0005`, persist-then-publish. |
| G5 | **No prior-state exposure** — the intelligence pipeline consumed prior context internally but discarded it, so nothing could detect *change*. | ✅ Closed: `IntelligenceResult.prior_context`. |
| G6 | **Oracle depth** — `historical_pattern` / `historical_similarity` need the similarity index served online (it exists as an offline registry artifact). | ⏳ Open — roadmap item R3 (§10). Taxonomy reserved; detectors plug into the same engine protocol. |
| G7 | **Momentum recalc is decay-only** — `recompute_context` decays momentum toward 0; it never rises without the feature layer. Pulse momentum detection therefore leans on `momentum_score`. | ⏳ Open — R4. |
| G8 | **No live granular events** — Hub ingests fixtures/results/standings/odds; goals/cards/subs arrive only via the result lifecycle, not as discrete live events. Sentinel/Pulse run at full power only once the Hub emits live event types (the impact taxonomy already handles them). | ⏳ Open — upstream (Hub) roadmap, R5. |
| G9 | **prior_features not wired** — detectors accept `prior_features`; production wiring passes the current hot snapshot only (several features are already windowed deltas, so the main detectors still function). | ⏳ Open — R6 (small). |

## 3. Missing Domain Concepts (now added)

- **Trend** — typed, evidence-carrying, strength/confidence-separated statement of a developing pattern. Strength = magnitude; confidence = certainty; deliberately orthogonal.
- **TrendType / TrendCategory** — the 17-type, 5-family taxonomy (Ninja, Pulse, Oracle, Sentinel, Echo) as additive-only wire enums.
- **TrendInputs** — the correlation surface: one tick's canonical id, contexts (current+prior), odds timeline, signals, impact, features. Detectors are pure functions over it.
- **TrendDetector protocol** — `detect(TrendInputs) -> list[Trend]`; adding a trend type = write a detector + register it. No engine changes.
- **Trend cooldown** — per-(match, trend_type) re-emission guard (Redis `SET NX EX` via the existing aggregation store), so a developing trend emits once per window, not per event.

## 4. Required Refactors

All deliberately minimal — no rewrites:

1. ✅ `IntelligencePipeline` exposes `prior_context` (additive field).
2. ✅ `OddsRepository` hoisted to a named composition variable in `app.py` so the trend layer reads odds history (was constructed inline).
3. ✅ `handle_envelope` extended with a `run_trends` step (failure-isolated, behind `TRENDS_ENABLED`).
4. ⏳ R4: make `recompute_context` momentum bidirectional (derive from signal/feature deltas rather than decay-only).
5. ⏳ R6: persist a previous-snapshot pointer in the feature store (or a 2-deep history) so `prior_features` is real in production wiring.

No changes required to: consumer, odds handler, identity, impact, signal, aggregation, publication, checkpoint engines. Sport Hub untouched this sprint.

## 5. Required Persistence Changes

- ✅ `atlas.trend_events` (migration `migrations/sql/0005_create_trend_events.sql`): PK `trend_id`, indexes on `(canonical_match_id, trend_type, detected_at)`, `canonical_match_id`, `trend_type`, `detected_at`; JSONB `evidence`. Idempotent, same discipline as 0001–0004. **Run explicitly in production** (auto-create is sqlite/dev only).
- ⏳ Retention: `trend_events` and `odds_ticks` grow unbounded — partitioning/retention policy before sustained multi-competition load (§8).

## 6. Required Stream Changes

- ✅ New stream: `insight:stream:trends` (configurable `TREND_STREAM_KEY`), MAXLEN~100k (`TREND_STREAM_MAXLEN`). Producer: Atlas only. Future consumer: Nexus (consumer group, same at-least-once discipline as Atlas's own consumer — `trend_id` is the dedup key).
- No changes to the three canonical input streams or the derived ML_CONTEXT stream. The trend stream is additive; nothing existing was repurposed.

## 7. Required Contracts

**Trend wire envelope** (`schema_version: "v1"`, published as XADD fields + JSON `payload`):

```json
{
  "schema_version": "v1",
  "trend": {
    "trend_id": "<uuid>",            "schema_version": "v1",
    "trend_type": "market_shift",    "category": "ninja",
    "canonical_match_id": "<uuid>",  "competition_id": "<uuid|null>",
    "minute": 73,
    "strength": 0.56, "confidence": 0.8, "direction": 1,
    "window_seconds": null,
    "evidence": { "implied_prob_prev": 0.541, "implied_prob_now": 0.625, "prob_delta": 0.084, "bookmaker_count": 2 },
    "detected_at": "2026-06-11T02:00:00+00:00"
  }
}
```

Contract rules: enums additive-only; `evidence` is free-form but every detector
emits the numeric facts that justified the detection (auditable without
re-derivation); `canonical_match_id` is the only match key downstream may use;
consumers MUST dedup on `trend_id`. Top-level XADD fields (`trend_type`,
`category`, `canonical_match_id`) allow cheap consumer-side filtering without
JSON parsing.

## 8. Scalability Concerns

- **Detector cost is O(detectors) per envelope**, each pure CPU over small inputs — negligible next to the existing feature build (Anvil API I/O). The one real cost is the odds-history read per odds event; bounded by `ODDS_HISTORY_LIMIT` and amortizable with a Redis-cached tail if needed.
- **Single consumer instance** processes streams serially; multi-instance scale-out already works (consumer groups + Redis-backed cooldowns/checkpoints/aggregations are shared). The identity registry serializes on Postgres — fine at V1 volumes.
- **Table growth**: `trend_events` ≈ low hundreds of rows per match at current thresholds; `odds_ticks` dominates. Retention/partitioning is the first scale task (R7).
- **Stream fan-out**: one trend stream for all families is right for V1; per-family streams are a config-level split later if Nexus consumers need isolation (the envelope already carries `category` as a top-level field).
- **World Cup mode** (Hub-side, Sprint 6.1) increases odds tick rate ~2×; the trend cooldown caps Atlas's output rate per match regardless of input rate.

## 9. Production Risks

| Risk | Mitigation |
|---|---|
| Threshold miscalibration → noisy or silent trend stream | All thresholds are detector constructor params; cooldown caps worst-case noise; `trends_generated_total` vs `trends_suppressed_total` make calibration visible. Tune after first live competition. |
| Publish failure after persist | Persist-then-publish: replayable from `trend_events`; `trends_publish_failed_total` alerts. A replayer job is R8. |
| One broken detector | Engine isolates per-detector exceptions (logged + continue) — tested. |
| Cross-provider identity mis-merge | Inherited from Sprint 6.2: precision-first resolver + alias audit trail; trends keyed on the same id so a fix re-keys consistently. |
| Echo false positives (sentiment features default-imputed when Plaza is down) | `sentiment_delta`/`community_confidence` default to neutral values that sit below detector thresholds; degraded Plaza ⇒ Echo silence, not Echo noise. |
| Migration not applied in prod | Same operational rule as 0003/0004: run `0005` before rollout; report + migration header both state it. |
| `match.odds` minute is absent → Sentinel `risk_increase` rarely fires for odds-only matches | By design (no live minute without live events); resolves with R5. |

## 10. Exact Implementation Roadmap

**Done this sprint (Sprint 0 — foundation):**
- ✅ Trend domain model + taxonomy (17 types / 5 families) — `atlas/trends/models.py`
- ✅ 15 detectors: Ninja×4, Pulse×4, Oracle×1, Sentinel×3, Echo×3
- ✅ TrendEngine (detector isolation + Redis cooldown), TrendPublisher (`insight:stream:trends`), TrendRepository + migration `0005`
- ✅ Pipeline wiring (`run_trends` in `app.py`), settings (`TRENDS_ENABLED`, `TREND_STREAM_KEY`, `TREND_STREAM_MAXLEN`, `TREND_COOLDOWN_SECONDS`)
- ✅ Metrics: `trends_generated_total`, `trends_suppressed_total`, `trends_published_total`, `trends_publish_failed_total` (joins the Sprint 6.2 set)
- ✅ 19 new tests; full suite 134 passed; ruff clean

**Next (ordered):**
- **R1 — Threshold calibration pass** over one full live competition; promote tuned values into Settings.
- **R2 — Nexus consumer contract doc** + consumer-group reference implementation (read-only; lives in Nexus's repo, validates the §7 envelope).
- **R3 — Oracle online**: serve the similarity index from the model registry (active artifact) → implement `historical_similarity` + `historical_pattern` detectors against it.
- **R4 — Bidirectional momentum** in `recompute_context` (derive from windowed signal/feature deltas, not decay-only).
- **R5 — Live event ingestion (Hub)**: emit `match.goal`/`match.card`/`match.substitution` as discrete canonical events; Atlas's impact taxonomy + Sentinel/Pulse detectors already consume them — zero Atlas changes needed.
- **R6 — prior_features wiring**: 2-deep feature snapshot history so delta detectors compare real snapshots in production.
- **R7 — Retention**: partition/expire `odds_ticks` + `trend_events`.
- **R8 — Trend replayer**: ops job re-publishing persisted trends that never reached the stream (`trend_events` ⋈ stream audit).

---

### Validation (this sprint)

- `pytest`: **134 passed** (115 existing + 19 trend tests) — zero regressions
- `ruff check atlas/ tests/`: clean
- `build_app()` smoke: wires 15 detectors, all routes intact
- Go (Sport Hub): untouched this sprint; suites remain green from Sprint 6.2
