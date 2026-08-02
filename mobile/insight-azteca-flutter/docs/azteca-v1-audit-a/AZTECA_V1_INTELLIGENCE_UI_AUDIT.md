# AZTECA V1 — Metrics / Probability / Intelligence UI Audit (Stage 7)

## Data actually available to Azteca (from DTOs)
Real fields already modeled (sources gated/partial today): probabilities (`MatchProbabilities{home,draw,away}`),
confidence (radar/insight `confidence`), magnitude/strength (radar `magnitude` 0..1), momentum & pressure
(live), odds timeline (`OddsPoint`), signals (directional `MatchContextSignal`, `MatchSignal`), trending/
movement (radar), timeline points (sparkline). Reputation/level/grouped stats (profile — REAL now).
Explicitly NOT betting odds — community/agent probabilities. Historical similarity/anomaly exist in Atlas
(backend) but are not yet surfaced as Azteca DTOs.

## Availability reality
- **Available NOW**: profile/social metrics (reputation, followers/following/posts/signals counts) — real.
- **Modeled, data gated**: match probabilities, momentum, confidence, odds/trend timelines (Live/Radar/Context
  routes absent). Rendering them today = fabrication → forbidden.

## V1 visualization taxonomy (only what real data supports)
Required primitives: metric card; delta card (±, with direction); directional arrow (up/down/flat);
confidence bar; probability bar (3-way home/draw/away); sparkline (odds/momentum timeline). Optional later:
line chart, distribution, radar chart, threshold band, comparison. Scatter — not needed for V1.

## Library recommendation
**Custom Flutter primitives for cards/bars/arrows/deltas; add `fl_chart` ONLY for the true time-series
(sparkline / odds line / momentum).** Rationale:
- No chart lib is currently in `pubspec.yaml`. Cards/bars/arrows are trivial `CustomPaint`/widgets — a chart
  lib for those is over-engineering and bloats the bundle.
- `fl_chart` (BSD-3, mature, no native deps) is justified for sparklines/line charts where hand-painting is
  error-prone. Use it narrowly; keep cards/bars custom.
- Bundle/perf: fl_chart is pure Dart, modest size, renders on the Skia canvas — acceptable. License: BSD-3 OK
  for store distribution.

## Accessibility requirements (mandatory)
- Never encode meaning by color alone — pair every delta/direction with an icon + text ("+3.2% ↑ subindo").
- Semantic labels on every metric (`Semantics(label: …)`), readable contrast (WCAG AA), dynamic-type safe
  (no fixed-height clipping), reduced-motion honored for any animated bar/sparkline.

## Verdict
Intelligence UI is DTO-ready but data-gated. AZTECA-INSIGHTS-A should (1) build the accessible primitive
kit (cards/bars/arrows/deltas + fl_chart sparkline), (2) render ONLY real fields (profile metrics now;
match intelligence once Live/Radar/Context backends exist). No fabricated statistics.
