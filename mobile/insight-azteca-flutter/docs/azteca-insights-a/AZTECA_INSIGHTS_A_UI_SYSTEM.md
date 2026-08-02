# AZTECA-INSIGHTS-A — Intelligence UI System

`lib/features/insights/widgets/insight_primitives.dart`. One reusable visual language; not page decoration.

## Implemented (justified by real data + near-term V1 usage)
| Primitive | Purpose | Honesty guarantee |
|---|---|---|
| `InsightMetricCard` | scalar tile (label + value + optional freshness + optional delta) | delta only renders if a real `MetricDelta` (baseline) exists |
| `MetricValueRow` | dense label→value row | same |
| `DirectionIndicator` | ↑/↓/→ + **word** | `unknown` ⇒ no arrow; neutral polarity ⇒ no good/bad colour |
| `DeltaIndicator` | "↑ +8,4%" | falls back to the **absolute** change when % is undefined (zero baseline) |
| `FreshnessIndicator` | Ao vivo / Recente / Desatualizado / Histórico | `unknown` ⇒ renders **nothing** |
| `ProbabilityBar` | bounded 0..1 + `%` | continuous bar — a *different* visual language from confidence |
| `ConfidenceIndicator` | 3 discrete segments + word (Alta/Média/Baixa) | segmented, never a continuous probability bar |
| `ComparisonBar` | two-sided A vs B | renders **"—"** when there is nothing to compare |
| `InsightExplanationCard` | product-language summary + factors + evidence summary + source | no field can carry model internals |

## Deliberately NOT implemented
`CompactSparkline`, `TrendChart`, `DistributionChart` — no consumable series/distribution contract exists
(Stage 0). Building them now would invite fabrication. The **model** (`TrendSeries`, `DistributionMetric`)
exists so the widgets are a small, additive step once a real contract lands.

## Design
Compact sports density; `context.ds` tokens only (reuses the purpose-built `confidenceHigh/Mid/Low`,
`signal`, `card`, `divider`, `subtle`, `textLow/Mid/High` — no invented colours); 12px radii; 0.6px borders;
no dashboard cards, no neon; automatically dark/light correct (theme extension); `FontFeature.tabularFigures`
so numbers align as they grow.

## Reuse
Same primitives are intended for Profile (now), and Match Detail / Explore / Live / Radar later — no
per-screen metric widgets.
