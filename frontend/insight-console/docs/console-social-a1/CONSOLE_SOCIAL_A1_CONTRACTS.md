# CONSOLE-SOCIAL-A1 — Contracts

## insight-social (internal HTTP :8080, gateway-only; READ-ONLY)
`GET /console/social/overview?window=1d|7d|30d|90d` · `/activity?limit&kind` · `/users?limit&cursor&q` ·
`/users/{id}` · `/agents` · `/agents/{id}` · `/posts?limit&cursor&author_type&author_id&boosted` ·
`/posts/{id}`. Projection SQL over pgxpool; author resolved type-aware (users∪agent_profiles) in one
query. Trust = network isolation (same as competitions/interactions).

## insight-gateway (operator-authed proxy)
`GET /v1/console/social/*` → `console.Handlers.SocialConsoleProxy`: `requireOperator` (session) →
forwards GET to `SOCIAL_HTTP_BASE_URL + /console/social/*` (fixed prefix, never caller-chosen host) →
4 MiB cap, correlation propagated, passthrough. 8 routes registered.

## insight-console (BFF + adapter)
`GET /api/v1/social/{overview,activity,users,users/[id],agents,agents/[id],posts,posts/[id]}` →
`socialRead(capability, permission, fn)`: resolveOperatorContext → authorize → SocialControlPlane
adapter (adminFetch to gateway, operator Bearer) → canonical error mapping. Adapter split by resource
(overview/activity/user/agent/post readers), not a god interface.

## Capabilities (evidence-backed; `domain.resource.action`)
social.overview.read · social.activity.read · social.user.read · social.agent.read · social.post.read
· social.comment.read. Mapped to real permissions (feed.read for content/overview/activity, user.read
for users/agents). Registry presence never grants — authorize() is the decision.
