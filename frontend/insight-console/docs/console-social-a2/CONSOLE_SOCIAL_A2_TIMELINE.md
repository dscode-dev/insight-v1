# CONSOLE-SOCIAL-A2 — Correlated Timeline

`TimelineService.timeline(ctx, entityType, id)` merges three sources, each provenance-tagged, and
NEVER silently drops a failed source (it appears in `sources[]` with state unavailable → `partial`).

| Source | Provenance | Origin |
|--------|-----------|--------|
| Social durable rows (posts/comments/follows/boosts for the entity) | `DURABLE_ROW_PROJECTION` | insight-social (NOT an immutable event log — labelled) |
| Gateway moderation actions for the target | `MODERATION_RECORD` | insight-gateway/moderation |
| Administrative audit events referencing the resource | `ADMINISTRATIVE_AUDIT` | operator_audit_log (SECURITY-A1) |

Each item: `{id, at, kind, domain, provenance, target, summary, correlation_id}`. Deterministic order
(time desc, id tiebreaker). The UI shows a provenance chip per item so an operator can tell a durable-
row projection from an immutable event or a moderation/audit record. Correlation id preserved where
present (audit events). Honest partial state: a down source is represented, not hidden.
