# insight-sports-hub

Go service that owns the **source-of-truth orchestration** for every
sports signal consumed by the Insight platform. Receives Raw events
from providers, normalises them, validates, detects conflicts,
computes confidence, and publishes Canonical events to downstream
consumers (Atlas ML, gateway, frontend).

**Sprint 1 ships the permanent foundation — no provider adapters,
no Redis publishing, no ML hooks.** Those land in Sprint 2.

## Architecture

Strict hexagonal:

```text
   ┌─────────────────────────────────────────────────────────┐
   │                       cmd/sportshub                     │   composition root
   └─────────────────────────────────────────────────────────┘
                                │
   ┌─────────────────────────────────────────────────────────┐
   │                  internal/application/                  │   use cases
   │  ingestion · normalization · validation · canonicaliz.  │
   │  conflict · confidence · publishing · source registry   │
   └─────────────────────────────────────────────────────────┘
            │                              │
   ┌────────────────┐            ┌──────────────────────┐
   │ internal/ports │ ◄── impl ──┤  internal/adapters/  │   I/O
   │  (interfaces)  │            │  postgres · http ·   │
   └────────────────┘            │  publishing · clock  │
            │                    └──────────────────────┘
   ┌────────────────┐
   │ internal/domain│   pure types + invariants
   │ source · event │
   │ sport · lineage│
   └────────────────┘
```

Dependency rule (enforced by `tests/application/boundary_test.go`):

| Layer | May import |
|---|---|
| `internal/domain/**` | other domain packages only |
| `internal/application/**` | domain, ports |
| `internal/ports` | domain |
| `internal/adapters/**` | anything below |
| `cmd/sportshub` | anything |

## Domain model

| Type | Purpose |
| --- | --- |
| `Source` | Registered provider (name, type, priority, enabled, confidence_weight) |
| `SourceType` | 8 categories mirrored byte-for-byte from `atlas.contracts.SourceType` |
| `SourceRef` | Per-event provenance — wire-compatible with Atlas `SourceRef` (Sprint 0.1.1 shape) |
| `RawSportsEvent` | One observation. Immutable. Never the platform truth |
| `CanonicalSportsEvent` | Merged consensus of N raws sharing one `Identity` |
| `Identity` | Natural key: `(sport, competition_id, match_id, event_type)` |
| `Status` | `candidate | confirmed | conflicting | rejected | stale` |
| `lineage.Link` / `lineage.Graph` | Raw → Canonical relationship rows |

## Application services

| Service | Responsibility |
| --- | --- |
| `SourceRegistryService` | CRUD over `Source` aggregates |
| `NormalizerService` | Provider-agnostic `NormalizedInput` → `RawSportsEvent` |
| `ValidationService` | Runs Sprint 1 quarantine rules pre-canonicalization |
| `ConflictDetectionService` | Pluggable Strategy; default `FieldEqualityStrategy` over authoritative raws |
| `ConfidenceService` | Pluggable Policy; default `WeightedAveragePolicy` (`Σ(weight × raw_conf) / Σ(weight)`) |
| `CanonicalizationService` | Merges N raws with the same `Identity` into one Canonical |
| `PublishingService` | Routes Canonical → Stream + idempotency key (Sprint 1 no-op Publisher) |
| `IngestionOrchestrator` | Wires every service into the canonical pipeline |

## Validation rules (Sprint 1)

| Reason slug | Where enforced |
| --- | --- |
| `missing_source` | `RawSportsEvent` constructor + `SourceRef.Validate` |
| `missing_timestamp` | `RawSportsEvent` + `SourceRef` |
| `unsupported_sport` | `sport.Parse` (V1: football only) |
| `unknown_competition` | `CompetitionRegistry` lookup |
| `empty_payload` | Raw + Canonical constructors |
| `duplicate_raw_event_id` | `RawEventRepository.ExistsByID` |
| `confidence_out_of_range` | Raw/Canonical constructors + SourceRef |
| `future_event_beyond_budget` | `ValidationService` (configurable via `VALIDATION_FUTURE_SKEW_SECONDS`) |

