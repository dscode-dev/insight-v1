# AZTECA V1 — Architecture Map (Stage 0)

Evidence-based; file:line references are authoritative. App = `insight-azteca-flutter` (Flutter 3.24, Dart 3.5).

## Stack
Riverpod (`flutter_riverpod`/`hooks_riverpod`), `go_router`, `dio`, `freezed`/`json_serializable`,
`flutter_secure_storage`, `image_picker`, `google_fonts`, `shimmer`, `intl`. **No chart library**
(no fl_chart), **no GIF/media package**, **no websocket package** (SSE is hand-rolled over dio/HttpClient).

## Entry & environment
- `lib/core/env.dart` — Gateway-ONLY. Single base URL `https://insight-api.konohalabs.com.br`
  (STAGING-INTEGRATION-B; no `/v1` prefix — services prepend). `API_MODE` default `gateway`.
- **Mock is demo-only**: `lib/core/api_mode.dart` — mock honored ONLY when `ENABLE_DEMO_MODE=true` AND
  non-production. Production never serves fixtures.
- **Feature gates** (`lib/core/env.dart` + `lib/core/feature_gate.dart`): only `social_v1` is ON by
  default. `live_v1`, `radar_v1`, `notifications_v1`, `post_uploads` are OFF by default because their
  Gateway routes DO NOT EXIST — a gated provider throws `FeatureUnavailable` WITHOUT a network call and
  the screen renders "Em breve." **This is the single most important readiness signal in the app.**

## API client (`lib/services/gateway_client.dart`)
Dio with 4 interceptors: `_AuthInterceptor` (Bearer), `_RefreshInterceptor` (one 401→`/v1/auth/refresh`
retry+replay, else clears session), `_RetryInterceptor` (idempotent **GET-only**, 3 attempts, backoff;
mutations never retried), `_ErrorMapper` (non-2xx → `GatewayException{status,detail}`). Tokens in
`TokenStorage` (secure storage). `GatewaySession` holds tokens for interceptors.

## Dependency chain (canonical social flow — VERIFIED wired)
```
HomeScreen → FeedNotifier(feed_provider) → SocialApi(social_service) → dio → /v1/feed/global
  → gateway foundation.GlobalFeed → social gRPC feed.Service.Global → PG posts/relationships
```
Auth: `auth_provider`/`auth_flow_provider` → `auth_service` → `/v1/auth/*` (phone+OTP). Router bridges
`authStatusProvider` to GoRouter `refreshListenable`.

## Services (19) & real endpoints
Real & wired: `social_service` (full social surface: feed/global,following · posts CRUD · comments ·
like/save/boost · follow/mute · sports-profile), `feed_service` (`/v1/feed` legacy flagged), `auth_service`,
`avatar_service` (`POST /v1/users/me/avatar`), `preferences_service` (`GET/PUT /v1/users/me/preferences`),
`reaction_service`, `moderation_service`, `competition_service`, `discussion_service`.
Gated/mock-backed: `live_service` (`/v1/live/*` gated), `radar_service` (`/v1/radar/*` gated),
`notifications_service` (`/v1/notifications*` gated; mock fixtures), `hub_service` (`/v1/hub/*`; mock
fixtures), `realtime_service` (`/v1/realtime/sse` hand-rolled; mock fallback).

## State/caches
Riverpod providers per domain (24 files). Optimistic patterns: `feed_provider.prepend` (post-success only),
`interaction_provider` snapshots (like/save/boost), `reaction_provider`. Avatar cache eviction in
`lib/core/avatar_cache.dart`. Composer draft persistence `lib/core/composer_draft_store.dart` (secure storage).
`startup_diagnostics.dart` asserts the cloud host. No analytics (`ENABLE_ANALYTICS=false`). No feature-flag
remote config (build-time defines only).

## Architectural verdict
Foundation is **professional and correct**: gateway-only, typed DTOs, real interceptors/refresh/retry,
honest feature-gating that prevents 404s in production. The gap is **breadth of wired backend**, not
client architecture quality. "Screen exists" ≠ "chain wired" — Live/Radar/Notifications/Hub/Realtime/Search
have screens but gated or mock chains.
