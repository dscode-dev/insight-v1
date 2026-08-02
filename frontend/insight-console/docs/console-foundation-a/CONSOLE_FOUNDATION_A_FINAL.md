# CONSOLE-FOUNDATION-A — Final Report

**Date:** 2026-07-03 · **Classification: `READY`**

## 1. Final classification — READY
Registries are real and server-owned; typed adapters are real and consumed; the Platform Snapshot
is real and drives a migrated UI surface; dual-environment topology is validated live; security
boundaries are preserved (no arbitrary proxy, no secret serialization, no browser infra access);
and the SECURITY-A0 seam exists. The distributed Control Plane foundation is established and in use
by a real vertical slice — not decorative.

## 2. Architecture implemented
`Browser → Console BFF (/api/v1/platform/*) → PlatformSnapshotService → Environment/Service/
Capability Registries + typed adapters (atlas/explorer/gateway/robozao/nexus) → real upstreams`,
with a canonical error model, per-source attribution, honest partial state, control-plane
observability, and an actor seam. Topology + secrets are server-owned; the browser holds only its
session cookie.

## 3. Files created (~33)
- Core: `lib/control-plane/{config,types,errors,observability,actor,index}.ts`
- Registries: `lib/control-plane/registries/{environments,services,capabilities}.ts`
- Adapters: `lib/control-plane/adapters/{base,atlas,explorer,nexus,gateway,robozao}.ts`
- Routes: `app/api/v1/platform/{environments,environments/[environmentId],services,services/[serviceId],capabilities,snapshot}/route.ts`
- Tests: `tests/control-plane-{registries,adapters,snapshot,security}.test.ts`
- Docs: `docs/console-foundation-a/*` (8)

## 4. Files changed
- `lib/operations-adapters.ts` — rewritten to a snapshot-backed legacy-shape mapper; **hardcoded
  topology (CLOUD_META/SERVICE_META, 41 markers) deleted**.

## 5. Registries implemented
Environment (2), Service (16), Capability (15) — server-owned, config-backed (no DB), public read
models strip endpoints/tokens; each exposed via an operator-gated BFF route.

## 6. Real services registered (16, = confirmed live topology)
Robozão: console, atlas(frozen), explorer, robozao-gateway, nexus, sport-hub, postgres, redis, qwen.
Google Cloud: gateway, social, anvil, cloud-postgres, cloud-redis, cloud-clickhouse, cloud-nginx.

## 7. Real capabilities registered (15, evidence-backed)
atlas.{health,intelligence,replay}.read · explorer.{health,missions,datasets}.read ·
robozao.operations.read · nexus.publications.read · gateway.{platform_health,audit,users}.read ·
social.{moderation.read, content.moderate(mutation, DECLARED), agents.read, users.read}. No
capability without a real route/RPC.

## 8. Adapter inventory
`base` (shared transport) + `HealthReadable` atlas/explorer/nexus + multi-service gateway
(platform-health) + robozao (operations). All read-only. Atlas consumed as frozen 1.0.0.

## 9. Platform Snapshot model
`generatedAt, partial, environments[], services[]{health,version,detail,source,activity},
capabilities{total,byState}, sources[]`. Bounded concurrency, per-adapter isolation, no fake health,
honest partial, freshness stamps.

## 10. Migrated read paths
`/api/operations/status` → `operationsSnapshot()` → `PlatformSnapshotService` → adapters → live
Atlas/Explorer/gateway/robozão. Rendered by the Operations Center **Infrastructure tab** (unchanged
UI, now server-sourced truth). Real Atlas read + real Explorer read both flow through the foundation.

## 11. Remaining legacy direct calls (documented)
`lib/cloud.ts` (`atlasIntelligenceCall` static `X-Internal-Token`; `explorerCall` `X-Operator`
string) and `lib/moderation.ts` (`moderator_id`) — unchanged, still used by other legacy routes;
targeted for SECURITY-A0 via the actor seam. `lib/robozao.ts` still serves `/api/v1/ops`.

## 12. Remaining hardcoded topology
None in the migrated surface (`operations-adapters.ts` = 0 maps). Untouched legacy pages may still
carry incidental service strings; not in scope this sprint (documented in MIGRATION.md).

## 13. Security boundary improvements
No arbitrary proxy/SSRF (fixed upstreams; ids validated, never URLs); no secret serialization
(tested); tokens centralized server-side; bounded/validated I/O; canonical errors that never leak
hosts/traces; actor seam forbids client-asserted identity and reserves `publicActor=null`.

## 14. Live Robozão validation
docker ps = registry robozão set; Atlas `/health` healthy (frozen, unmodified); Explorer `/health`
ok+version; robozao-gateway present. Read-only.

## 15. Live Google Cloud validation
docker ps = registry cloud set (gateway 0.1.9/social 0.1.5/anvil 0.1.0/datastores/nginx); gateway
`/healthz`→200; `/v1/console/platform/health`→401 (exists+gated); no data unauthenticated.

## 16. Test results
`tsc --noEmit` pass · `next lint` clean · `check:boundaries` OK · `next build` pass (6 platform
routes, 51 pages) · `vitest` **42/42 pass** (6 files; +27 new foundation tests) · `git diff --check`
clean.

## 17. Known limitations
- Operations Center **Overview** still derives readiness/coverage client-side (not a migrated area;
  CONSOLE-SERVICE-OPS-A).
- `/api/v1/platform/capabilities` has no dedicated UI yet (registry consumed server-side by the
  snapshot; capability UI later).
- Legacy attribution (`X-Operator`/`moderator_id`/static Atlas token) remains until SECURITY-A0.
- Snapshot uses live probes with no cache (acceptable for V1; documented — add short-TTL only if a
  measured need appears).

## 18. Exact prerequisites for CONSOLE-SECURITY-A0
1. Use `actor.ts` (`actorFromOperator`) as the attribution source; keep `publicActor=null` until
   CONSOLE-IDENTITY-A.
2. Replace `X-Operator` (Explorer) and body `moderator_id` (moderation) with the server-verified
   operator identity (or a signed control-plane assertion) — the adapters/base are the insertion
   point; no registry/snapshot redesign needed.
3. Route mutation attribution + approvals through a canonical audit event
   (`insight.operational_event.v1`) to the real audit spine (ADR-0005) — the error/observability
   split already keeps operational telemetry separate from audit.
4. Bring the direct `lib/cloud.ts` Atlas/Explorer calls behind a gateway/boundary adapter (ADR-0003)
   to retire the static internal token.

**Verdict:** CONSOLE-SECURITY-A0 can begin without redesigning this foundation. The Console has its
first real, secure, server-owned distributed Control Plane foundation, proven end-to-end by a live
vertical slice across both environments.