Additive only — Sprint 2+ appends new `QuarantineReason` constants
without renaming existing ones.

## Lineage preservation (architectural rule)

Every `RawSportsEvent` and every `CanonicalSportsEvent` carries the
**complete** `SourceRef`. The Hub never flattens, simplifies or
discards SourceRef fields. `tests/application/services_test.go`
includes `TestSourceRefSurvivesAllPipelineHops` which asserts every
field (incl. `adapter_version` + `metadata`) survives the
normalizer → canonicalization round-trip byte-for-byte.

Postgres preserves the full SourceRef in the `source` JSONB column on
`raw_sports_events` and the `sources` JSONB array on
`canonical_sports_events`.

## Publishing contracts (no transport yet)

| Stream | Routed for event types |
| --- | --- |
| `insight:stream:events:match` | `match.*` |
| `insight:stream:events:odds` | `odds.*` |
| `insight:stream:events:context` | everything else |

`internal/adapters/publishing/noop.go` discards (logs at debug).
Sprint 2 replaces with the Redis Streams adapter.

## Running locally

```bash
cp .env.example .env
make db-up        # apply goose migrations
make run          # boots on :8080
curl localhost:8080/healthz
curl localhost:8080/readyz
```

## Tests

```bash
go test ./...
```

Covers:

- domain invariants (Source / SourceRef / SourceType / Sport / RawEvent / CanonicalEvent / Identity / Status)
- application service contracts (normalizer, validation, conflict, confidence, canonicalization)
- lineage preservation round-trip
- architecture boundary enforcement (parsed import graph under `internal/`)

## Sprint 2 — provider adapters

The first real-world providers are connected via the `SourceAdapter`
port (`internal/ports/source_adapter.go`). Every adapter is a
**stateless translator** — never owns business rules, validation,
confidence calculation, conflict resolution, canonicalization, or
duplicate detection. Those stay in the Hub core.

| Adapter | Source | Endpoints used |
| --- | --- | --- |
| `internal/adapters/providers/api_football` | API-Football (api-sports.io) | `/v3/leagues`, `/v3/fixtures`, `/v3/standings` |
| `internal/adapters/providers/football_data` | football-data.org | `/v4/competitions`, `/v4/competitions/{code}/matches`, `/v4/competitions/{code}/standings` |

Each adapter package contains exactly 4 files: `client.go`
(HTTP), `dto.go` (private wire shapes), `mapper.go` (DTO →
`RawSportsEvent`), `adapter.go` (`ports.SourceAdapter` impl).

### Adapter architectural rules (enforced by tests)

- Adapters MAY import `internal/domain/**` and `internal/ports`.
- Adapters MUST NOT import `internal/application/**` — enforced by
  `tests/adapters/isolation_test.go`.
- Adapters MUST NOT import each other (same boundary test).
- Full `SourceRef` survives the adapter → orchestrator handoff —
  asserted by `tests/adapters/api_football_mapper_test.go` +
  `tests/adapters/football_data_mapper_test.go`.

### Provider-native ids never escape the adapter

Adapters resolve the Hub's canonical `competition_id` (uuid) →
provider-native id (`"71"`, `"PL"`) via
`CompetitionRegistry.GetExternalIDForSource`. The reverse direction
(`LookupByExternalID`) is used when ingesting an event whose
provider id is known. Both directions live behind the port — the
adapter never persists a mapping table of its own.

### CompetitionRegistry

Sprint 1's permissive in-memory registry was replaced with a
Postgres-backed adapter (`internal/adapters/postgres/competition_repo.go`).
Migration `migrations/00002_competition_registry.sql` seeds the V1
allow-list:

- Brasileirão Série A
- Premier League
- UEFA Champions League
- Copa Libertadores
- La Liga

