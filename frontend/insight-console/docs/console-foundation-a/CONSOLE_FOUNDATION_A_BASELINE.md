# CONSOLE-FOUNDATION-A — Stage 0: Baseline Revalidation

**Date:** 2026-07-03 · Inputs: all of `docs/console-architecture-a/` (12 docs + ADR-0001..0008),
used as mandatory design constraints. No conflicts with the audit were found; the codebase matches
CONSOLE-ARCHITECTURE-A (Console 0.3.18, three upstream seams, `/tmp` Operation domain, 1606-line
mega-component). This sprint implements the distributed foundation the audit prescribed.

## Implementation map (CURRENT → TARGET → METHOD → RISK)

| Area | CURRENT | TARGET | MIGRATION METHOD | RISK |
|------|---------|--------|------------------|------|
| Topology | Hardcoded `CLOUD_META`/`SERVICE_META` in `lib/operations-adapters.ts` | Server-owned **Service/Environment Registry** | Move metadata into registries; delete maps | Low (types preserved) |
| Trust boundary | `lib/cloud.ts` direct Atlas/Explorer with internal token + `X-Operator` | Typed **adapters** behind the BFF; tokens in server config only | New `lib/control-plane/adapters/*`; legacy `cloud.ts` untouched but deprecated | Med |
| Platform truth | 1606-line client component derives readiness/coverage | **PlatformSnapshotService** (server) | New service; migrate Infra data path | Med |
| Service integration | Ad-hoc fetches per route | **Base adapter** (timeout/cancel/normalized errors/attribution) | New `adapters/base.ts` | Low |
| Registries | None | Environment/Service/Capability registries + BFF routes | New `lib/control-plane/registries/*` + `app/api/v1/platform/*` | Low |
| Error semantics | Mixed; some silent fallback | **Canonical error model** (11 codes) | New `errors.ts` | Low |
| Operator identity | Client-asserted (`X-Operator`, `moderator_id`) | **Actor seam** forbidding client assertion (SECURITY-A0 ready) | New `actor.ts`; no behavior change | Low |

## Located integration points (revalidated)
- Service URLs/tokens: `ADMIN_API_BASE_URL`, `ATLAS_API_BASE_URL`+`ATLAS_INTERNAL_TOKEN`,
  `EXPLORER_API_BASE_URL`, `ROBOZAO_GATEWAY_URL`, `ADMIN_API_INTERNAL_TOKEN` (Nexus: no var → honest unconfigured).
- BFF routes: `app/api/**` (25 pre-existing). Atlas/Explorer clients: `lib/cloud.ts`. Gateway: `lib/admin-api.ts`. Robozão ops: `lib/robozao.ts`.
- Polling / derivation: `components/console/operational-command-center.tsx` (client, 10s poll ×8, readiness/coverage derived).
- Auth/session: `lib/session.ts`, `lib/api-guard.ts`. Internal-token handling: `lib/admin-api.ts`, `lib/cloud.ts`.
- Operation domain (out of scope, do-no-harm): `lib/operations-domain.ts` (`/tmp`) — untouched; the foundation does not make its future durable service harder (canonical event shape reused; actor seam prepared).

**Baseline verdict:** environment inspectable; no drift; foundation can proceed exactly as the ADRs specify.
