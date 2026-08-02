# CONSOLE-ARCHITECTURE-A — Final Report

**Date:** 2026-07-03 · **Type:** Audit + architecture baseline (no product changes) ·
**Classification:** **READY**

---

## 1. Executive verdict
The Insight Console is a **broad, well-built, but viewer-biased observability frontend** that is
**not yet structurally a control plane** — and, crucially, the reasons are now precisely known.
The path to the Human Control Plane is **primarily a backend-contract and boundary/security
problem, not a UI problem**. Service boundaries, live distributed topology, the control-plane
boundary, the capability model, the security model, operation ownership, the adapter strategy, and
the implementation sequence are all established with concrete evidence. **CONSOLE-FOUNDATION-A can
begin without major ambiguity.**

Do not mistake breadth for maturity: 34 pages and many metrics notwithstanding, the Console has
**exactly two real, audited control surfaces** (Moderation, Publication/Nexus). Everything else is
observation, preview, or read-only administration.

## 2. Most important architectural findings
1. **~85% viewer / ~15% controller.** Only Moderation and Nexus publication mutate real state with
   audit. Users/Operators/Sessions are read-only despite a rich RBAC catalog.
2. **Split, inconsistent trust boundary (DF-1).** Gateway-mediated *and* direct-to-service
   (Console holds `X-Internal-Token` for Atlas, asserts `X-Operator` string to Explorer). The
   Console is a privileged internal client — the top boundary problem.
3. **Attribution is client-asserted on both real mutation paths (SEC-1/2).** `moderator_id` and
   `X-Operator` are caller-supplied; not bound to a verified session at the mutation point.
4. **Platform "truth" is browser-derived (DF-2/IA-4).** Readiness, coverage, insights, health
   scores are computed in a 1606-line client component, not reported by services.
5. **Topology is hardcoded in the frontend (DF-3).** `CLOUD_META`/`SERVICE_META` bake host/region/
   deps/capabilities — there is no registry.
6. **The Operation domain is an ephemeral `/tmp` JSON file (CA-1..10).** Non-durable, racy,
   audit-bypassing, SuperAdmin-bypass, `execution_enabled:false`. Conceptually right, structurally
   wrong.
7. **RBAC vocabulary ≫ enforcement points (SEC-4).** Permissions name ban/suspend/scheduler.*/
   provider.*/model.* with almost no backing routes — an illusion of control.
8. **Social admin depth is absent** beyond moderation; Agent admin, community admin, identity
   mutations, official-identity/delegation, and a support case model do **not exist anywhere**.

## 3. Current Console maturity assessment
| Dimension | Maturity |
|-----------|----------|
| Frontend engineering (Next.js server-first, correlation, Zod, typed gateway seam) | **Good** |
| Authentication (revocable operator sessions, HttpOnly cookie, server-side role checks) | **Good** |
| Observation of real state (health both envs, intelligence/data reads) | **Moderate–Good** |
| Real control (mutation) | **Weak** (2 surfaces) |
| Authorization enforcement at services | **Weak** (BFF-only for the real mutation) |
| Attribution & audit completeness | **Weak** (client-asserted; audit spine bypassed by ops) |
| Domain admin contracts | **Weak/Absent** (Social/Identity/Agents/Support) |
| Topology/registry discipline | **Weak** (hardcoded) |
| Operation durability/governance | **Weak** (ephemeral file) |

## 4. Major structural risks
- **R1** Adding mutations on today's split boundary + client attribution would ship real IDOR/
  privilege-escalation surface. **Fix attribution+audit first (SECURITY-A0).**
- **R2** The 1606-line polling mega-component is a reliability and correctness liability (no
  isolation/pagination, derived truth). Decompose behind stable routes.
- **R3** Ephemeral Operation domain will silently lose approvals/history on redeploy.
- **R4** Hardcoded topology guarantees drift and blocks capability discovery.
- **R5** Official-identity pressure could produce silent impersonation if the delegation shape is
  not fixed now (ADR-0007).

## 5. Confirmed topology (both environments, live)
- **Cloud** (`instance-20260604-195317`): nginx, **gateway 0.1.9**, **social 0.1.5**, **anvil
  0.1.0** (headless worker), postgres16/redis7.4/clickhouse24.12.