The in-memory adapter stays for unit tests + lab boot without a DB.

### Source registration at startup

`main.go` calls `SourceRegistryService.Register` for every configured
provider. Source UUIDs are deterministic UUIDv5 over the
`SourceID` slug so re-deploys converge on the same canonical id.

### Provider operational status

`GET /v1/providers/status` returns per-provider operational state:

```json
{
  "providers": [
    {
      "source_id": "api_football",
      "reachable": true,
      "last_successful_sync": "2026-06-01T19:00:00Z",
      "average_latency_ms": 142,
      "requests_total": 12,
      "requests_failed_total": 0
    }
  ]
}
```

The tracker (`internal/adapters/observability/provider_status.go`)
is in-memory + thread-safe via RWMutex; populated by every adapter
call. Never logs API secrets.

## Sprint 2.1 — architectural hardening

Sprint 2.1 introduces no execution engine and no scheduler. It only
adds the contracts the Scheduler/Sync Engine (Sprint 3) will need,
plus one boundary restoration:

### Restored Normalizer seam

`IngestionOrchestrator.IngestRaw` now routes every adapter-built raw
through `NormalizerService.NormalizeRaw` (pass-through today). The
seam exists so future producers — internal bots, CrewAI agents,
LangGraph workflows, imported datasets — share one normalisation
boundary with the provider adapters.

### New contracts

- **`ProviderCapability`** in `internal/domain/source` —
  adapter-declared booleans: `SupportsFixtures`, `SupportsResults`,
  `SupportsStandings`, `SupportsOdds`, `SupportsLineups`,
  `SupportsNews`.
- **`SyncType` + `SyncJob`** in `internal/domain/sync` — future job
  unit: provider, competition, sync_type, priority, scheduled_at.
- **`RateLimitPolicy`** in `internal/domain/sync` — per-provider
  quotas (rpm / rph / daily / burst). Read by Scheduler only;
  adapters never reference it.
- **`PollPolicy`** in `internal/domain/sync` — per-(provider,
  sync_type) cadence with optional `LiveInterval` for accelerated
  live windows.

### Enriched `/v1/providers/status`

Each entry now includes `capabilities`, `rate_policy`, and
`poll_policies`. Profiles are registered once at boot via
`ProviderStatus.RegisterProfile`; live counters (`requests_total`,
`average_latency_ms`, …) remain populated by per-call recorders.

### Boundary still enforced

- `tests/application/boundary_test.go` continues to walk `internal/`
  and forbid `domain → application/adapters/ports`,
  `application → adapters`, `ports → adapters/application`.
- `tests/adapters/isolation_test.go` continues to forbid provider →
  application and provider → sibling-provider.
- New `internal/domain/sync` package depends only on `errors`, `fmt`,
  `time`, and `uuid` — boundary-clean.

## Sprint 3 — Scheduler / Sync Engine

Sprint 3 introduces the first execution engine of the platform.
Local-only (in-memory queue + worker pool); the contract is shaped
so Sprint 4 can swap the queue for Redis Streams without touching
any application code.

### Pipeline (Sprint 3 end-state)

```text
Scheduler.tick ─► Planner ─► []SyncJob ─► Dispatcher ─► ports.JobQueue
                                                          │
                                  workerLoop ◄────────────┘
                                       │
                                       ▼
                                RateLimiter.Allow
                                       │  allowed=true
                                       ▼
                                SourceAdapter.FetchFixtures/Standings
                                       │
                                       ▼
                                Ingester (orchestrator.IngestRaw)
                                       │
                                       ▼
                                Validation → Conflict → Confidence
                                       │
                                       ▼
                                Canonicalization → Persistence → noop Publisher
```

### Architectural decision split

| Question | Owner |
| --- | --- |
| **WHEN** to run | `internal/application/scheduler` |
| **IF** to run | `internal/application/ratelimit` |
| **HOW** to fetch | `internal/adapters/providers/{api_football,football_data}` |
| **WHAT** is true | the existing Hub core (validation → canonicalization) |

