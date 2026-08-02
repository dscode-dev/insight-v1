# CONSOLE-ARCHITECTURE-A — Stage 2: Data Flow Audit

Traces the real path **UI → hook/provider → adapter → BFF → service/API → storage/event
source** for each important surface, and flags derived state, hardcoded topology, and failure
handling. All server-side upstream calls are `cache: "no-store"`.

---

## 1. The three upstream seams (CONFIRMED)

| Seam | File | Target | Auth | Used by |
|------|------|--------|------|---------|
| **Gateway admin** | `lib/admin-api.ts` | `ADMIN_API_BASE_URL` = cloud gateway `/v1` | `X-Console-Service-Token` (service) **+** `Authorization: Bearer <operator>` | auth, moderation, platform-health, console admin, audit |
| **Direct service** | `lib/cloud.ts` (`atlasIntelligenceCall`, `explorerCall`) | Atlas `:8085` / Explorer `:8090` | `X-Internal-Token` (Atlas) / `X-Operator` string (Explorer) | atlas/explorer intelligence + datasets |
| **Robozão ops** | `lib/robozao.ts` | `ROBOZAO_GATEWAY_URL` `:8095` | `Authorization: Bearer <operator>` | operations status/events/tickets/runs/datasets/history, vpn/status |

**DF-1 — Split boundary.** The Console BFF has **two mutually-inconsistent trust models**:
gateway-mediated (operator token forwarded, service verifies) *and* direct-to-service (Console
holds an `X-Internal-Token` and asserts the operator as a plain `X-Operator` string). The latter
means the Console is a **privileged internal client of Atlas/Explorer**, and operator identity is
a self-asserted header, not a verified session. This is the single biggest boundary problem for
becoming a control plane.

---

## 2. Surface-by-surface flows

### 2.1 Operations Center (`OperationalCommandCenter`) — the mega-flow
```
Browser (client component, 10s poll ×8)
  → GET /api/operations/status ──────────────┐
  → GET /api/v1/data-intelligence/**/dashboard│  Console BFF route handlers
  → GET /api/v1/data-intelligence/executions  │  (app/api/**)
  → GET /api/v1/data-intelligence/atlas/ingestion
  → GET /api/v1/ops/events|tickets|history    │
  → GET /api/v1/dlq                            ┘
      → lib/operations-adapters.operationsSnapshot()
          → adminFetch "/v1/console/platform/health"  → cloud gateway → real PG/Redis/CH/social/anvil probes
          → robozaoOperationsStatus() "/operations/status" → robozao-gateway → OperationsService.Status (gRPC fan-out)
      → lib/cloud.atlasIntelligenceCall / explorerCall → Atlas/Explorer direct
      → lib/robozao.robozaoOps(events|tickets|history) → robozao-gateway
```
- **Real:** platform-health rows (gateway does the true checks), robozão service metrics, atlas
  ingestion, explorer executions, DLQ, ops events/tickets/history.
- **Derived in the browser (DF-2):** readiness scores, "insights", coverage %, health-score
  sorting, timeline synthesis, mission replay index. None of these come from a service.
- **Hardcoded (DF-3):** `CLOUD_META` + `SERVICE_META` in `operations-adapters.ts` bake
  service→host/region/dependencies/capabilities/"state" (e.g. atlas `state:"waiting batch"`).
  Topology is a **frontend constant**, not a registry.
- **Resilience (DF-4):** no pagination (events/tickets/history capped by `limit` query only),
  `setInterval` never backs off, no per-tab error isolation (a single failed fetch pushes into a
  shared `errors[]` array). Honest fallbacks exist for cloud (`cloudPending`, never a fake
  "down") — good — but robozão failure collapses to a single "unavailable" gateway row.

### 2.2 Moderation Center — the exemplary real flow
```
Browser → POST /api/v1/moderation/actions
  → requireOperator()/requirePermission (ACTION_PERMISSION[action])   [BFF re-validates]
  → lib/moderation.postAction() → adminFetch POST "/v1/admin/moderation/actions"
      → cloud gateway (consolemw: X-Console-Service-Token) → moderation handler → social/PG
```
- **Real, mutating, audited.** Zod-validated read schemas; permission map enforced BFF-side.
- **DF-5 (attribution gap):** the POST body carries a client-supplied `moderator_id`; the
  moderation handler is gated by the **shared service token**, so the operator identity bound to
  the action is asserted by the Console, not re-derived from a verified session at the mutation
  point. (See Security audit.)

### 2.3 Administration (Users / Operators / Sessions)
```
Browser → GET /api/v1/admin/{users|operators|sessions}
  → requireOperator() → adminFetch → gateway /v1/console/admin/* (GET only)
      → gateway console.Handlers.requireOperator() [real DB session+role check] → PG
```
- **Real reads, no writes.** Gateway validates the operator session server-side (SHA-256
  token_hash → `operator_sessions ⋈ operators`). No mutation route exists on the gateway side.

### 2.4 Audit Center
```
Browser → GET /api/v1/audit → adminFetch → gateway /v1/console/audit → PG (AuditService.Query)
```
- **Real, read-only.** This is the platform audit spine. It records gateway-side admin reads and
  moderation, but **not** Console Operation-domain lifecycle events (those live in the JSON file).

### 2.5 Control Panel / Operation domain
```
Browser → GET/POST /api/v1/control/operations
  → lib/operations-domain.{list,create,dryRun,approve,cancel}Operation()
      → read/write JSON file at CONSOLE_OPERATIONS_STORE (default /tmp/insight-console-operations.json)
```
- **No service, no durability.** `execution_enabled:false`. Emits `insight.operational_event.v1`
  objects **into the file record only** — they never reach a real event bus. (See Control Audit.)

### 2.6 Publication Center (Nexus)
```
Browser → Console /api → Nexus authed HTTP API → Nexus PG (audited mutations, tier RBAC)
```
- **Real, mutating, audited, tier-gated.** Alongside Moderation, the healthiest control flow.

---

## 3. Cross-cutting findings

| # | Finding | Severity |
|---|---------|----------|
| DF-1 | Two inconsistent trust models (gateway-mediated vs direct-with-internal-token) | **High** |
| DF-2 | Platform "intelligence" (readiness/coverage/insights) is browser-derived, not service truth | **High** |
| DF-3 | Topology hardcoded in `operations-adapters.ts` (CLOUD_META/SERVICE_META) | **High** |
| DF-4 | 10s polling, no backoff, no pagination, shared error array, weak per-tab isolation | Med |
| DF-5 | Moderation attribution is client-supplied `moderator_id` under a shared token | **High** |
| DF-6 | Operation-domain events never reach the real IOC bus / audit spine | **High** |
| DF-7 | `X-Operator` to Explorer is an unauthenticated identity string | **High** |
| DF-8 | Correlation id (`x-request-id`) is propagated end-to-end (good) | ✅ Strength |
| DF-9 | Honest empty/pending states for cloud (`cloudPending`, never fake down) (good) | ✅ Strength |
| DF-10 | Zod schema validation on gateway JSON (good) | ✅ Strength |

**DF verdict:** The read paths are largely real and correlation-traceable, with two genuine
mutation paths (moderation, publication). The **control-plane blockers** are the split trust
boundary, the direct-service internal-token pattern, browser-derived "truth", and hardcoded
topology. These must be resolved before any new domain mutations are added.
