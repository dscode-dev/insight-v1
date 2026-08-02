# CONSOLE-SOCIAL-B — Report Lifecycle Integration

## Ownership
Reports are Gateway-owned (`moderation_reports`, existing vocabulary open|reviewing|resolved|dismissed).
SOCIAL-B adds operator transitions — no invented statuses.

## Operator transitions (typed, audited)
- `review`  → reviewing (open|resolved|dismissed → reviewing)
- `resolve` → resolved  (open|reviewing → resolved)
- `dismiss` → dismissed (open|reviewing → dismissed)
Same-state is idempotent; illegal destinations return 409 invalid_transition. `open` is only an initial
state (not a transition destination).

## Correlation with enforcement
When enforcement originates from a report, the operator passes `report_id` on the user/content command;
`moderation.Act` stamps `moderation_actions.report_id` AND auto-resolves the report (existing behavior),
and the canonical audit carries `report_id`. Standalone report transitions (no content/user side effect)
go through the report endpoints. Correlation is explicit (shared ids), never an atomic cross-DB transaction.

## Flow
```
Report → Investigate (A2) → Decision → [user/content command w/ report_id] → moderation_actions
       → report transition (review/resolve/dismiss) → canonical audit (correlation_id)
```
