# CONSOLE-SOCIAL-A1 — Implementation Delta (Stage 0)

Consumes the SOCIAL-A audit (docs/console-social-a/). Short delta only — then implemented.

## SOCIAL-A assumptions that remain TRUE (verified in code)
- agent_profiles has NO owner_user_id (5 fixed seeded agents ninja/pulse/oracle/sentinel/echo). No user↔agent ownership. Confirmed live (`slug` list).
- posts/comments = author_id + author_type∈{user,agent,admin} (shared actor, no FK). Preserved end-to-end.
- comments.depth CHECK IN (1,2) — depth-bounded threads.
- Reports/moderation = Gateway-owned (NOT in A1 slice). Content/identity/boosts/saves = Social.
- Saves individual → aggregate-only exposure.

## Reusable contracts
- Social HTTP internal port (:8080, gateway-only) with pgxpool handlers — pattern of competitions.go/interactions.go (network-isolated trust). Gateway proxies via `http.NewRequestWithContext` (competitions precedent).
- Gateway operator-session auth (`console.Handlers.requireOperator`), settings.SocialHTTPBaseURL (default http://insight-social:8080).
- Console: OperatorContext/resolveOperatorContext/authorize (SECURITY-A0/A1), adminFetch seam, canonical ControlPlaneError, capability registry.

## Missing contracts implemented this sprint
- insight-social: 8 read handlers (console_social.go) — overview/activity/users/user-detail/agents/agent-detail/posts/post-detail (projection SQL, no N+1).
- insight-gateway: SocialConsoleProxy (operator-gated) + 8 routes /v1/console/social/*.
- insight-console: SocialControlPlane adapter + 8 BFF routes + 8 workspaces + nav + 6 capabilities.

## Deployment targets / versions before change
Cloud: insight-social 0.1.5 → 0.1.6, insight-gateway 0.1.10 → 0.1.11. Robozão: insight-console 0.3.19 → 0.3.20. Atlas 1.0.0 FROZEN (untouched). No migrations (read-only).
