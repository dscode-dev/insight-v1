# AZTECA-PROFILE-B — Username & Identity Safety

## Username: NOT editable in V1 (deliberate)
Username is a UNIQUE, deep-linked handle (`/users/:id`, universal links). Editing it safely requires: canonical
normalization, uniqueness re-check, reserved-name list, case policy, confusable/invisible-character handling,
and a migration/back-compat story — none of which exist today. Adding a naive editor would risk broken deep
links and identity confusion. Decision: **preserve existing username semantics; do not edit in V1**; documented
as technical debt for a dedicated identity sprint. The Edit Profile screen shows username read-only.

## Display name: safe, permissive
- Bounded to 64 runes (schema `VARCHAR(64)`), rune-counted (multi-byte names not unfairly rejected).
- Unicode allowed — no aggressive restriction on legitimate names.
- Trimmed; non-empty required. Server-authoritative validation; client mirrors for UX.
- Rendered through existing text widgets (no raw HTML). No invisible-only enforcement added (display name is
  not an identity key, so ambiguity risk is low; documented rather than over-restricted).

## No mass assignment / no privilege escalation
The write contract accepts display_name only; reputation/level/tier/role/username/avatar/counts cannot be set
via PATCH. Identity (user id) is server-derived from the session, never from the body.
