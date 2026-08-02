# CONSOLE-ARCHITECTURE-A — Stage 10: V1 Implementation Roadmap

Validated against audit evidence. The proposed 16-sprint sequence is **largely sound**, with
**three evidence-based adjustments**:

1. **Insert CONSOLE-SECURITY-A earlier** (identity binding + audit spine are prerequisites for any
   mutation — SEC-1/2/6). Split: a **SECURITY-A0 "attribution & audit" foundation** before
   SOCIAL-A; keep the broader SECURITY-A hardening later.
2. **Add a registries/boundary foundation** to CONSOLE-FOUNDATION-A (ADR-0001/0002/0003) — nothing
   downstream is safe while topology is hardcoded and adapters live in the frontend.
3. **Move the Operation Service (ADR-0004) ahead of IOC-EXECUTOR-A** as its own step, since
   several domains need durable operations + approvals before execution exists.

---

## Validated sequence

| # | Sprint | Purpose | Prereqs | Services | Key contracts | Non-goals | Prod risk | Certification |
|---|--------|---------|---------|----------|---------------|-----------|-----------|---------------|
| 1 | **CONSOLE-FOUNDATION-A** | Boundary + registries + capability model + thin BFF; decompose mega-component behind stable routes | This audit | gateway | registry read, capability grammar | no new mutations | Low | registries drive Operations Center; no topology constants; build green |
| 1.5 | **CONSOLE-SECURITY-A0** (new) | Operator-identity binding + canonical audit for existing mutations | #1 | gateway, social, explorer | ADR-0005/0006 | no new domains | Med | moderation/explorer actor server-bound; events in spine |
| 2 | **CONSOLE-SOCIAL-A** | Social **read** admin (posts/comments/interactions/communities/relationships/content-origin) | #1,#1.5 | social, gateway | `social.*.read` contracts | no moderation changes | Med | real social admin reads, paginated, audited |
| 3 | **CONSOLE-SOCIAL-B** | Social **moderation/administration** (content + community + user actions) | #2 | social, gateway | `social.*.moderate/administer` | no official identity | **High** | dual-control on destructive; full audit |
| 4 | **CONSOLE-IDENTITY-A** | Identity model: users/official identities/agents/ownership/operator attribution; **Ninja** relationship | #1.5 | gateway, social | ADR-0007 shape | no silent impersonation | **High** | delegation explicit + audited; no impersonation |
| 5 | **CONSOLE-AGENTS-A** | Agent admin: activation/publication-state/execution history/provider route | #4 | social, nexus, explorer | `social.agents.*` | no new agent runtime | Med | agent activate/publication audited |
| 6 | **CONSOLE-SERVICE-OPS-A** | Finish Operations decomposition; SSE live surfaces; incidents backed by real store | #1 | gateways | registry + events stream | no fake incidents | Med | SSE live; per-surface error isolation; no derived "truth" |
| 7 | **CONSOLE-INTELLIGENCE-A** | Atlas/Explorer intelligence behind boundary (read); mission start/cancel behind approvals | #1.5 | atlas(frozen), explorer | `atlas.*.read`, `explorer.missions.*` | **no Atlas logic change** | Med | operator-bound reads; mission cancel exists + approved |
| 8 | **CONSOLE-DATA-A** | Data/ingestion/datasets/lineage/DLQ/Anvil workloads | #6,#7 | explorer, anvil, robozão | `explorer.*`, `anvil.*` | no pipeline redesign | Med | DLQ replay operator-bound + audited |
| 9 | **CONSOLE-REALTIME-A** | Active matches/streams/consumers/lag/stale-source ops views | #6 | gateway realtime, sport-hub | SSE ops topics | no app realtime change | Med | operator realtime surfaces; lag visible |
| 10 | **IOC-EXECUTOR-A** | Execute approved operations (distributed, idempotent, retries, rollback) | ADR-0004 service | Operation Service, adapters | executor contract | limited action set first | **High** | idempotency/partial-success/rollback proven |
| 11 | **CONSOLE-SUPPORT-A** | Cross-domain support: user search, account state, activity, relationships, cases | #2,#4,#5 | social, gateway | support case model | no new moderation | Med | support view aggregates real domains |
| 12 | **CONSOLE-SECURITY-A** | Full hardening: dual-control, break-glass, CSRF, rate limit, replay, sensitive-confirm | #1.5+ | gateways, services | ADR-0006/0008 | — | Med | pen-review; break-glass audited |
| 13 | **CONSOLE-UX-FREEZE-A** | Capability-driven IA freeze; remove duplication clusters | most above | console | — | no new domains | Low | IA stable; orphans removed |
| 14 | **CONSOLE-I18N-B** | Complete i18n on frozen surfaces | #13 | console | — | no new surfaces | Low | catalogs complete |
| 15 | **CONSOLE-CERTIFY-A** | End-to-end control-plane certification (evidence-based) | all | all | — | — | Low | READY per domain, audited |
| 16 | **CONSOLE-FREEZE-A** | Freeze Console V1 architecture/contracts | #15 | — | — | — | Low | V1 frozen |

**Ordering rationale (evidence):** attribution+audit (SEC-1/2/6) gate every mutation → they come
before SOCIAL-B/IDENTITY. Registries+boundary (DF-1/3, ADR-0001/0003) gate everything → in
FOUNDATION. Operation Service (CA-1..10) precedes the executor. Atlas stays read-only and frozen
throughout (INTELLIGENCE-A touches contracts, never logic/thresholds).

**Roadmap verdict:** the intended sequence holds with the three adjustments. FOUNDATION-A is
unambiguously first and its scope is now concretely defined by this audit.
