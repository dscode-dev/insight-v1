# AZTECA-INSIGHTS-A — Metric Semantics Rules

Binding rules. Each is enforced by the type system and/or a test.

| # | Rule | Enforcement |
|---|---|---|
| 1 | **A probability is bounded 0..1** and rendered as a % with a continuous bar | `ProbabilityMetric` asserts bounds; test `bounds enforced` |
| 2 | **Confidence ≠ probability.** Never convert a confidence into a probability | separate types; **no constructor path** between them; distinct visuals (segmented vs continuous); test `confidence is a SEPARATE optional claim` |
| 3 | **A delta requires a reference value** | `MetricDelta` requires `previous`; no baseline ⇒ no delta ⇒ no arrow |
| 4 | **No arrow without a baseline** | `MetricDirection.unknown` renders no arrow; test `unknown direction renders NO directional arrow` |
| 5 | **% change from a zero baseline is undefined** | `percentageDelta` returns **null**; UI shows the absolute change instead |
| 6 | **A trend requires ordered observations (≥2)** | `TrendSeries` asserts `points.length >= 2`; test `single observation is REJECTED` |
| 7 | **No trend line from one scalar** | structurally impossible (rule 6) |
| 8 | **A distribution requires real distribution data (≥2 buckets)** | `DistributionMetric` assert |
| 9 | **Comparison ratios need a meaningful denominator** | `ratio`/`leftShare` return **null** on zero denominator / nothing to compare; UI renders "—" |
| 10 | **"Up" is not universally good** | `MetricPolarity`; `isFavourable` is null for neutral, false for `lowerIsBetter` going up |
| 11 | **No pseudo-precision beyond backend data** | values rendered at source precision; deltas at 1 decimal; percent rounded honestly |
| 12 | **Freshness is never guessed** | `MetricFreshness.unknown` default ⇒ no chip rendered |

## The five concepts, visually separated
- **Probability** — "Vitória A: 64%" → continuous bar + %.
- **Confidence** — "Confiança: Alta" → 3 discrete segments + word (never a % bar).
- **Delta** — "Pressão ↑ +12%" → icon + signed text (needs a baseline).
- **Comparison** — "A 1,42× B" → two-sided bar + both values (needs a denominator).
- **Trend** — "Momentum subindo" → requires ≥2 ordered points (none available today ⇒ not rendered).
