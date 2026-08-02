# CONSOLE-SOCIAL-B — Observability

Reuses existing telemetry (no second architecture).

## Metrics
- `social_agent_publish_blocked_total` (NEW, Social) — publications rejected because the agent is
  deactivated. Proves agent enforcement is real.
- `moderation_actions_total{action}` (existing, Gateway) — increments for every operator command that
  goes through `Act` (suspend_user/ban_user/restore_user/remove_content/restore_content) AND for report
  transitions (`report_reviewing|report_resolved|report_dismissed`).
- `moderation_reports_total{reason}`, `moderation_blocks_total{action}` (existing).

## Canonical audit as the intervention ledger
`operator_audit_log` records every intervention's DENIED / AUTHORIZED / COMPLETED / FAILED with
capability, target, reason_code, correlation_id. Queryable via `GET /v1/console/audit/events?outcome=…&
capability=…` — this IS the authorized/denied/completed/failed count + latency surface (occurred_at).

## Enforcement-state read model
`GET /v1/console/social/enforcement/{type}/{id}` returns current state + recent `moderation_actions`
history for operator visibility (active suspended/banned users, hidden content) without new counters.
