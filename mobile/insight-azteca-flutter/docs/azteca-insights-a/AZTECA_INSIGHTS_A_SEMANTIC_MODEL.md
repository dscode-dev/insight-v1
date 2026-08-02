# AZTECA-INSIGHTS-A — Semantic Model

`lib/features/insights/model/insight_metrics.dart` — pure Dart (no widgets), unit-testable, reusable by
Profile / Match Detail / Explore / Live / Radar. Consumes PRODUCT projections only.

## Principle: distinct claims get distinct types (no god-object "Metric")
A scalar, a delta, a probability, a confidence, a comparison, a series, a distribution and an explanation are
**different claims about the world**. Flattening them into one `MetricCard` is how fabrication happens. The
type system is the first line of defence — **each type can only be constructed with the data its claim
requires**:

| Type | Claim | Fabrication defence (enforced by the type) |
|---|---|---|
| `MetricValue` | "this quantity is X" | freshness defaults to `unknown` (never guessed) |
| `MetricDelta` | "X changed from P to C" | **requires `previous`** — no baseline ⇒ impossible to build ⇒ no arrow. `percentageDelta` is **null when baseline is 0** (never ∞/100%). `polarity` states whether up is good (never assumed) |
| `MetricDirection` | up/down/stable/**unknown** | `unknown` is first-class: UI renders no arrow |
| `ProbabilityMetric` | "outcome chance is p" | **asserts 0..1**; `confidence` is a separate optional field — there is **no constructor path from confidence → probability** |
| `ConfidenceMetric` | "this estimate is reliable to degree c" | asserts 0..1; bands are a *presentation* mapping, never a probability |
| `ComparisonMetric` | "A vs B on one metric/unit" | `ratio`/`leftShare` are **null on a zero denominator / nothing to compare** |
| `TrendPoint` / `TrendSeries` | "ordered observations moved" | **asserts ≥2 points** — a trend from one scalar cannot be represented. Auto-sorts by time; `direction` compares real first vs last; `asDelta` reuses delta semantics |
| `DistributionMetric` | "mass over ≥2 outcomes" | asserts ≥2 buckets; `shares` normalize; empty when total ≤ 0 |
| `InsightExplanation` | "why, in product language" | has **no field capable of carrying internals** (no vectors/detector names/replay meta). `InsightSource` = platform/community/market/historical/unknown |
| `MetricFreshness` | live/recent/stale/historical/**unknown** | `unknown` when the contract has no timestamp |
| `MetricPolarity` | higherIsBetter/lowerIsBetter/neutral | caller states it; `isFavourable` is **null** for neutral (no judgement) |

## Notable semantics
- `MetricDelta.isFavourable` returns `false` for "conceded goals up" (`lowerIsBetter`) — "up" is not always good.
- `TrendSeries.asDelta` lets a series reuse delta rendering without a second code path.
- Everything is `@immutable`; most constructors are `const`.

Tests: `test/insight_semantics_test.dart` (20) lock every defence above.
