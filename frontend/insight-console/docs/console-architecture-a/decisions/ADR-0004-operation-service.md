# ADR-0004 — Durable, executor-ready Operation Service (retire the `/tmp` domain)

**Status:** Proposed

**CURRENT STATE:** The Operation domain (`lib/operations-domain.ts`) persists to
`/tmp/insight-console-operations.json` (capped 500, read-modify-write, no locking),
synthesises lifecycle transitions at creation, emits `insight.operational_event.v1` **into the
file only**, and has `execution_enabled:false` with a SuperAdmin permission bypass.

**PROBLEM:** Ephemeral, non-durable, racy, single-replica, audit-bypassing. It cannot survive a
Console redeploy, support dual approval, idempotency, retries, partial success, long-running
operations, or distributed execution.

**DECISION:** Promote Operation to a **platform-owned Operation Service** with durable storage
(gateway-owned table or dedicated service) and an **executor-ready contract**: idempotency keys,
attempts/leases, dual-control (approver ≠ creator), rollback references, partial-success state,
and canonical event emission to the audit spine. The Console consumes it via a typed API. **Do
NOT implement the executor (IOC-EXECUTOR-A) here** — but the store/contract must be executor-ready.

**RATIONALE:** Operations are platform state, not frontend state. Durability + audit + dual-control
are prerequisites for any real intervention. Executor-readiness avoids a second migration.

**MIGRATION IMPACT:** Keep the 6-state lifecycle and event shape (good). Replace the file store;
repoint `/operations/history`. Remove the SuperAdmin bypass (explicit capability + audit even for
SuperAdmin). Until the executor exists, operations remain preview-only but **durable**.

**RISKS:** New service/table + migration. Mitigate by starting as a gateway-owned table reusing
the existing PG pool and audit spine, not a brand-new service.
