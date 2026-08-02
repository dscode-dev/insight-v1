# AZTECA-PROFILE-B — Backend Profile Write Contract

## Endpoint
`PATCH /v1/users/me` (gateway) → `PATCH /users/me/profile` (internal Social HTTP, gateway-only).
Chosen HTTP (not a new gRPC/proto method) to reuse the existing preferences/avatar pattern and avoid a
buf/proto regen for a single-field write.

## Identity & safety
- **Authenticated only** (`requireAuth`); operator/user identity is **server-derived** — the gateway forwards
  the verified user via `X-User-Id`; the request body can never carry a user id.
- **No mass assignment**: the body decodes ONLY `display_name` (a `*string` pointer = present/omitted). Any
  other key is ignored. No reputation/tier/role/avatar/username/counts mutation is possible.
- **Partial update**: omitted `display_name` → 400 `no_editable_fields` (no silent no-op).

## Validation (Social handler `me_profile.go`)
- trim; non-empty → else 400 `display_name_required`.
- rune length ≤ 64 (mirrors `VARCHAR(64)`; counts runes not bytes so multi-byte names aren't unfairly cut) →
  else 400 `display_name_too_long`.
- Unicode allowed (no aggressive restriction — legitimate names preserved).
- Parameterized `UPDATE users SET display_name=$2 WHERE id=$1 RETURNING …`; missing row → 404.
- Returns the authoritative projection `{id, username, display_name, initials, accent_color, reputation, tier}`.

## Username
NOT writable in V1 (documented technical debt): changing a unique, deep-linked handle needs confusable/
reserved-name policy + migration evidence that does not yet exist. Existing username semantics preserved.

## Audit history
Social has no general profile-change outbox/event mechanism; a display-name change is a direct column update.
Not fabricating a second audit platform. Documented limitation: profile edits are not currently event-audited
(unlike Console operator actions which use `operator_audit_log`). Low-risk for a self-service display name.

## Gateway
`interactions.Handler.UpdateMyProfile` forwards PATCH + body + `X-User-Id` to Social; normalizes upstream
status; leaks no infra detail. Route `route(PATCH, "/v1/users/me", …)` under `requireAuth`.
