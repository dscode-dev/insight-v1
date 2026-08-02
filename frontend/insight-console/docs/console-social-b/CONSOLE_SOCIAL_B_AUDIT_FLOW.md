# CONSOLE-SOCIAL-B — Audit Flow (SECURITY-A1 canonical spine)

Every privileged intervention writes to `operator_audit_log` (the SECURITY-A1 durable spine), keyed by
one `correlation_id` shared across the lifecycle, idempotent per `(correlation_id, status)`:

```
resolve operator ─▶ authorize
     │                  │ deny ─▶ recordAudit(DENIED, deny, denied_permission_missing) ─▶ 403  (no mutation)
     │ allow
     ▼
recordAudit(AUTHORIZED, allow, authorized)   ← INTENT, BEFORE mutation
     │  fail ─▶ 500 audit_intent_failed  (high-impact fails closed; NO mutation)
     ▼
domain mutation (moderation.Act / TransitionReport / agent SetActive) [+ session revoke on ban/suspend]
     │  fail ─▶ recordAudit(FAILED, allow, <reason>) ─▶ 4xx/502
     ▼
recordAudit(COMPLETED, allow, completed)     ← OUTCOME
     ▼
verify post-condition (re-read UserState / IsContentHidden / resulting state) ─▶ response
```

- **Two-tier durability**: high-impact actions (ban/suspend/hide/agent-deactivate) never mutate before a
  durable intent row exists. Report transitions record intent→outcome too.
- **Domain vs canonical**: user/content actions ALSO write `moderation_actions` (Gateway domain log);
  agent transitions ALSO write `agent_state_events` (Social). The canonical `operator_audit_log`
  correlates all three via `correlation_id`. No cross-database transaction is claimed.
- **Idempotency / at-least-once**: a retried command with the same `X-Request-Id` reuses the correlation
  id ⇒ audit rows dedupe (ON CONFLICT idempotency_key) and the domain transition is naturally idempotent
  (upsert/PK/derived-state), so the resulting state converges. Exactly-once is NOT claimed.
- **Safe metadata only**: target_type/id, capability, reason, report_id, decision, reason_code. Secrets filtered.
