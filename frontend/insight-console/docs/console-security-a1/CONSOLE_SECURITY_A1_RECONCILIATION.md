# CONSOLE-SECURITY-A1 — Reconciliation Model

Minimal, production-grade — no workflow engine.

## Detection
An administrative action chain shares one `correlation_id`. An incomplete chain is one with a
non-terminal last state (AUTHORIZED/STARTED present, no COMPLETED/FAILED/CANCELLED). The canonical
read (`GET /v1/console/audit/events?correlation_id=…`, ordered `created_at DESC, id DESC`) makes this
detectable: query a correlation chain and inspect for a terminal `outcome_status`.

## Signal
When a write is not durably persisted (Gateway unreachable / non-durable store), the writer returns
`reconciliationNeeded:true` and emits `audit_reconciliation_needed` (security telemetry, distinct
from canonical audit). High-risk intents fail-closed instead (no orphaned mutation).

## Idempotent recovery
Because persistence is idempotent on `idempotency_key`, a later retry of a missing transition is
safe: it either creates the (previously-failed) row or no-ops on the existing one. A COMPLETED is
never duplicated; a succeeded action is never recorded as FAILED (the outcome is written from the
real result).

## Deliberately out of scope (documented)
No scheduled reconciliation job / retry queue is introduced (the platform has no idle queue that
warrants it for V1). The detection query + reconciliation marker + idempotent replay are sufficient;
a scheduled sweeper can be added later against the same `correlation_id`/terminal-state query without
schema change.
