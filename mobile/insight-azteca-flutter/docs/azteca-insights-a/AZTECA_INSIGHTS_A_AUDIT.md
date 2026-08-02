# AZTECA-INSIGHTS-A — Stage 0 Forensic Reality Audit

Evidence-based; the schema/routes are authoritative. Atlas inspected READ-ONLY, unmodified.

## A. What Azteca can consume TODAY (product-facing, real)
**Exactly one intelligence-bearing product contract**: `GET /v1/users/{id}/sports-profile`
(gateway `interactionsHandler.SportsProfile` → social `sports_profile.go`). Fields, all SQL-counted
server-side (backend-authoritative, never client-derived):
`followers`, `following`, `communities`, `posts`, `signals` (grouped `stats`), plus `reputation`,
`role`, `avatar_url`/`avatar_version`, identity fields.

## B/C/D. Internal-only (must NEVER reach Flutter)
- **Atlas (FROZEN 1.0.0)**: SimilarityContext/SimilarityService, TrendEngine internals, ReplayEngine/
  ReplayManifest, Quality Gate evaluations, detector classes (e.g. OracleSimilarityDetector), IOC events,
  pgvector/embedding memory. All platform-internal.
- **Explorer**: historical datasets/collectors — no product projection.
- **Magnus**: not present as a product-facing contract in this tree.

## E. Gateway product intelligence endpoints — **NONE EXIST**
`grep '"/v1/(live|radar|context|insights|intelligence|metrics)'` on `cmd/gateway/main.go` → **no matches**.
No match metrics, probabilities, trends, confidence, comparisons, odds evolution, momentum, reasoning or
intelligence summaries are exposed. Confirmed by `feature_gate.dart`: "`/v1/live/*`, `/v1/radar/*`,
`/v1/context/*` … DO NOT EXIST yet"; `live_v1` / `radar_v1` flags are OFF by default so no 404 ships.

## F. Flutter DTOs that exist but are unused/gated
`models/live.dart` (momentum, pressure, OddsPoint timeline, MatchSignal, TimelinePoint),
`models/radar.dart` (magnitude 0..1, confidence, TrendingMatch, MarketMovement, CommunitySignalCard),
`models/match_context.dart` (MatchProbabilities home/draw/away, directional MatchContextSignal).
All modeled, **all data-gated** (their routes don't exist). Services `live_service`/`radar_service` are
gated + mock-backed.

## G/H. Existing surfaces attempting to render intelligence
- **Profile ▸ Estatísticas** — the only real one. `IdentityStrip` rendered posts / sinais / **precisão** /
  reputação from `bundle.stats` (`UserStats`).
- **⚑ FABRICATION FOUND**: `UserStats.accuracy` ("precisão", rendered as `${accuracy*100}%`) exists ONLY in
  `/v1/profile/me/bundle` — a `strangler.NativeFlagged` **stub** ("Stubbed on the Gateway side until the Plaza
  reputation/stats + ClickHouse activity projections are wired in"). The REAL sports-profile contract has **no
  accuracy field**. ⇒ a fabricated metric was being shown to users. **Removed this sprint.**
- Live/Radar/Match-context screens render honest "Em breve" placeholders (gated).

## I. Chart dependency — **none**
`pubspec.yaml` has no `fl_chart` / `syncfusion_flutter_charts` / `charts_flutter`.

## J. Custom painters/chart widgets to reuse — **none** (`grep CustomPainter|CustomPaint lib/` → empty).
Design system DOES already provide purpose-built tokens: `confidenceHigh/confidenceMid/confidenceLow`,
`signal`, `signalMuted` — reused by the new primitives instead of inventing colours.

## K. Contracts sufficient for V1 integration
`sports-profile` scalars only.

## L. Contracts needing a Gateway projection (NOT built here)
Match probabilities/confidence/trends/comparisons/explanations — these depend on Live/Radar/context
producers that do not exist and are explicitly out of this sprint's scope.

## M. Boundary classification
| Data | Class |
|---|---|
| Profile scalars (followers/following/communities/posts/signals/reputation/role) | **REAL_AND_CONSUMABLE** |
| `UserStats.accuracy` ("precisão") | **NOT_IMPLEMENTED** (stub-backed fabrication → removed) |
| Atlas similarity/trend/replay/quality/IOC internals | **REAL_BUT_INTERNAL** (never to Flutter) |
| Explorer historical datasets | **REAL_BUT_INTERNAL** |
| Match probabilities / momentum / odds series / radar magnitude+confidence | **REAL_BUT_NOT_PROJECTED** → **BLOCKED_BY_CONTRACT** (no gateway route; producers absent) |
| Deltas/directions/ratios computed from two REAL values | **CLIENT_DERIVABLE_SAFE** (pure presentation of given values) |
| Trends/series | **BLOCKED_BY_CONTRACT** (no series contract ⇒ none rendered) |
| Live / Radar intelligence | **NOT_IMPLEMENTED** (deferred to LIVE-RADAR sprint) |

## Conclusion driving this sprint
Build the **presentation language** now (semantic model + accessible primitives), integrate the **only real
data** (Profile scalars), **delete the fabrication** (precisão), **defer charts** (no series to draw), and
**document the required product projection** for match intelligence instead of faking it.
