# CONSOLE-ARCHITECTURE-A — Stage 7: Target Control Plane Architecture

The target for Console V1 as the **Human Control Plane**. Validated against the real system
(two gateways, on-prem Console, cloud identity, direct Atlas/Explorer seam). Design only.

---

## 1. Non-negotiable boundary rule
The browser (and, where possible, the Console BFF) must **never**: SSH, run Docker/shell, touch
production DBs, hold infra credentials, or call privileged service endpoints without passing the
**Control-Plane Boundary**. Every privileged read/mutation is an **operator-identity-bound,
capability-checked, audited** call through the boundary.

## 2. Layered target

```
┌─────────────────────────────────────────────────────────────────┐
│  Console UI  (Next.js, server-first; capability-driven surfaces)  │
│  observes · understands · manages · intervenes · supports · audits│
└───────────────┬─────────────────────────────────────────────────┘
                │  same-origin /api only (HttpOnly session cookie)
┌───────────────▼─────────────────────────────────────────────────┐
│  Console BFF  (thin: session, correlation, capability pre-check,  │
│                response shaping — NO domain logic, NO topology)   │
└───────────────┬─────────────────────────────────────────────────┘
                │  operator-identity-bound calls (Bearer + control assertion)
┌───────────────▼─────────────────────────────────────────────────┐
│              CONTROL-PLANE BOUNDARY  (the gateway/s)              │
│  authn · capability authz · audit emit · operation service ·     │
│  platform registry · rate limit · dual-control · break-glass     │
└─┬───────┬───────┬───────┬───────┬───────┬───────┬───────┬────────┘
  ▼       ▼       ▼       ▼       ▼       ▼       ▼       ▼
Social  Identity Agent  Atlas  Explorer Anvil  Nexus  Platform-Ops
Admin   Admin    Admin  Admin   Admin   Admin  Admin  Adapter(s)
Adapter Adapter  Adapter Adapter Adapter Adapter Adapter (cloud+robozão)
```

**Validation against reality:** the generic adapter fan-out is correct *conceptually*, but the
real system has **two boundary implementations** — the **cloud gateway** (identity/social/
moderation/audit/platform-health) and the **robozão-gateway** (on-prem ops). The target keeps
**one logical boundary, two physical gateways**, federated by an **Environment Registry**. Atlas
and Explorer must be **pulled behind** a gateway adapter (ending the direct internal-token seam).

## 3. Component responsibilities

| Component | Owns | Notes |
|-----------|------|-------|
| **Console UI** | operator experience, capability-driven rendering | no derived "truth"; heuristics labelled |
| **Console BFF** | session cookie, correlation, response shaping, coarse capability pre-check | **stateless**; no JSON-file domains; no topology constants |
| **Control-Plane Boundary** | authn, capability authz, audit emission, operation orchestration, registries, rate limit | logical; realised by cloud + robozão gateways |
| **Service Admin Adapters** | typed admin contract per service | live *in the boundary/service*, not the Console |
| **Operation Service** | durable operation lifecycle, approvals, executor handoff | replaces the `/tmp` JSON domain (ADR-0004) |
| **Registries** | service / environment / capability discovery | replaces hardcoded `CLOUD_META`/`SERVICE_META` (ADR-0001/0002/0003) |
| **Audit spine** | canonical `insight.operational_event.v1` store | every mutation; tamper-evident |

## 4. Flows (target)

### Read
`UI → BFF (/api) → boundary (operator authz + capability check) → Service Admin Adapter →
service → response (+ correlation id + source attribution)`. No browser-derived platform truth;
services return their own state; the Console composes, never fabricates.

### Mutation
`UI (typed action) → BFF (capability pre-check) → boundary (authz + risk + dual-control gate +
confirmation token) → Operation Service (durable record, idempotency key) → Service Admin Adapter
→ service (operator-bound) → audit event → UI (operation status + correlation id)`.

### Event correlation
Every step shares one `correlation_id` (already propagated today via `x-request-id`). Operation
lifecycle + service events + audit all pivot on it → true who/what/why/where/result reconstruction.

## 5. Registries (replace hardcoded topology)
- **Service Registry** — id, kind, env, version, dependencies, capabilities, health endpoint.
  Sourced from services/gateways (OperationsService.Capabilities already exists for robozão).
- **Environment Registry** — `cloud` / `robozão`, gateway base URL, auth mode, reachability.
- **Capability Registry** — the `domain.resource.action` catalog + risk + approval + rollback +
  affected-services, seeded from IOC-CONTROL-A's action catalog and gateway `roles.go`.

## 6. Policies
- **Failure isolation:** per-adapter timeouts (already 5–10s), circuit breaker per service,
  per-surface error boundaries (not a shared `errors[]`). One failing domain never blanks the
  console.
- **Timeouts/breakers:** boundary-level, per environment (cloud vs on-prem latency differ).
- **Pagination:** mandatory cursor pagination on all list contracts (events/tickets/history/
  users/posts). No unbounded `limit`.
- **Caching:** short-TTL read cache at the boundary for health/registry; **never** cache
  mutations or audit.
- **Realtime:** SSE from the boundary for live surfaces (gateway already has `/v1/events/stream`
  and `/v1/realtime/sse`); Console consumes operator-scoped streams — no client polling loops for
  high-value surfaces.

## 7. What moves out of the Console
1. Operation domain logic + storage → **Operation Service** (ADR-0004).
2. Topology maps → **Registries** (ADR-0001/0002/0003).
3. Direct Atlas/Explorer internal-token calls → **gateway adapters** (ADR-0006).
4. Browser-derived readiness/coverage/insights → **service-reported** or explicitly-labelled
   heuristics (never platform truth).

**Target verdict:** achievable incrementally. The Console keeps its server-first Next.js shell and
its two real control surfaces (moderation, publication) as the pattern; the heavy lifting is
**backend adapters + registries + a durable Operation Service + identity binding**, all behind a
single logical control-plane boundary realised by the existing two gateways.
