# insight-gateway

The edge HTTP/SSE gateway for the Insight platform — the single
public entry point. Runs STANDALONE by default (consolidated
platform): every route is served by native Go handlers and unmatched
paths return 404. The original Strangler proxy machinery survives
behind `LEGACY_UPSTREAM_BASE_URL` for overlap deployments only.

## Status

Phase 4 / Sprint 2 closed. The gateway ships with:

* **W1.0** — repo bootstrap + Strangler proxy + goose migrations.
* **W1.2** — 4 OTP-auth native handlers (`/v1/auth/otp/request`,
  `/v1/auth/otp/verify`, `/v1/auth/register`, `/v1/auth/refresh`)
  behind per-endpoint rollout flags. User creation goes through the
  social.v1.UserService gRPC client
  (`internal/infrastructure/socialclient/usercreator.go`).
* **W1.3** — native SSE realtime at `/v1/realtime/sse`. RealtimeBroker
  tails 8 Redis derived-stream partitions, fans out to subscribers via
  per-connection channels with non-blocking sends + drop-on-full
  metrics. JWT access_token in query string (EventSource constraint).

In standalone mode the rollout flags are inert — native handlers
serve 100% of traffic. With a legacy upstream configured, flipping a
flag to `shadow` / `10` / `100` is the per-endpoint cutover lever.

**W1.4 (BFF endpoints — `/v1/feed`, `/v1/live/matches/*`,
`/v1/radar/bundle`, `/v1/hub/bundle`, `/v1/profile/me/bundle`,
`/v1/notifications`)** is deferred to Sprint 3+ because they depend on
W2 (Social Domain) and W4 (Sports Data Hub) being available via gRPC.
Until then those endpoints 404 in standalone mode (no legacy proxy); the
Strangler.

## Architecture

Hexagonal layout. The public surface is just `cmd/gateway/main.go`;
everything else is internal.

```text
cmd/gateway/main.go              boot + wiring
internal/
├── config/                      env-driven typed Settings
├── domain/auth/                 Credential + OtpChallenge + ports + errors
├── application/auth/            4 OTP use cases (Service)
├── infrastructure/
│   ├── postgres/                pgx pool factory + credential/otp repos
│   ├── redis/                   cooldown store (per-phone resend window)
│   ├── jwt/                     access/refresh/registration token codec
│   ├── otp/                     code gen + HMAC hash
│   ├── phone/                   E.164 normalization
│   ├── sms/                     Null/Zenvia/Twilio providers
├── realtime/                    Broker + filters (SSE fan-out core)
└── interfaces/
    ├── proxy/                   Strangler chi router + flag rollout
    └── http/
        ├── auth/                4 handlers + DTOs + error mapping
        └── realtime/            SSE handler with keepalive
migrations/                      goose SQL (ported from alembic)
tools/seed_goose_marker.sh       one-shot cutover script
k8s/
├── base/                        canonical manifests
└── overlays/
    ├── local-lab/               kind cluster
    └── production/              prod overlay + migrations Job
```

The Strangler core (`internal/interfaces/proxy/strangler.go`) is a
chi router; `NotFound` is 404 standalone, proxy fallback in overlap mode.
W1.2+ register native handlers via `Strangler.Native(method, path, h)`.
Anything unregistered keeps proxying — zero risk of dropping traffic
during the cutover.

## Routing model

```text
                  ┌──────────────────────────────────────┐
   request ─────▶│ Strangler (chi + per-route flags)    │
                  │  ├─ /v1/auth/otp/request   GO+flag   │  W1.2 ✅
                  │  ├─ /v1/auth/otp/verify    GO+flag   │  W1.2 ✅
                  │  ├─ /v1/auth/register      GO+flag   │  W1.2 ✅
                  │  ├─ /v1/auth/refresh       GO+flag   │  W1.2 ✅
                  │  ├─ /v1/realtime/sse       GO+flag   │  W1.3 ✅
                  │  ├─ /v1/feed               PROXY     │  W1.4 (waits W2)
                  │  ├─ /v1/live/matches/*     PROXY     │  W1.4 (waits W4)
                  │  ├─ /v1/hub/bundle         PROXY     │  W1.4 (waits W2)
                  │  ├─ /healthz               GO        │  W1.0 ✅
                  │  ├─ /readyz                GO        │  W1.0 ✅
                  │  ├─ /metrics               GO        │  W1.0 ✅
                  │  └─ NotFound ─ 404 (or legacy proxy) │
                  └──────────────────────────────────────┘
```

Per-flagged-route decision (each request):

| Flag value                   | Behaviour                                                          |
|------------------------------|--------------------------------------------------------------------|
| `""` / `off` / `false` / `0` | Proxy to the legacy upstream (standalone: serve natively).         |
| `shadow`                     | Proxy upstream AND call Go in a goroutine (response discarded).    |
| `1`..`100`                   | Random N% of requests served by Go; remainder proxy.               |

## Local dev

Requires Go 1.23 and Postgres + Redis running. No legacy upstream
needed — leave `LEGACY_UPSTREAM_BASE_URL` unset.

```bash
make build         # build to ./bin/gateway
make test          # go test -race
make lint          # golangci-lint
make run           # run against the lab cluster's downstream (needs env)
make db-status     # goose status
make db-up         # apply goose migrations
make docker-build  # multi-stage distroless image
```

Use the `.env.example` file as a starting point:

```bash
cp .env.example .env.local
# edit DATABASE_URL, REDIS_URL, JWT_SIGNING_KEY
make run
```

## Migrations cutover (one-time)

When this gateway first comes online against an `insight_auth`
database the legacy BFF's alembic was managing, seed goose so it
doesn't try to re-apply the two existing migrations:

```bash
DATABASE_URL=... bash tools/seed_goose_marker.sh
```

Idempotent — re-running is a no-op. After that, normal goose flow:

```bash
goose -dir migrations postgres "$DATABASE_URL" up
```

## Deploy

```bash
# Lab (kind)
make docker-build IMAGE_TAG=dev
kind load docker-image konohalabs/insight-gateway:dev --name insight-lab
kubectl apply -k k8s/overlays/local-lab

# Production
kubectl apply -k k8s/overlays/production
```

The legacy Ingress simply switches its
`backend.service.name` to `insight-gateway` — Strangler takes care of
the rest. Roll back by switching the Ingress back, no schema or data
state needs reverting.

## Observability

* Logs: structured JSON to stdout (zerolog).
* Metrics: Prometheus `/metrics`. Scraped by the cluster Prometheus
  via the annotation on the Service.
* Tracing: OTLP gRPC to the collector at
  `otel-collector.observability.svc.cluster.local:4317`.
* Health: `/healthz` (liveness — always 200 unless deeply broken),
  `/readyz` (checks Postgres + Redis; legacy upstream only when configured).

## Risk notes for W1.0 → W1.x

* **JWT signing key continuity**: shared with the legacy BFF via the
  `insight/shared:jwt_signing_key` Vault path. Do NOT rotate during
  migration windows.
* **Postgres dual-reader (historical)**: gateway-go and the legacy BFF both read/write
  `insight_auth`. Schema is frozen during the Strangler — no new
  migrations; the legacy BFF is now retired.
* **Rate limit Redis namespace**: gateway preserves the
  `insight:atrium:rl:*` prefix (kept for data continuity) so old and new don't
  double-count limits.
* **SSE keepalive**: 15s `: keepalive\n\n` is essential — the
  reverse proxy preserves the upstream's flush behaviour via
  `ModifyResponse` setting `X-Accel-Buffering: no`.
