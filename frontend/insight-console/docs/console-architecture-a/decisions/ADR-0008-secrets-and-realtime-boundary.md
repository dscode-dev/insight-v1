# ADR-0008 — Secrets stay behind the boundary; realtime via SSE, not client polling

**Status:** Proposed

**CURRENT STATE:** The Console BFF holds `ADMIN_API_INTERNAL_TOKEN`, `ATLAS_INTERNAL_TOKEN`, and
`X-Console-Service-Token` and calls Atlas/Explorer directly. High-value surfaces (Operations
Center) **poll 8 endpoints every 10s** from the browser with no backoff.

**PROBLEM:** (a) Infra/service secrets in the frontend deployable widen blast radius and block
non-Console clients from reusing contracts safely. (b) Client polling loops are wasteful, race
under load, and give no ordering/lag guarantees.

**DECISION:** (1) **Secrets boundary:** privileged service secrets live at the control-plane
boundary, not the Console. The Console holds only what it needs to authenticate the operator
session and call the boundary. Direct-service internal tokens are removed as adapters migrate
(ADR-0003/0006). The browser holds **no** credentials beyond the HttpOnly session cookie. (2)
**Realtime:** high-value live surfaces consume **operator-scoped SSE** from the boundary (the
gateway already exposes `/v1/events/stream` and `/v1/realtime/sse`); polling is reserved for
low-frequency/summary data with backoff.

**RATIONALE:** Least-privilege for the frontend; efficient, ordered, lag-aware realtime;
consistent with the single-boundary rule.

**MIGRATION IMPACT:** Move internal tokens to the boundary as adapters migrate; convert the
Operations Center's 10s poll to SSE for live tabs; keep polling (with backoff) for summaries.

**RISKS:** SSE fan-out scaling (mitigate: operator-scoped topics, boundary backpressure).
Interim period where both patterns coexist (acceptable; migrate per-surface).