No layer crosses these lines. Boundary tests in
[tests/application/scheduler_boundary_test.go](insight-sports-hub/tests/application/scheduler_boundary_test.go)
parse the import graph and the provider source files to enforce them.

### Components

- **Planner** ([planner.go](insight-sports-hub/internal/application/scheduler/planner.go)) —
  loads enabled competitions, reads each registered adapter's
  capabilities, walks each provider's PollPolicy, and emits one
  `SyncJob` per `(provider, sync_type, competition)` lane whose
  `EffectiveInterval` has elapsed since the last emission. Disabled
  competitions and unsupported capabilities yield zero jobs.
- **Scheduler** ([scheduler.go](insight-sports-hub/internal/application/scheduler/scheduler.go)) —
  the tick loop. `time.Ticker`, no cron library. First tick fires
  immediately on boot. Graceful shutdown via context cancel.
- **Dispatcher** ([dispatcher.go](insight-sports-hub/internal/application/scheduler/dispatcher.go)) —
  thin shim that pushes the planner's output into the queue + emits
  `job_queued` / `job_dropped_queue_full` structured logs and
  status counters.
- **In-memory JobQueue** ([queue/inmemory.go](insight-sports-hub/internal/adapters/queue/inmemory.go))
  — bounded buffered channel; FIFO; non-blocking Enqueue;
  context-aware blocking Dequeue; idempotent Close that drains.
- **RateLimiter** ([ratelimit/limiter.go](insight-sports-hub/internal/application/ratelimit/limiter.go))
  — sliding-window counter per provider across four axes (burst,
  minute, hour, daily). Adapters NEVER read it.
- **JobRunner** ([jobrunner/runner.go](insight-sports-hub/internal/application/jobrunner/runner.go))
  — worker pool (configurable via `JOB_RUNNER_WORKERS`). Per job:
  `IncStarted → limiter.Allow → adapter.Fetch* → ingester`, with
  status counters at every transition. Graceful shutdown on ctx
  cancel OR queue close.

### Structured log events

Emitted at the relevant points:
`scheduler_started`, `scheduler_tick`, `scheduler_tick_completed`,
`scheduler_stopped`, `job_queued`, `job_dropped_queue_full`,
`jobrunner_started`, `job_started`, `provider_selected`,
`rate_limit_blocked`, `job_completed`, `job_failed`,
`jobrunner_stopped`. Every entry carries `provider`, `competition`,
`sync_type`, `job_id`, and (where relevant) `queue_size`, `latency`,
`execution_duration`. Never logs API keys.

### HTTP surface — Sprint 3 addition

```http
GET /v1/scheduler/status
```

Response keys: `scheduler_running`, `interval_seconds`,
`ticks_total`, `jobs_created_total`, `last_tick_at`, `queue_size`,
`active_workers`, `registered_providers`,
`enabled_competitions[]`, `disabled_competitions[]`.

`GET /v1/providers/status` is extended with per-source counters:
`queued_jobs`, `running_jobs`, `completed_jobs`, `failed_jobs`,
`queue_dropped_total`, `rate_limit_blocked_total`,
`last_execution`, `next_scheduled_execution`.

### Config knobs (Sprint 3)

| Env var | Default | Purpose |
| --- | --- | --- |
| `SCHEDULER_INTERVAL_SECONDS` | `30` | Tick cadence |
| `SCHEDULER_QUEUE_CAPACITY` | `1024` | Max queued jobs |
| `JOB_RUNNER_WORKERS` | `4` | Worker pool size |

## Sprint 4 — Distributed-ready queue transport

Sprint 4 swaps the queue transport without changing a single line of
application logic. The Scheduler, Planner, Runner, RateLimiter and
adapters are all transport-agnostic.

### Architectural goal

