# insight-social

Go service that owns the Social domain of Insight — the 7 aggregates
that used to live in `plaza-py`: **User, Community, Discussion,
Signal, Sentiment, Relationship, Reputation**.

Part of Phase 4 / W2 of the Python→Go migration. Communicates with
the rest of the platform exclusively over **gRPC** (`social.v1`,
defined in [insight-protos](../insight-protos)).

## Status — W2.0 (boot)

The service boots, registers all 7 services as `Unimplemented` stubs,
exposes `/healthz` / `/readyz` / `/metrics` on its HTTP listener, and
owns its own `insight_social` schema via goose migrations ported from
plaza-py's alembic baseline.

What's **not** here yet: every aggregate's real implementation. Those
land in W2.1, one aggregate per PR, swapping the corresponding stub
for the real `Register*ServiceServer` call.

| Sprint | Scope                                                                  |
|--------|------------------------------------------------------------------------|
| W2.0   | Repo bootstrap, gRPC server boots with 7 stubs, migrations cut over    |
| W2.1a  | User + Community + Discussion implementations                          |
| W2.1b  | Signal + Sentiment + Relationship + Reputation implementations         |
| W2.2   | Strangler flip endpoint-by-endpoint at insight-gateway                 |

## Architecture

```text
   ┌──────────────────────┐         gRPC (mTLS)        ┌─────────────────┐
   │   insight-gateway    │ ─────────────────────────► │  insight-social │
   │   (Strangler flag)   │                            │   (this repo)   │
   └──────────────────────┘                            └────────┬────────┘
              │ (off|shadow|percent)                            │
              ▼                                                 ▼
   ┌──────────────────────┐                            ┌─────────────────┐
   │     plaza-py         │ ───── same Postgres ─────► │  insight_social │
   │  (legacy, frozen)    │                            │   (logical DB)  │
   └──────────────────────┘                            └─────────────────┘
```

Layers (hex/onion):

```text
cmd/social/main.go          ← composition root (boots everything)
internal/
  config/                   ← env → typed Settings
  domain/                   ← aggregates (W2.1)
  application/              ← use-cases (W2.1)
  infrastructure/
    postgres/               ← pgx pool + repo impls (W2.1)
    redis/                  ← HumanSignal publisher (W2.1)
  interfaces/
    grpc/                   ← Register*ServiceServer impls (W2.0 stubs)
```

## Running locally

```bash
cp .env.example .env
# bring up postgres + redis (docker compose at repo root, or your own)
make db-up      # apply goose migrations
make run        # boots gRPC :50051 + HTTP :8080
```

Smoke-test the gRPC surface with `grpcurl`:

```bash
grpcurl -plaintext localhost:50051 list
# social.v1.UserService
# social.v1.CommunityService
# ...

grpcurl -plaintext localhost:50051 social.v1.UserService/GetUser
# ERROR: Code: Unimplemented (expected during W2.0)
```

## Migrations

Plaza-py owned the schema before this service existed. The cutover
script seeds a goose marker so goose recognises the existing schema
as "version 1 applied", then drops alembic's bookkeeping table:

```bash
DATABASE_URL=postgres://... ./tools/seed_goose_marker.sh
```

After cutover, **plaza-py is frozen** — no new alembic revisions. All
schema changes go through `make db-up` against this repo's
[migrations/](migrations/) directory.

## Deployment

- **local-lab**: `kubectl kustomize k8s/overlays/local-lab` — single
  replica, plaintext gRPC, in-process migrations on boot.
- **production**: `kubectl kustomize k8s/overlays/production` —
  3 replicas + topology spread, mTLS via cert-manager, migrations
  via Argo PreSync Job, NetworkPolicy locked to insight-gateway.

CI delegates to the reusable workflow in
[insight-runtime-go](../insight-runtime-go) so every Insight Go
service shares the same lint/test/build/push gates.

## Things that DON'T live here

- **HumanSignal runtime** — absorbed by Atlas (`insight-atlas`)
  per Phase 2 decision. This service publishes to its Redis Streams;
  it doesn't process them.
- **Cards / models / scoring** — absorbed by Atlas (`insight-atlas`).
- **Auth / OTP / JWT** — owned by [insight-gateway](../insight-gateway).
- **Sports Hub data** — separate service, [insight-sports](../insight-sports) (W4).
