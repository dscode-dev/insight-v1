# CONSOLE-SOCIAL-A — Admin Read Contract Strategy (Stage 2/3)

Per-capability decision. No `GET /admin/dump-everything`, no generic SQL/proxy, no browser→social.

## Constraint from the audit
The gateway has **no social DB pool** and reaches social only via app-oriented gRPC. Rich operator
projections (posts with counts + boost/report state, activity, investigation, timeline) are **not**
expressible through existing gRPC. Therefore:

| Capability | Decision | Why |
|-----------|----------|-----|
| Reports / moderation stats / actions | **REUSE_EXISTING_ENDPOINT** | gateway `/v1/admin/moderation/{reports,stats,actions}` already durable + operator-authed |
| Moderation ↔ audit correlation | **REUSE** (SECURITY-A1) | `operator_audit_log` via `/v1/console/audit/events` |
| Users list/get, Agents list/get (basic) | **ADD_GATEWAY_BFF_AGGREGATION** over existing gRPC `UserService.{List,Get,GetStats}` / `AgentService.{List,Get}` | gateway-only change, reuses social contracts (limited fields) |
| Posts list (with counts/author/boost/report state), Post detail, Comments thread, Activity, Boosts, Save aggregate, per-entity Timeline, Investigation | **ADD_SOCIAL_ADMIN_READ_ENDPOINT** (new, in insight-social) then **gateway proxy** under `/v1/console/social/*` | requires social-DB aggregate projections that only social can compute efficiently (no N+1) |

## Proposed contracts (capability-oriented; implement only what the audit supports)
```
# gateway BFF over existing social gRPC (phase 1 — no social deploy):
GET /v1/console/social/overview
GET /v1/console/social/users            ?limit&cursor&q
GET /v1/console/social/users/{id}
GET /v1/console/social/agents           ?limit&cursor&active
GET /v1/console/social/agents/{id}

# new social admin read endpoints, gateway-proxied (phase 2 — social deploy):
GET /v1/console/social/posts            ?author_type&author_id&since&until&boosted&limit&cursor
GET /v1/console/social/posts/{id}
GET /v1/console/social/comments         ?post_id&author_id&limit&cursor
GET /v1/console/social/comments/{id}
GET /v1/console/social/activity         ?kind&actor_type&since&until&limit&cursor
GET /v1/console/social/boosts           ?post_id&status&limit&cursor
GET /v1/console/social/investigation/{entityType}/{entityId}
GET /v1/console/social/timeline/{entityType}/{entityId}
# communities/relationships: only if the communities schema supports member counts + activity
```
All are **GET, operator-session gated** (like the existing `/v1/console/*` reads), cursor-paginated,
bounded page sizes, validated filters/sort. Ingest-style service-token is NOT needed for reads (reads
use the operator Bearer; the existing console read pattern).

## Authorization (Stage 3) — capabilities (evidence-backed, `domain.resource.action`)
`social.overview.read` · `social.activity.read` · `social.post.read` · `social.comment.read` ·
`social.user.read` · `social.agent.read` · `social.community.read` · `social.relationship.read` ·
`social.report.read` (maps to existing `feed.read`) · `social.moderation_history.read` (`audit.read`) ·
`social.boost.read` · `social.investigation.read`. Registered in the Capability Registry (descriptive);
enforced via the real `authorize()` seam (SECURITY-A0) against operator permissions — **capability
presence never authorizes**. Reads require an operator with `console.access` + the mapped read
permission; no service token to the browser; no browser-supplied identity.

## Explicitly NOT added
No mutation endpoints (SOCIAL-B). No endpoints for absent concepts (no user↔agent owner). No individual
save-relationship endpoint (SAVE_PRIVACY). Atlas untouched.
