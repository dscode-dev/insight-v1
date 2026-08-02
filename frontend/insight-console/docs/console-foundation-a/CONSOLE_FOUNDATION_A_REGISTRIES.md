# CONSOLE-FOUNDATION-A — Registries

Three server-owned registries (ADR-0001/0002). **Persistence decision: code + validated config,
NO database.** The service/environment set is deployment topology (changes with releases, reviewed
in code), not runtime user data; a DB would add operational surface with no V1 benefit. `configured`
is derived from validated env (`lib/control-plane/config.ts`); public read models strip endpoints/tokens.

## Environment Registry — `registries/environments.ts`
- `list()`, `get(id)`, `isValidId(id)`. Two environments (confirmed live): `robozao` (on-prem),
  `google-cloud` (us-central1-c). Public model: id, displayName, type, location, active, metadata,
  serviceIds. No URLs/secrets. New environments add here with no page changes.

## Service Registry — `registries/services.ts`
- Seed = **exactly the 16 confirmed live containers** across both environments (no invention).
- INTERNAL `ServiceDescriptor` holds adapter wiring + `endpointKey` (names a config upstream; the
  URL is never inlined). PUBLIC `ServicePublic` strips endpoint/token and adds `configured`.
- **CONFIGURED ≠ AVAILABLE ≠ HEALTHY** are distinct: `configured` = Console has a usable route
  (from validated config); availability/health come from the live snapshot. Nexus with no
  `NEXUS_API_BASE_URL` ⇒ `configured:false` (honest), never a guessed host.
- `list({environment,domain,adapterKind})`, `get(id)`, `isValidId(id)`.

## Capability Registry — `registries/capabilities.ts`
- Grammar `domain.resource.action` (ADR-0002). **Descriptive discovery, NOT authorization.**
- Every capability carries real `evidence` (a route/RPC from the audit). No evidence ⇒ not
  registered (never invented). 15 capabilities across atlas/explorer/robozao/nexus/gateway/social.
- States: DECLARED/DISCOVERED/AVAILABLE/DEGRADED/UNAVAILABLE/UNSUPPORTED. READ capabilities are
  resolved to AVAILABLE/DEGRADED/UNAVAILABLE from live service health by the snapshot; **MUTATION
  capabilities stay DECLARED** — this sprint neither exercises nor enables any mutation.
- `list({service,domain,actionType})`, `get(id)`, `effectiveState(cap, health)`, `isValidId(id)`.

## BFF read surfaces (operator-gated, no secrets)
`GET /api/v1/platform/environments` · `/environments/:id` · `/services` (?environment,?domain) ·
`/services/:id` · `/capabilities` (?service,?domain,?actionType) · `/snapshot`.

## Consumption (not decorative)
The Service + Environment registries and all adapters are consumed by `PlatformSnapshotService`,
which backs the **migrated** `/api/operations/status` — rendered live by the Operations Center
Infrastructure tab. The Capability registry is consumed server-side by the snapshot (capability
summary) and exposed via its route (dedicated capability UI is a later sprint).
