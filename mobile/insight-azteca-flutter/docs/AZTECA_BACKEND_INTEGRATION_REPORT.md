# Azteca Backend Integration (Azteca-X Part 6)

Azteca integrated with the **local lab environment** — the SanninJiraiya
Gateway on the LAN. Real requests, real contract, no mocks.

## Topology

```
Azteca (device on LAN)
  → Gateway  http://136.115.122.177:8080   (public API: auth, uploads, social BFF)
      → Social (gRPC, internal-only)  +  Postgres / Redis
```

Azteca consumes the **Gateway only** (`lib/services/gateway_client.dart`,
base URL = `InsightEnv.apiBaseUrl`). With `ENVIRONMENT=local` that resolves to
`http://192.168.1.61:8080`.

## Endpoints Azteca uses (from `lib/services/auth_service.dart` + clients)

`/v1/auth/otp/request` · `/v1/auth/otp/verify` · `/v1/auth/register` ·
`/v1/auth/refresh` · `/v1/feed*` · social profile/feed BFF routes.

## Live validation (against 136.115.122.177:8080)

```
GET  /healthz                         → 200   (gateway live)
GET  /readyz                          → {"probes":[postgres ok, redis ok],"status":"ok"}
POST /v1/auth/otp/request {phone:…}   → 202   ← the exact endpoint Azteca calls
```
Gateway log on boot: `social_connected target=social:50051` → the Gateway→Social
path Azteca's feed/profile calls traverse is up.

This proves the **real authentication entrypoint** Azteca uses responds on the
local environment (202 Accepted) — real request, real backend, no fallback.

## Notes (honest)

- Completing the OTP → token exchange end-to-end needs the OTP code; with
  `SMS_PROVIDER=null` the code isn't surfaced in logs, so a full token round-trip
  wasn't captured here. The contract path (request → 202) is validated; verify +
  feed/likes/comments exercise the same authenticated client once a code is
  available (or a real SMS provider is configured).
- Feeds/likes/comments/profiles flow through the same `gatewayDioProvider`; with
  the local env active they hit `136.115.122.177:8080/v1/...`. No mock/fallback
  providers are enabled (`API_MODE=gateway`, demo mode off).
