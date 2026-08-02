# CONSOLE-SOCIAL-A2 — Security

## Boundary (unchanged from A1, extended)
Browser → Console BFF (/api/v1/social/*) → domain adapters → Gateway (/v1/console/social/* +
/v1/admin/moderation/* + /v1/console/audit/events) → Social / Gateway. No browser→Social, no browser
cross-domain join, no service token in browser, no internal host/topology in browser code.

## Authorization (capability, fail-closed)
Every BFF route: resolveOperatorContext (verified session) → authorize(capability, permission) real
decision (registry presence never grants) → adapter/service → canonical error normalization. Trust
reads require feed.read; social reads feed.read/user.read; investigation social.investigation.read.
The Gateway proxy independently re-validates the operator session. Composed investigation authorizes
social.investigation.read at the route; per-panel upstreams (audit/moderation) that the operator lacks
access to degrade that panel to `unavailable` (fail-closed at panel level) rather than leaking.

## Cross-domain composition is server-side only
InvestigationService/TimelineService run in the BFF; the browser receives composed read models, never
raw multi-domain rows to join. Domain ownership stays explicit (source attribution per panel/source).

## Read-only
No mutation route, capability, or control added. execution_enabled false. Atlas 1.0.0 untouched.
