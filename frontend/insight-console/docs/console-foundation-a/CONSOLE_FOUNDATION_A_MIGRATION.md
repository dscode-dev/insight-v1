# CONSOLE-FOUNDATION-A — Migration

## Vertical slice migrated (proves the foundation is real, not decorative)
```
Operations Center · Infrastructure tab (client)
  → GET /api/operations/status                       (existing route, UNCHANGED contract)
    → lib/operations-adapters.operationsSnapshot()   (REWRITTEN: now a thin legacy-shape mapper)
      → PlatformSnapshotService.generate()           (NEW: server-owned truth)
        → EnvironmentRegistry + ServiceRegistry + CapabilityRegistry   (NEW)
        → AtlasAdapter / ExplorerAdapter / GatewayAdapter / RobozaoAdapter / NexusAdapter  (NEW)
          → real upstreams (Atlas :8085, Explorer :8090, robozão-gw :8095, cloud gateway)
```
The UI contract (`OperationsSnapshot`/`ServiceAdapterSnapshot`) is preserved, so the Operations
Center renders unchanged **but now consumes registry + snapshot truth** instead of hardcoded
topology. This satisfies: real Atlas read path (AtlasAdapter.readHealth), real Explorer read path
(ExplorerAdapter.readHealth), and UI consumption of registry/snapshot data.

## Hardcoded topology removed (Stage 9)
`grep` inventory in `lib/operations-adapters.ts`:
- **Before:** 41 topology markers (`CLOUD_META`, `SERVICE_META`, per-service host/region/deps/caps,
  literal `insight-atlas`/`insight-social`/… placement).
- **After:** 0 topology maps. The file is now a pure mapper from the canonical snapshot; all
  host/region/dependency/capability facts come from the registries. The `endpoint` field emitted to
  the browser is the **environment label**, never an internal URL.

## KEEP / CHANGE / DEPRECATE
| Item | Disposition |
|------|-------------|
| `lib/admin-api.ts`, `api-guard.ts`, `session.ts` | KEEP (foundation seam reused) |
| `lib/operations-adapters.ts` | CHANGED → snapshot-backed mapper (topology deleted) |
| `lib/control-plane/**` (new) | ADDED (registries, adapters, snapshot, errors, actor, observability) |
| `app/api/v1/platform/**` (new) | ADDED (6 routes) |
| `lib/cloud.ts` (direct Atlas/Explorer internal-token) | DEPRECATE (still used by other legacy routes; unchanged this sprint) |
| `lib/robozao.ts` | KEEP (still used by `/api/v1/ops`, `/api/ops/robozao/status`) |

## Explicitly NOT migrated (remain legacy — documented)
- Operations Center **Overview** readiness/coverage/insights (still client-derived) — not a
  migrated area; flagged for CONSOLE-SERVICE-OPS-A.
- Other pages (missions, datasets, atlas, moderation, publication, admin, audit, dlq) — untouched;
  they keep their existing data paths.
- `/api/v1/platform/capabilities` has no dedicated UI yet (registry consumed server-side by the
  snapshot; capability UI is a later sprint).
- Operation domain (`/tmp`) — untouched by design (CONSOLE-OPERATIONS-A).
