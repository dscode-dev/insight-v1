# ADR-0003 — Service Admin Adapters live behind the boundary, not in the Console

**Status:** Proposed

**CURRENT STATE:** The Console BFF is the de-facto adapter layer: `lib/moderation.ts`,
`lib/cloud.ts` (Atlas/Explorer), `lib/robozao.ts`, `lib/operations-adapters.ts`. Some go through
the gateway; some call services directly with internal tokens.

**PROBLEM:** Domain adapters embedded in the frontend deployable couple admin contracts to the
Console release cycle, spread trust (Console holds `X-Internal-Token`), and prevent server-side
capability enforcement at the service.

**DECISION:** **Admin contracts are owned by the control-plane boundary / services.** The Console
BFF becomes thin: session, correlation, coarse capability pre-check, response shaping. Each domain
gets a typed **Service Admin Adapter** at the boundary (Social, Identity, Agent, Atlas, Explorer,
Anvil, Nexus, Platform-Ops). Nexus's authed+audited+tier-RBAC API is the reference pattern.

**RATIONALE:** Decouples admin evolution from Console releases; centralises authz/audit at the
service; removes privileged secrets from the frontend; enables reuse by non-Console operators
(CLI, automation) under the same contracts.

**MIGRATION IMPACT:** Move moderation/atlas/explorer adapter logic behind the gateway over time;
Console keeps thin BFF passthroughs. Start with read parity, then mutations.

**RISKS:** Interim duplication while adapters migrate (mitigate: migrate per-domain, keep BFF
passthrough stable). Boundary becomes higher-value target (mitigate: Stage 6 security model).
