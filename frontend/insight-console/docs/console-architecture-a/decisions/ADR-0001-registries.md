# ADR-0001 — Service & Environment Registries replace hardcoded topology

**Status:** Proposed (CONSOLE-ARCHITECTURE-A)

**CURRENT STATE:** Topology is a frontend constant — `CLOUD_META` + `SERVICE_META` in
`lib/operations-adapters.ts` hardcode each service's host/region/dependencies/capabilities and
even a static `state` ("waiting batch"). Two environments (cloud, robozão) are implied by string
prefixes and `startsWith("insight-")`.

**PROBLEM:** A control plane cannot key authority, health, or capability discovery off frontend
constants. New services require a Console redeploy; dependencies drift silently; the "environment"
concept is inferred, not declared.

**DECISION:** Introduce a **Service Registry** and an **Environment Registry** owned by the
control-plane boundary. Services/gateways report id, kind, env, version, dependencies,
capabilities, health/metrics endpoints. The robozão `OperationsService.Capabilities` already
provides part of this; the cloud gateway gains an equivalent. The Console consumes registries;
it holds **no** topology constants.

**RATIONALE:** Single source of truth; new services appear without a Console deploy; dependency
graphs and capabilities become service-reported facts, not UI guesses.

**MIGRATION IMPACT:** Delete `CLOUD_META`/`SERVICE_META`; Operations Center reads the registry.
Backfill the registry from the current maps as seed data. Backwards-compatible via a registry
adapter that falls back to health-only rows (honest "unknown", never fake).

**RISKS:** Registry becomes a new critical dependency (mitigate: cache + honest degraded mode).
Initial registry content must be verified against live topology to avoid re-encoding stale maps.