```text
                       (Sprint 3)                              (Sprint 4)
Scheduler ─► JobQueue ─► in-memory FIFO     Scheduler ─► JobQueue ─► Redis Streams
                              │                                            │
                              ▼                                            ▼
                          JobRunner ──────────────────────────────────► JobRunner
```

Same `ports.JobQueue` contract. The composition root picks the
backing impl via `QUEUE_BACKEND=inmemory|redis`.

### Delivery / Ack / Retry / Fail lifecycle

Sprint 4 promotes `Dequeue` from returning a bare `SyncJob` to a
`ports.Delivery{Job, Attempt, AckToken}`. The runner now owns the
message lifecycle:

| Outcome | Runner action | Effect |
| --- | --- | --- |
| Happy path | `queue.Ack(d)` | XACK the stream id |
| Rate-limit blocked | `queue.Retry(d, "rate_limit_*")` | bumped CurrentAttempt + ZADD retry |
| Fetch error | `queue.Retry(d, "fetch_failed")` | bumped CurrentAttempt + ZADD retry |
| Unknown provider | `queue.Fail(d, "unknown_provider")` | DLQ record + XACK |
| Attempts exhausted (inside Retry) | promoted to `Fail` | DLQ record + XACK |

Backoff: `BaseRetryDelay << (attempt-1)` — 5s, 10s, 20s, …
(`syncdom.NextRetryDelay`).

### Redis Streams adapter

[internal/adapters/queue/redis/](insight-sports-hub/internal/adapters/queue/redis/)
implements `ports.JobQueue` + `ports.StatsReporter` using:

| Concern | Mechanism |
| --- | --- |
| Producer | `XADD MAXLEN ~ N` (approximate trim — bounded capacity) |
| Consumer | `XREADGROUP` with one consumer group; one consumer per pod |
| ACK | `XACK` + best-effort `XDEL` |
| Retry timing | sorted set keyed by `RetryAfter.UnixNano()` + 1s promoter |
| Multi-worker dedup | Redis consumer-group semantics (no duplicate processing) |
| Stats | `XLEN` / `XPENDING` / `ZCARD` / `XINFO CONSUMERS` |

### Dead-letter contract (Sprint 4 — storage no-op)

`syncdom.SyncJobFailure` + `ports.DeadLetterStore` define the wire
shape. Sprint 4 ships [queue.NoopDLQ](insight-sports-hub/internal/adapters/queue/dlq_noop.go);
Sprint 5+ will land a Postgres-backed store + admin endpoints. Queue
adapters always route terminal failures through the port — the
storage swap is one constructor call.

### HTTP `/v1/scheduler/status` (extended)

New fields:
`redis_connected`, `stream_depth`, `active_consumers`,
`pending_messages`, `retry_queue_size`.

In-memory queue reports `redis_connected=true` + zero counters; the
admin UI renders a unified shape regardless of transport.

### Structured log events (Sprint 4)

`redis_connected`, `redis_disconnected`, `job_published`,
`job_received`, `job_acknowledged`, `job_retry_scheduled`,
`job_processing_failed`, `worker_started`, `worker_stopped`,
`queue_backend_initialised`. Every entry carries
`stream`/`consumer`/`provider`/`competition`/`sync_type`/`attempt`.
API secrets are never logged.

### Config knobs (Sprint 4)

| Env var | Default | Purpose |
| --- | --- | --- |
| `QUEUE_BACKEND` | `inmemory` | `inmemory` or `redis` |
| `REDIS_ADDR` | `localhost:6379` | Redis endpoint |
| `REDIS_PASSWORD` | `""` | Optional auth |
| `REDIS_DB` | `0` | Logical DB |
| `REDIS_STREAM` | `insight:queue:syncjobs` | Stream key |
| `REDIS_GROUP` | `insight-syncjob-workers` | Consumer group |
| `REDIS_CONSUMER` | `<hostname>-<pid>` | Per-pod consumer name |
| `REDIS_RETRY_ZSET` | `insight:queue:syncjobs:retry` | Retry sorted set |
| `REDIS_MAX_LEN` | `10000` | XADD MAXLEN approx cap |

