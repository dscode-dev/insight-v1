# Insight Console — Official V1 Definition

**Status:** Ratified baseline (CONSOLE-ARCHITECTURE-A). Purpose: prevent sprint drift. Any future
Console sprint that contradicts this document must first amend it.

---

## What is Insight Console?
The **Human Control Plane of the Insight platform**: the single authenticated surface through
which authorized operators **observe, understand, manage, intervene, support, and audit** the
entire distributed platform (Social, Identity, Agents, Atlas, Explorer, Anvil, Nexus, Gateways,
Realtime, Data) across both environments (Google Cloud, Robozão).

It is **not** a dashboard, an IOC status page, a metrics wall, a health viewer, or a passive
observability frontend. Pages and metrics are not the measure of maturity — **audited capability
over real domain resources** is.

## What it is responsible for
1. **Observe** — real, service-reported state across all services/environments (no browser-derived
   "truth").
2. **Understand** — investigation across correlated events, audit, missions, users, content.
3. **Manage** — administer product domains via typed `domain.resource.action` capabilities.
4. **Intervene** — execute safe, authorized, audited operations through the control-plane boundary.
5. **Support** — investigate users/agents/content/services/missions/datasets/incidents.
6. **Audit** — reconstruct who/what/why/where/which-resource/what-result via one canonical spine.

## What it is NOT responsible for
- Owning domain business logic (that stays in each service).
- Owning platform topology as frontend constants (registries own it).
- Executing infrastructure directly (no SSH/Docker/shell/DB/secret access from browser or, where
  avoidable, the BFF).
- Redesigning or retraining Atlas (frozen), or any detector/threshold/ML.
- Being the durable store for operations, audit, or identity (services own those).

## Capabilities that MUST exist before V1 can freeze
- **Platform:** registry-backed service/environment/capability discovery; real health (both envs);
  SSE live surfaces; incident view backed by a real store.
- **Social:** content/comment/interaction/community/relationship **read** admin; moderation +
  community/user administration with dual-control on destructive actions.
- **Identity:** user/official-identity/agent/ownership model; explicit operator attribution;
  **Ninja** official identity with **explicit delegation, never silent impersonation**.
- **Agents:** activation + publication-state + execution history admin.
- **Intelligence/Data:** operator-bound reads of Atlas/Explorer; mission start/cancel behind
  approvals; DLQ replay audited.
- **Governance:** durable Operation Service (executor-ready), capability RBAC enforced at services,
  approvals, break-glass, one canonical audit spine.

## Mandatory security guarantees
- Verified, revocable operator sessions; server-side capability authz at the **service** (BFF is
  defence-in-depth).
- **Operator identity bound at the mutation point** — no client-asserted actor strings.
- Every sensitive read + every mutation emits canonical `insight.operational_event.v1` to the
  audit spine with operator + correlation + before/after.
- Dual-control + break-glass for `critical` actions; server-enforced sensitive-action confirmation;
  CSRF + rate limiting + replay protection on state-changing routes.
- No secrets in the browser; privileged secrets behind the boundary.

## Mandatory operational guarantees
- Single logical control-plane boundary (two physical gateways federated by the Environment
  Registry).
- Durable operation state (survives redeploy); idempotency, retries, partial success, rollback
  references.
- Per-surface failure isolation + circuit breakers; cursor pagination on all lists; honest empty/
  degraded states (never fabricated).

## Product domains controlled by V1
Platform · Social · Identity · Agents · Intelligence · Data · Realtime · Support · Governance.

## Explicitly V1.1 (not V1)
- Full distributed executor breadth beyond the initial safe action set.
- Advanced lineage, advanced realtime state-engine controls.
- Complete i18n breadth beyond frozen surfaces.
- Anvil deep workload control (needs a new worker control API).
- Any Atlas extension (remains frozen; new detectors go through the Atlas Quality Gate, not here).

## The standard
Console V1 is judged **not** by page/metric count but by whether it is **structurally capable of
being the secure Human Control Plane**: real capabilities over real resources, operator-bound,
audited, durable, behind one boundary — with the official identity model explicit and
impersonation impossible.
