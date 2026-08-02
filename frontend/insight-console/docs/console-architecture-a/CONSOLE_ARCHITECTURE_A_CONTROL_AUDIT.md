# CONSOLE-ARCHITECTURE-A — Stage 5: Control Panel & Operation Domain Audit

Deep audit of IOC-CONTROL-A (action catalog/preview) and IOC-CONTROL-B1 (Operation domain
lifecycle). Source of truth: `lib/operations-domain.ts` (244 LOC), `app/api/v1/control/
operations/route.ts`, `app/(console)/operations/history/page.tsx`.

---

## 1. What exists
- **Operation lifecycle** (`OperationStatus`): draft → validated → waiting_approval → approved →
  ready_for_execution → cancelled. Implemented in `operations-domain.ts`.
- **Per operation:** operation_id, type, risk_level, target_service/resource, requested_action,
  preview_payload, impact_analysis, rollback_availability, execution_policy, correlation_id,
  `operational_events[]` (schema `insight.operational_event.v1`), `audit_trail[]`,
  `permission_evaluation`, optional `dry_run`.
- **Operations:** `create` (auto-runs draft→validated→permission_checked→waiting_approval),
  `dryRun`, `approve` (→ ready_for_execution), `cancel`, `list`.
- **Preview semantics:** `execution_policy.execution_enabled = false`,
  `executable_in: "IOC-CONTROL-B2"`, `direct_service_calls_allowed: false`.

## 2. What is wrong (evidence-based)

| # | Finding | Evidence |
|---|---------|----------|
| CA-1 | **Persistence is an ephemeral local file** | `STORE_PATH = /tmp/insight-console-operations.json`, `slice(-500)` |
| CA-2 | **Does not survive Console redeploy / not shared across replicas** | file on the Console container's `/tmp` |
| CA-3 | **Read-modify-write race** | `readStore()`→push→`writeStore()` with no lock/txn |
| CA-4 | **Lifecycle is synthesised, not driven** | `create()` appends validated/permission_checked/waiting_approval in one call |
| CA-5 | **Events never leave the record** | `operational_events[]` pushed into the file; no IOC bus / audit spine emission |
| CA-6 | **SuperAdmin bypass on permission eval** | `operator.role === "SuperAdmin" \|\| permissions.includes(...)` |
| CA-7 | **No execution, by design** | `execution_enabled:false` — correct for now, but the domain can't host execution later |
| CA-8 | **Owned by the Console BFF** | domain logic + storage live in the frontend deployable |
| CA-9 | **No idempotency / retry / partial-success / long-running model** | single-shot record; no operation keys, attempts, or step state |
| CA-10 | **Approval is single-writer** | `approve()` flips status; no dual-control, no approver identity separation from creator |

## 3. Direct answers to the mandated questions
- **Is Operation a proper platform-level domain?** — Conceptually yes; **structurally no**. It is
  a frontend artefact today.
- **Incorrectly owned by the Console frontend/BFF?** — **Yes.** It must move to a platform service.
- **Should operation state survive Console redeploys?** — **Yes.** Today it does not (CA-1/CA-2).
- **Is current persistence durable?** — **No** (ephemeral file).
- **Can it support distributed executors?** — **No** (no queue, no lease, no idempotency).
- **Idempotency?** — **No.** **Retries?** — **No.** **Rollback?** — only a text field.
- **Dual approval?** — **No** (single-writer approve, SuperAdmin bypass).
- **Correlate with service events?** — **No** (events don't reach the bus/audit).
- **Partial success?** — **No.** **Long-running operations?** — **No.**

## 4. Disposition

| Element | Verdict | Rationale |
|---------|---------|-----------|
| Lifecycle state machine (the 6 states) | **KEEP (as spec)** | Good model; re-home it |
| `insight.operational_event.v1` shape | **KEEP** | Canonical; reuse verbatim |
| Impact/rollback/permission-evaluation fields | **KEEP (as contract)** | Right fields |
| JSON-file persistence | **REMOVE** | Ephemeral, racy, non-durable |
| Domain logic in `lib/operations-domain.ts` | **MOVE** | To a platform Operation Service (durable store, queue) |
| `create()` synthesised transitions | **REFACTOR** | Transitions must be driven by real validation/approval |
| SuperAdmin bypass | **REFACTOR** | Explicit permission required even for SuperAdmin, with audit |
| Control Panel UI (`/operations/history`) | **KEEP + REFACTOR** | Repoint to the service; add approver separation |
| Action catalog (IOC-CONTROL-A) | **KEEP** | Reuse as the capability catalog seed |

## 5. Decision
**The Operation domain must become a durable, platform-owned Operation Service** (own DB or a
gateway-owned table + queue), consumed by the Console via a typed contract, emitting canonical
events to the real IOC/audit spine. **Do not implement IOC-EXECUTOR-A here** — but the target
store/contract (Stage 7 + ADR) must be executor-ready (idempotency keys, attempts, leases,
dual-approval, partial-success, correlation). Until then the Control Panel stays **preview-only**
but backed by durable state, not `/tmp`.
