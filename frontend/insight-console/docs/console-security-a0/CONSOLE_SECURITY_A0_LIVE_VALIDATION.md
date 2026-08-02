# CONSOLE-SECURITY-A0 — Live Dual-Environment Validation (read-only)

Read-only. No moderation performed, no Social writes, no Atlas/Explorer intelligence mutation, no
DB writes.

## Google Cloud (verified-session source + canonical spine)
- `POST /v1/operator/auth/login` → **400** (real operator-auth endpoint; needs a body).
- `GET /v1/operator/auth/me` (no token) → **401** — the server-side session verification that
  `resolveOperatorContext` depends on is live and gated.
- `GET /v1/console/audit` (no auth) → **401** — the canonical audit spine READ path exists + gated.
- Cloud Postgres `insight_auth` (read-only `to_regclass`): **`operator_audit_log` exists** (durable
  canonical spine) and **`operator_sessions` exists** (validates `sessionId = sha256(token)` maps to
  a real session key). No data read, no writes.

## Robozão
- Console 0.3.18 runs here and authenticates against the Cloud gateway (cross-env trust confirmed in
  prior sprints). No changes made. Atlas 1.0.0 untouched.

## What was validated at the contract/integration level (not destructively)
1. Verified-session source — live (`/me` 401). ✓
2. Operator context derivation — server-side, unit-tested; live session source confirmed. ✓
3. No browser-controlled actor becomes authoritative — code + `assertNoClientActor` + tests. ✓
4. Moderation compatibility bridge — `moderator_id` server-derived (code); not exercised
   destructively (no real moderation action taken). Contract-level. ✓
5. Canonical audit persistence — durable Postgres store implemented; **not live-activated** (no
   `CONSOLE_AUDIT_DATABASE_URL` / migration not applied / console image not rebuilt). Runtime store
   is in-memory + honest `reconciliationNeeded`. ← the PARTIAL limitation.
6. Audit read API — `/api/v1/audit/events(/:id)` built + builds in production bundle. ✓
7. Correlation chain — propagated via `x-request-id`/`x-correlation-id`; audit carries it. ✓
8. No secrets in audit — tested (tokens/objects dropped). ✓
9. No Atlas mutation, no Explorer intelligence mutation, no Social content mutation. ✓

## Honest limitation
End-to-end durable audit could not be live-validated without provisioning
`CONSOLE_AUDIT_DATABASE_URL` + applying the migration + rebuilding/redeploying the console (a deploy
step) OR shipping the Gateway audit-ingest endpoint (a cloud-gateway deploy). Neither was performed
to avoid unrelated/risky production mutation. No production evidence was fabricated.
