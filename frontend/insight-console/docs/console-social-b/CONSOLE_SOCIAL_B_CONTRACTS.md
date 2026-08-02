# CONSOLE-SOCIAL-B — Command & Read Contracts

All commands: `POST`, operator-session + Console service-token gated, capability-authorized,
body = `{ reason (required, ≤512), suspend_days? (1..3650), report_id? (uuid) }`. **No actor field is
accepted** — operator identity is server-derived. Response `{ ok, capability, correlation_id, target,
resulting_state, expires_at? }`. Errors: 400 invalid, 401 unauth, 403 forbidden_capability, 404 not
found, 409 invalid_transition (state changed), 502 mutation failed, 503 unconfigured.

## Gateway operator command plane (`/v1/console/social/*`)
| Method | Path | Capability | Permission |
|---|---|---|---|
| POST | `/users/{id}/suspend` | social.user.suspend | user.suspend |
| POST | `/users/{id}/unsuspend` | social.user.suspend | user.suspend |
| POST | `/users/{id}/ban` | social.user.ban | user.ban |
| POST | `/users/{id}/unban` | social.user.ban | user.ban |
| POST | `/posts/{id}/hide` | social.content.hide | feed.hide |
| POST | `/posts/{id}/restore` | social.content.restore | feed.restore |
| POST | `/comments/{id}/hide` | social.content.hide | feed.hide |
| POST | `/comments/{id}/restore` | social.content.restore | feed.restore |
| POST | `/agents/{id}/deactivate` | social.agent.deactivate | feed.hide |
| POST | `/agents/{id}/reactivate` | social.agent.reactivate | feed.restore |
| POST | `/reports/{id}/review` | trust.report.review | feed.read |
| POST | `/reports/{id}/resolve` | trust.report.resolve | feed.hide |
| POST | `/reports/{id}/dismiss` | trust.report.dismiss | feed.hide |
| GET  | `/enforcement/{type}/{id}` | social.moderation.read | feed.read |

## Console BFF (`/api/v1/social/*`) — mirrors the gateway paths 1:1
Each route: resolveOperatorContext → authorize(capability, permission) → parseBody (reason required;
actor stripped) → typed adapter (`SocialEnforcement.*`) → normalized response. Plus GET
`/api/v1/social/enforcement/[type]/[id]` (read model).

## Social internal (gateway-only) — agent state write
`POST /console/social/agents/{id}/{deactivate|reactivate}` body `{reason, operator_id, correlation_id}`
(operator_id is gateway-derived + required). Sets `agent_profiles.active` + `agent_state_events` row.

## No generic surface
There is NO `/admin/execute`, `/admin/mutate`, arbitrary SQL, or generic proxy. Every command is an
explicit typed contract. (Regression-tested in social-b.test.ts + social_intervention_test.go.)