- **Robozão:** **console 0.3.18**, **atlas 1.0.0 (frozen)**, **explorer 0.0.20**, **robozao-gateway
  0.0.2**, **nexus 0.0.2**, sport-hub, pgvector-pg16, redis7.4, qwen/ollama.
- **Two gateways, one on-prem Console authenticating against cloud identity**, direct
  Atlas/Explorer seam on-prem.

## 6. Capability gap summary
Real & usable: platform health (both envs), moderation, Nexus publication, Atlas/Explorer reads,
audit read, permission catalog. Dominant gaps: **domain admin contracts** (Social/Identity/Agents/
Support), a **platform registry**, **governance mutation durability**, and **official-identity
delegation**. Becoming a control plane is mostly about building these contracts behind one boundary.

## 7. Refactor summary
KEEP the server-first shell, gateway seam, guards, and the two real control surfaces. REFACTOR the
mega-component (decompose + SSE), the Operation domain (→ durable service), and moderation
attribution. MOVE adapters + topology + operation logic out of the frontend. DEPRECATE the
direct-service internal-token seam and `lib/db.ts`/`pg`. REMOVE dead/duplicate surfaces
(`/atlas` index, `/console/[...path]`, `/cloud`↔Infra, `/explorer`↔Data, DI dashboard, `/live`).
**No rewrite.**

## 8. Security summary
Authentication is solid; **authorization + attribution + audit are not yet control-plane grade.**
Required before mutations: server-bound operator identity (ADR-0006), one canonical audit spine
(ADR-0005), capability authz at the service (ADR-0002), dual-control/break-glass for critical
actions, CSRF/rate-limit/replay, and the explicit non-impersonation official-identity model
(ADR-0007).

## 9. Validated V1 roadmap (16 steps)
Sequence confirmed with three evidence-based adjustments: **registries+boundary in FOUNDATION-A**,
a **SECURITY-A0 attribution+audit step before SOCIAL-A**, and the **Operation Service ahead of
IOC-EXECUTOR-A**. Atlas stays frozen and read-only throughout. Full table in
`CONSOLE_ARCHITECTURE_A_ROADMAP.md`.

## 10. Exact prerequisites for CONSOLE-FOUNDATION-A
1. Adopt the **capability grammar** `domain.resource.action` + a **Capability Registry** seeded
   from `roles.go` + the IOC-CONTROL-A action catalog (ADR-0002).
2. Stand up **Service + Environment Registries**; delete `CLOUD_META`/`SERVICE_META`; Operations
   Center reads registries (ADR-0001).
3. Define the **control-plane boundary contract** (thin BFF; adapters behind the boundary) —
   ADR-0003; keep Nexus as the reference pattern.
4. Specify the **durable Operation Service** store/contract (executor-ready; not the executor) —
   ADR-0004; migrate off `/tmp`.
5. Fix the **audit spine + operator-attribution** shape so events carry operator + correlation +
   `public_actor` placeholder (ADR-0005/0006/0007).
6. Decompose `operational-command-center.tsx` behind unchanged routes (no behavior change).

## 11. Validation (no regressions — audit added docs only)
| Check | Result |
|-------|--------|
| `git diff --check` | clean |
| `git status` | only `docs/console-architecture-a/` added (no code touched) |
| `tsc --noEmit` (typecheck) | **pass** |
| `next lint` | **pass** (no warnings/errors) |
| `check:boundaries` | **pass** (no legacy service deps) |
| `next build` | **pass** (all 34 routes; `/operations` largest at 19.3 kB — mega-component) |
| `vitest run` | **pass** (15 tests / 2 files) |

## 12. Final classification — **READY**
The audit is complete enough that CONSOLE-FOUNDATION-A can begin without major ambiguity about
service boundaries, distributed topology (confirmed live), control-plane boundaries, capability
model, security model, operation ownership, adapter strategy, and implementation sequence. Known
capability gaps are the **subject** of the roadmap, not blocking unknowns. No production mutations
were performed; no fake data, topology, or capabilities were introduced.

**Deliverables (this sprint):** `docs/console-architecture-a/` — BASELINE, INFORMATION_ARCHITECTURE,
DATA_FLOWS, CAPABILITY_GAPS, SERVICE_CONTRACTS, CONTROL_AUDIT, SECURITY, TARGET, REFACTOR_BLUEPRINT,
ROADMAP, CONSOLE_V1_DEFINITION, FINAL, and `decisions/ADR-0001..0008`.