### Sprint 4 boundary tests

[tests/application/scheduler_boundary_test.go](insight-sports-hub/tests/application/scheduler_boundary_test.go)
walks `internal/` source files and fails if anything outside
`internal/adapters/queue/redis/` imports `github.com/redis/go-redis`.
Plus the existing rules (scheduler/jobrunner/ratelimit ↛ concrete
adapters) extend to forbid Redis imports too.

## Sprint 5 — V1 integration

Sprint 5 connects the Sports Data Hub to the rest of the V1 stack
(Atlas ML + Atrium BFF + azteca-flutter) without changing any
business logic. The Hub now:

### Failure classification

[internal/domain/sync/failure_type.go](insight-sports-hub/internal/domain/sync/failure_type.go)
introduces `FailureType` with five bands and the verbatim Sprint 5
matrix:

| Reason slug | FailureType | Retryable |
| --- | --- | --- |
| `provider_timeout` | `provider` | yes |
| `provider_error` | `provider` | yes |
| `rate_limit` | `transient` | yes |
| `redis_unavailable` | `infrastructure` | yes |
| `database_error` | `infrastructure` | yes |
| `malformed_payload` | `validation` | **no** |
| `unknown_provider` | `permanent` | **no** |
| `competition_disabled` | `permanent` | **no** |
| `unsupported_sync_type` | `permanent` | **no** |
| `attempts_exhausted` | `permanent` | **no** |

The queue's new `Settle(d, reason)` method classifies + routes to
Retry or Fail. The runner emits canonical reason slugs; no string
heuristics left.

### Real canonical-event publisher

[internal/adapters/publishing/redis_publisher.go](insight-sports-hub/internal/adapters/publishing/redis_publisher.go)
replaces the Sprint 1 no-op. Picked at boot via `PUBLISHER_BACKEND`
(`noop` default, `redis` production). Wire envelope:

```json
{
  "schema_version": "v1",
  "stream": "match",
  "idempotency_key": "<canonical_event_id>::<status>",
  "event": { ...CanonicalSportsEvent... },
  "published_at": "2026-06-06T17:00:00Z"
}
```

Routes:

- `insight:stream:events:match`   — `event_type` starts with `match.`
- `insight:stream:events:odds`    — `event_type` starts with `odds.`
- `insight:stream:events:context` — everything else

Atlas consumes the match + context streams; Anvil (Sprint 6) will
consume odds.

### V1 docker-compose

[docker-compose.v1.yml](App/docker-compose.v1.yml) at the workspace
root spins up the full V1 stack: postgres, redis, sports-hub, atlas,
atrium. Run:

```bash
docker compose -f docker-compose.v1.yml up -d
curl localhost:8080/v1/scheduler/status
curl localhost:8081/live
curl localhost:8082/ready
```

## Known Sprint 2 limitations (deferred to Sprint 3+)

| Item | Why deferred |
| --- | --- |
| Periodic poll scheduler | Sprint 2 builds adapters but doesn't schedule them — `orchestrator.IngestRaw` is called manually or via tests today |
| Redis Streams publisher | Still no-op (`internal/adapters/publishing/noop.go`) — spec keeps it out of Sprint 2 |
| Match catalogue (`external_match_id` → real `match_id`) | UUIDv5 derivation still in use; cross-provider match unification is Sprint 3+ |
| Team registry (separate from competition) | Adapters carry team external_ids inside the payload only |
| Internal bots, CrewAI, LangGraph | Out of scope per Sprint 2 spec |
| Source admin HTTP routes (enable/disable, edit weight) | Service ready; routes pending |
| Prometheus metrics adapter | Still no-op |
| Postgres CompetitionRegistry integration tests against a real DB | Tests run against the in-memory adapter today; both share the port contract |
