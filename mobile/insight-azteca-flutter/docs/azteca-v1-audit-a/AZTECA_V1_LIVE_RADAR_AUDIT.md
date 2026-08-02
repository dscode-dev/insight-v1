# AZTECA V1 — Live & Radar Product Readiness (Stage 6)

## Current state (CONFIRMED NOT IMPLEMENTED for V1)
Both are bottom-nav tabs with screens (`features/live`, `features/radar`) and rich DTOs, but their data
chains are **gated OFF because the Gateway routes do not exist**:
- `live_v1` OFF → `/v1/live/*`, `/v1/context/*` absent (feature_gate.dart). LiveScreen → "Em breve".
- `radar_v1` OFF → `/v1/radar/*` absent. RadarScreen → "Em breve".
Services (`live_service`, `radar_service`) exist and are wired to those routes but are gated + mock-backed.

## DTOs already modeled (ready to render once data exists)
- Live (`models/live.dart`): `momentum`, `pressure`, `OddsPoint{home,draw,away}` timeline, `MatchSignal`,
  `TimelinePoint` (for sparklines).
- Radar (`models/radar.dart`): `magnitude` (0..1), `confidence`, `TrendingMatch`, `MarketMovement`,
  `CommunitySignalCard`.
- Match context (`models/match_context.dart`): `MatchProbabilities{home,draw,away}`, `MatchContextSignal`
  (directional, descriptive — explicitly "not betting odds"), leading-side hint.
These map to real Atlas/Explorer/Anvil intelligence outputs (probabilities, signals, momentum, similarity).

## Proposed V1 product boundary (derived from real platform capability)
Distinct products, not two versions of one page:
- **LIVE** = the *now* of a single match in progress: score/state/clock, major events, current momentum/
  pressure, current match-context probabilities + signals. Source: a live/context read surface fed by
  Atlas 1.0.0 outputs + match state. Requires `/v1/live/*` + `/v1/context/*` (absent today).
- **RADAR** = a *cross-match monitoring* surface: emerging signals, probability/market movement, trend/
  anomaly surfacing, prioritized opportunities across monitored matches. Source: Atlas trend/similarity +
  Explorer/Anvil aggregates. Requires `/v1/radar/*` (absent today).
LIVE is match-scoped and event-driven (realtime-friendly); RADAR is portfolio-scoped and periodic.

## Dependencies
- Backend: Live/Context/Radar Gateway routes over Atlas (frozen — read-only) + match state + Explorer/Anvil.
  These are BACKEND sprints; Azteca cannot make Live/Radar real alone.
- Realtime (Stage 9) strongly benefits LIVE (event/momentum push) but LIVE can ship with polling first.
- Intelligence UI taxonomy (Stage 7) is a shared prerequisite for rendering both.

## Verdict
Live & Radar are **NOT IMPLEMENTED** for V1 (backend-absent, correctly gated). They are the largest net-new
backend surface. Recommend **POST-V1** unless a backend Live/Context route lands; if it does, a single
AZTECA-LIVE-RADAR-A can render the already-modeled DTOs. Do not fake either with mock data for store release.
