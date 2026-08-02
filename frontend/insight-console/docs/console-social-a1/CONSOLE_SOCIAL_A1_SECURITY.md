# CONSOLE-SOCIAL-A1 — Security

## Boundary (browser never reaches Social)
Browser → Console BFF (/api/v1/social/*) → SocialControlPlane adapter → Gateway (/v1/console/social/*)
→ internal Social HTTP → Social PG. The browser only calls same-origin /api; no Social host, no service
token, no DB detail ever reaches browser code.

## Authentication + authorization (reused foundation)
Every BFF route: resolveOperatorContext (verified Gateway session; SECURITY-A0) → authorize(capability,
permission) real decision (registry presence never grants; fail-closed) → adapter. The Gateway proxy
independently re-validates the operator session (requireOperator) before forwarding. Verified live:
unauth /v1/console/social/* → 401; console pages → 307 login; BFF → 401.

## Read-only + privacy
No mutation, no execution. Save exposure is AGGREGATE ONLY (save_count) — individual savers never
exposed. Agent detail shows owner = "none (platform)" (no fabricated user↔agent ownership). Author
identity honest: resolved name when available, else id+type preserved (no invented "Usuário").

## Error distinction (canonical model)
Adapter maps upstream status → UNAUTHORIZED/FORBIDDEN/NOT_FOUND/SERVICE_UNAVAILABLE/TIMEOUT/
UPSTREAM_ERROR; the UI renders distinct states (loading/empty/error/unavailable/timeout/unauthorized).
Upstream failure is NEVER an empty array.
