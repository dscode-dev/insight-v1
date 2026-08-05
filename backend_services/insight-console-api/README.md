# insight-console-api

Console backend (NestJS 11 + Fastify). Started as the **strangler seam**
for `insight-console`: it owns what the Next.js BFF handles poorly, and
new console domains land here rather than in `app/api/**/route.ts`.

## Why this service exists

The Next.js console is `output: "standalone"` — a real Node server, not
serverless — so it *can* hold SSE connections. This service is not about
a capability Next lacks. It is about two concrete costs the audit found:

1. **Session resolution.** Every authenticated BFF request costs one
   `GET /v1/operator/auth/me` round-trip to the Gateway. With 14
   client-side polling points (worst: 8 requests / 10s / tab) that is a
   lot of repeated identity resolution. `SessionCacheService` collapses
   it behind a short TTL in a long-lived process.
2. **Polling fan-out.** Browser polling multiplies upstream load by the
   number of open tabs. A `Channel` polls upstream *once* per interval
   and fans out to every subscriber, and stops entirely when the last
   one disconnects.

## Identity — the security contract

This service **never mints identity**; the Gateway remains its sole
owner. The Next BFF resolves the operator, then passes it here as an
HMAC-signed envelope (`src/identity/operator-identity.ts`).

Without the signature this service would break the console's core rule —
that operator identity is server-derived and never caller-asserted
(`assertNoClientActor`) — because anything able to reach this port could
claim to be any operator. Envelopes carry `issuedAt` and expire after 60s
to bound replay.

`IdentityGuard` is registered globally (`APP_GUARD`), so routes are
fail-closed by default. `@Public()` opts out and is used by exactly two
places: `/health` (the container probe) and `/internal/session/*` (which
is what the BFF calls in order to *learn* the identity — it authenticates
with the session token itself, verified against the Gateway).

## Development

Node is not installed on the primary dev machine; run everything through
Docker:

```bash
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "/c/Users/<you>/Documents/Projetos/insight-v1/backend_services/insight-console-api:/app" \
  -w /app node:22-alpine \
  sh -c "npm install && npm run typecheck && npm run test"
```

`MSYS_NO_PATHCONV=1` is required under Git Bash, which otherwise rewrites
`/app` into a Windows path and breaks `-w`.

## Configuration

All validated at boot (`src/config/config.ts`); the process refuses to
start on invalid config rather than failing per-request.

| Variable | Required | Notes |
|---|---|---|
| `CONSOLE_API_SIGNING_SECRET` | yes | min 32 chars — shared with the Next BFF |
| `ROBOZAO_GATEWAY_URL` | yes | identity owner |
| `SESSION_CACHE_TTL_SECONDS` | no (30) | bounds how stale a revocation can be |
| `REALTIME_POLL_INTERVAL_MS` | no (5000) | one poll per channel, not per subscriber |
| `EXPLORER_API_BASE_URL` / `EXPLORER_OPS_TOKEN` | no | needed by the explorer channels |
| `ATLAS_API_BASE_URL` / `ATLAS_INTERNAL_TOKEN` | no | needed by the Quality Gate module |
