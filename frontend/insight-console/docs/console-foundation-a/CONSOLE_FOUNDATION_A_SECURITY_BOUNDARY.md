# CONSOLE-FOUNDATION-A — Security Boundary

## Guarantees implemented
1. **No arbitrary proxy / no SSRF.** There is no `/api/proxy?url=`. Every upstream call targets a
   **fixed** config-resolved base URL + **fixed** path. The browser supplies only registry *ids*,
   which are validated (`isValidId`) and used for lookup — never concatenated into a URL. Invalid /
   injection-shaped ids (`http://169.254.169.254/…`, `file:///etc/passwd`, `../../secret`) resolve
   to `null`/404 (tested).
2. **No secrets in browser payloads.** Internal tokens + upstream URLs live only in
   `lib/control-plane/config.ts` (server). Public read models omit `endpoint`/`token`; tests assert
   the serialized services/environments/capabilities and the snapshot contain no token, no host, no
   `http://`, no port.
3. **No browser infrastructure access.** No SSH/Docker/gcloud/DB/credentials anywhere in the client
   or the new BFF. Adapters run server-side only.
4. **Bounded + validated I/O.** Per-adapter timeout, 2 MB response cap, JSON validation, canonical
   errors that never leak stack traces or hosts.
5. **Auth preserved.** Every new route calls `requirePermission("console.access")`; the operator
   session Bearer is forwarded server-side to gateway/robozão; the service token is server-held.
6. **HTTP status honesty.** Upstream failures keep real status codes; partial aggregates return 200
   only with an explicit `partial` + per-source state.

## Actor seam (Stage 12 — prepare SECURITY-A0, do not implement)
`lib/control-plane/actor.ts`:
- `actorFromOperator(operator, correlationId)` builds attribution **only** from a server-verified
  operator — never a fabricated `"admin"`, never a browser-supplied id.
- `publicActor` is reserved (ADR-0007 official-identity delegation) and **always `null`** this
  sprint — silent impersonation is not representable.
- `rejectClientAssertedActor(field)` hard-throws — the insecure `X-Operator`/`moderator_id` pattern
  cannot be re-introduced through the foundation.

## Remaining self-asserted attribution (documented, out of scope — SECURITY-A0)
These pre-existing paths are **unchanged** and remain legacy until SECURITY-A0:
- `lib/moderation.ts` → `moderator_id` in the POST body (Gateway moderation).
- `lib/cloud.ts` `explorerCall` → `X-Operator` string to Explorer.
- `lib/cloud.ts` `atlasIntelligenceCall` → static `X-Internal-Token` (no operator identity).
The new foundation does **not** reproduce these patterns; the actor seam is the clean insertion
point to fix them without redesigning registries/adapters/snapshot.
