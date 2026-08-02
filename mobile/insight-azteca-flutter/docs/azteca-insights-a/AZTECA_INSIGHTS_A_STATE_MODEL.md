# AZTECA-INSIGHTS-A — State, Error & Freshness Semantics

## Distinguished states (never collapsed into "No data")
| State | Meaning | Profile Statistics behaviour (implemented) |
|---|---|---|
| loading | request in flight | `CircularProgressIndicator` |
| empty | contract returned zero-valued totals | real zeros rendered ("0 publicações" is a truthful fact, not an error) |
| error | request failed | `ErrorState` "Métricas indisponíveis" + **retry** (invalidates the provider) |
| unavailable / feature-disabled | capability gated off (`FeatureUnavailable`) | calm "Em breve" placeholder (existing `FeatureUnavailableView`) — no network call |
| unauthorized | 401 | auth layer clears session → login redirect |
| stale | contract carries an old timestamp | `FreshnessIndicator` (Desatualizado) — only when a timestamp exists |
| partial | some metrics missing | **per-metric rendering**: a missing optional metric omits its own tile; it does NOT blank the panel |

## Partial-payload rule
Each primitive is independently constructed from one claim. A null/absent optional (delta, confidence,
freshness, ratio) degrades **that element only** — never the surrounding insight panel.

## Freshness semantics (NOT invented)
Categories `live | recent | stale | historical | unknown`. **`unknown` is the default and renders nothing.**
No thresholds were invented: the only real contract (`sports-profile`) carries **no timestamp**, so Profile
metrics are `unknown` (no chip) rather than being labelled with a guessed freshness. Concrete thresholds will
be defined against the producing contract's real cadence when one exists (Live/Radar).
