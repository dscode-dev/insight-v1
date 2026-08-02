# CONSOLE-SOCIAL-A2 — Contracts

## insight-social (internal :8080, gateway-only; READ-ONLY) — 7 new
`GET /console/social/comments?limit&cursor&post_id&author_id&author_type` · `/comments/{id}` (comment
+ parent post + parent comment + replies) · `/communities?limit` · `/communities/{id}` (identity +
membership + moderators + recent members) · `/relationships?entity_type&entity_id` (followers/following/
memberships) · `/boosts?limit&cursor&post_id&user_id&status` · `/timeline?entity_type&entity_id&limit`
(DURABLE_ROW_PROJECTION). Author resolution type-aware in one query (no N+1). agent detail returns
`identity_type` (NO owner).

## insight-gateway — 7 new proxy routes
`GET /v1/console/social/{comments,comments/{id},communities,communities/{id},relationships,boosts,
timeline}` → `SocialConsoleProxy` (operator-session authed, forwards to social internal port). REUSED,
generic handler.

## Reused (Gateway-owned Trust & Safety + Audit — NOT duplicated)
Reports: `GET /v1/admin/moderation/reports`. Moderation history: `/v1/admin/moderation/actions`
(lib/moderation). Audit: `GET /v1/console/audit/events` (operator_audit_log, SECURITY-A1).

## insight-console — BFF + services
BFF (10 new): `/api/v1/social/{comments,comments/[id],communities,communities/[id],relationships,
boosts,reports,moderation,investigation/[type]/[id],timeline/[type]/[id]}` — each socialRead(capability,
permission, fn). Services: `InvestigationService.investigate(entityType,id)` composes summary/timeline/
relationships/amplification/trust_safety/administrative_audit panels (bounded concurrency, per-panel
failure isolation, source attribution); `TimelineService.timeline` correlates social+moderation+audit
with provenance. Adapters kept domain-specific (SocialControlPlane, GatewayTrustSafety, audit factory)
— no god adapter.

## Capabilities (grammar domain.resource.action)
social.comment.read (A1) · social.community.read · social.relationship.read · social.boost.read ·
social.save.read · social.investigation.read · trust.report.read · trust.moderation.read ·
audit.event.read. Enforced by authorize() (presence≠grant, fail-closed).
