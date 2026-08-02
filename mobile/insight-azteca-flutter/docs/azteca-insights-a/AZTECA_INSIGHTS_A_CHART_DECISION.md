# AZTECA-INSIGHTS-A — Charting Library Decision

## Decision: **DEFER the chart dependency. Add nothing.**
`pubspec.yaml` gains no `fl_chart`, no `syncfusion_flutter_charts`.

## Rationale (evidence, not preference)
1. **There is no consumable series.** Stage 0: no `/v1/live/*`, `/v1/radar/*`, `/v1/context/*`, no odds/momentum
   timeline reaches Azteca. A chart library would have **nothing real to draw**. Adding one would only enable
   fabricated sparklines — the exact failure this sprint forbids.
2. **Everything real today is scalar.** Profile totals are counts. Scalars/deltas/arrows/probability bars/
   confidence bands are trivially and better served by native widgets (`LinearProgressIndicator`, `Row`,
   `Container`) — "do not use a chart package to render a number with an arrow."
3. **Cost without benefit.** Any chart package adds bundle weight, an upgrade/maintenance surface and its own
   a11y model, for zero current capability.

## Evaluation (for the activation sprint)
| Option | Verdict |
|---|---|
| **Custom Flutter primitives** | ✅ chosen for scalars/deltas/probability/confidence/comparison — full control of a11y + theme; zero deps |
| **fl_chart** | ✅ **preferred when a real series lands** — BSD-3, pure Dart, no native deps, modest weight, sufficient for time series / sparkline / distribution. Simpler dependency wins |
| **syncfusion_flutter_charts** | ❌ rejected — heavier, commercial-licensing considerations; power we do not need. "Do not add Syncfusion merely because it is powerful" |

## Activation condition (explicit)
Add `fl_chart` **only when** a product contract delivers ≥2 ordered observations (`TrendSeries` becomes
constructible from real data) — e.g. `MatchInsightSummary.trends[]` per CONTRACT_BOUNDARY. At that point:
implement `CompactSparkline` / `TrendChart` behind the existing model, keep scalars/bars custom, and test
empty / 1-point (rejected by the model) / multi-point / large bounded series.
