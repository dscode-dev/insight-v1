# CONSOLE-SECURITY-A1 — Schema Mapping & Migration

## Migration 00007 (additive, backward-compatible, idempotent)
`insight-gateway/migrations/00007_operator_audit_canonical.sql` — `ALTER TABLE operator_audit_log
ADD COLUMN IF NOT EXISTS …` for: capability, correlation_id, session_id, target_environment,
target_service, target_resource_type, target_resource_id, authz_decision, authz_reason_code,
outcome_status, idempotency_key, source. Plus a **partial unique index** on `idempotency_key WHERE
NOT NULL` and btree indexes (correlation_id, capability, outcome_status, `(created_at,id)`).

No renames, no data rewrite. Existing moderation/auth rows keep working (new columns NULL). **Applied
live: goose "OK 00007 … successfully migrated to version 7"; 52 pre-existing rows preserved; all 8
verified columns present; idempotency index present.**

## Console `AdministrativeAuditEvent` → `operator_audit_log`
| Canonical dimension | Column |
|---------------------|--------|
| WHO | `operator_id` (gateway-derived), `session_id` (`sha256(token)`) |
| WHAT | `capability`, `event_type` (= capability), `outcome_status` (lifecycle) |
| TARGET | `target_environment`, `target_service`, `target_resource_type`, `target_resource_id` |
| AUTHORIZATION | `authz_decision`, `authz_reason_code` |
| OUTCOME | `outcome_status` |
| CORRELATION | `correlation_id`, `request_id` |
| TIME | `created_at` (server) |
| context | `metadata` jsonb (sanitized), `reason` (in metadata), `source` |

Fields the minimal spine does not round-trip on read (roles, delegation, authStrength) are defaulted
by the Console read projection — the security-critical dimensions are all first-class columns (not
buried in JSON). JSON metadata is sanitized + size-bounded and is NOT used to avoid first-class
security fields.

## Federation with moderation
Moderation keeps its domain audit in `moderation_actions` (unchanged) AND — when driven through the
Console — also emits a canonical `operator_audit_log` record via ingest. One canonical spine
(`operator_audit_log`) for Console-originated administrative audit; correlation_id links chains.
