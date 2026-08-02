# CONSOLE-SOCIAL-A2 — Investigation Architecture

## Server-side composition (browser never joins domains)
`InvestigationService.investigate(ctx, entityType, id)` orchestrates domain adapters with
`Promise.all` over failure-isolated panels (`panel()` wraps each in try/catch → {state, data, error}):
- summary: SocialControlPlane get{User,Agent,Post,Comment,Community} (or reports for report root)
- timeline: SocialControlPlane.timeline (user/agent/post)
- relationships: SocialControlPlane.relationships (user/agent)
- amplification: SocialControlPlane.listBoosts (post/user)
- trust_safety: GatewayTrustSafety.forTarget (reports+moderation for the target)
- administrative_audit: getAuditRepository().query({resourceId}) (operator_audit_log)
Returns `{entity, partial, sources[{panel,state,source}], panels}`. A failed panel is PRESENT + marked
`unavailable` (never omitted); `partial=true` if any source failed.

## Entity roots + stable deep links
`/social/investigate/{type}/{id}` where type ∈ user|agent|post|comment|community|report. The route is
the investigation truth (deep-linkable). Comments/Reports rows link into investigation; breadcrumbs
preserve trail. Domain ownership stays explicit (source attribution per panel: insight-social vs
insight-gateway vs operator_audit_log).

## NO ownership field
Agent investigation shows identity type "Platform agent" — never an owner. user→agent follow is
rendered as a follow relationship only.
