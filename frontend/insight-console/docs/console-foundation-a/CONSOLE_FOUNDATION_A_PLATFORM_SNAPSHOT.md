# CONSOLE-FOUNDATION-A — Platform Snapshot

`lib/control-plane/snapshot.ts` — where distributed platform truth is assembled **server-side**
(no longer the browser). Backs `GET /api/v1/platform/snapshot` and the migrated
`/api/operations/status`.

## Model (`types.ts` `PlatformSnapshot`)
`generatedAt`, `partial`, `environments[]`, `services[]` (each: public service + `health` +
`version` + `detail` + `source` + real `activity`), `capabilities{total, byState}`, `sources[]`.
Each `SourceStatus` carries `service`, `environment`, `state`, `observedAt`, `latencyMs`, `stale`,
and an optional normalized `error`.

## Assembly rules
- **Bounded concurrency:** the 5 fixed adapters run in parallel; each has its own timeout.
- **Failure isolation:** adapters never throw — they return `AdapterResult` with source attribution.
  One slow/broken service cannot block or collapse the snapshot.
- **Health provenance:** Atlas/Explorer/Nexus from their direct adapters; cloud services
  (social/anvil/cloud-datastores/gateway) from the gateway platform-health probe; robozão-gateway
  from its own status; console = healthy (it is serving); services with no Console probe
  (sport-hub, datastores, nginx, qwen) = **`unknown`** with an `unsupported` source.
- **No fake health:** an unobserved or errored service is `unknown`/`unavailable`, never `healthy`.
  A gateway timeout marks the gateway `unavailable` but its dependents `unknown` (we did not observe
  them — we do not assert they are down).
- **Honest partial:** `partial = true` iff any of the 5 real sources is not `available`. HTTP 200
  with `partial:true` is a **modeled** partial result (sources carry state), not a silent fallback.
  Errors are never turned into `[]`/`{}`/`0`.
- **Freshness:** every source stamps `observedAt` + `latencyMs`; `stale` is reserved for cached reads
  (direct probes are `stale:false`).

## Derived model (Stage 7)
Only **deterministic** derivation is server-side: normalized service state, capability effective
states (from health), source-degradation (`partial` + per-source `state`), environment membership.
Unsupported browser heuristics (readiness %, coverage, "insights") were **not** promoted to platform
truth — they remain clearly in the (unmigrated) client tabs and are flagged for later replacement.

## Tests (`tests/control-plane-snapshot.test.ts`)
all-available⇒not-partial + real health + unprobed=unknown · gateway timeout⇒partial + dependents
unknown + atlas still healthy (isolation) + source state `timeout` · one 503⇒that service unavailable,
others intact · deterministic shape across repeated runs.
