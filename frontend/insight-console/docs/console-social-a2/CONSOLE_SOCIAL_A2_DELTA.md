# CONSOLE-SOCIAL-A2 — Implementation Delta (Stage 0)

Builds on A1 (docs/console-social-a1/). No re-audit. Deploy is USER-OPERATED (not performed here).

## A1 facts reused (unchanged)
Browser→BFF→SocialControlPlane→Gateway→Social; operator-gated; keyset pagination; author_type
preserved; type-aware author resolution (no N+1); capability authorization. Source-of-truth split:
Social owns content/identity/relationships/boosts/saves; Gateway owns reports/moderation/audit.

## Semantic correction (MANDATORY, done)
A1 rendered agent `owner: none (platform)`. **Removed.** Social handler now returns
`identity_type: "platform_agent"` (no `owner` field); Console agent detail shows "Identity type:
Platform agent". No owner_user_id / linked_user_id introduced. User↔agent identity stays for
CONSOLE-IDENTITY-A.

## New schema used (verified)
communities(id,slug,name,topic,kind,competition_id,member_count,active_now); community_members(user_id,
community_id,is_moderator,joined_at); moderation_reports(target_type post|comment|user, status
open|reviewing|resolved|dismissed) + moderation_actions(report_id,moderator_id,action,target_*,note)
= Gateway-owned; comments(parent_id self-FK, depth∈{1,2}); relationships(actor_id,target_id polymorphic,
kind); boosts(boost_type,weight,status,expires_at). Existing indexes cover the new list paths.

## Missing contracts implemented
Social: 7 read endpoints (comments/comment-detail/communities/community-detail/relationships/boosts/
timeline). Gateway: 7 proxy routes (reuse SocialConsoleProxy). Console: adapter readers +
GatewayTrustSafety + InvestigationService + TimelineService + 10 BFF routes + 8 capabilities + 7 UI
surfaces + Investigation Workspace + nav.

## Deployment targets (USER-OPERATED)
Cloud: insight-social 0.1.6→0.1.7, insight-gateway 0.1.11→0.1.12. Robozão: insight-console 0.3.20→0.3.21.
No migrations. Atlas 1.0.0 FROZEN.
