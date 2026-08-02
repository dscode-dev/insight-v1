# AZTECA-INSIGHTS-A — V1 Scope Classification

| Surface | Class | Evidence |
|---|---|---|
| **Profile Statistics** | **READY** | backend-authoritative totals via `sports-profile`, rendered with the primitives; **fabricated "precisão" removed** |
| **Profile Signals** | **PARTIAL** (honest) | real signals COUNT surfaced (SQL-counted); no list contract ⇒ no fabricated cards (unchanged from PROFILE-B) |
| **Match metrics** | **BLOCKED_BY_CONTRACT** | no `/v1/live|context` route exists |
| **Probabilities** | **BLOCKED_BY_CONTRACT** | model + `ProbabilityBar` built; no producer |
| **Confidence** | **BLOCKED_BY_CONTRACT** | model + `ConfidenceIndicator` built; no producer |
| **Trends** | **BLOCKED_BY_CONTRACT** | `TrendSeries` built; no series contract ⇒ nothing rendered, no chart added |
| **Historical comparison** | **BLOCKED_BY_CONTRACT** | `ComparisonMetric`/`ComparisonBar` built; no producer |
| **Explainability** | **BLOCKED_BY_CONTRACT** | model + card built; no product explanation contract |
| **Charts** | **DEFERRED** (activation condition documented) | no consumable series ⇒ no dependency added |
| **Live intelligence** | **DEFERRED_TO_LIVE_RADAR** | routes absent, feature-gated OFF |
| **Radar intelligence** | **DEFERRED_TO_LIVE_RADAR** | routes absent, feature-gated OFF |
| **Realtime metric push** | **DEFERRED_TO_REALTIME** | architecture is compatible (immutable models); not implemented |

## Sprint classification (against THIS sprint's approved scope)
The approved scope was: audit the boundary, build the semantic language + primitives, integrate the **real**
data, decide charts on evidence, and refuse fabrication. **All of that is delivered ⇒ the sprint is READY.**
Live/Radar/match intelligence being BLOCKED_BY_CONTRACT is an *upstream producer* fact documented by the
audit — it does not make this sprint PARTIAL.
