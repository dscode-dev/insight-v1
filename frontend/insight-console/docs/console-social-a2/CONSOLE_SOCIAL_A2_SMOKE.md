# CONSOLE-SOCIAL-A2 — Post-Deploy Smoke Runbook (read-only)

Use a real authorized operator session (Console login, or a temporary operator_session row deleted
after). Base = https://insight-api.konohalabs.com.br. No mutation. Do not ban/hide/remove.

## Gateway → Social (curl; expect 200 + shape)
```
# unauth gate (expect 401)
curl -s -o /dev/null -w '%{http_code}\n' -X GET $B/v1/console/social/comments
# with Bearer $TOK (operator session):
curl -s $B/v1/console/social/comments?limit=5 -H "Authorization: Bearer $TOK"       # items[], author.type preserved
curl -s $B/v1/console/social/communities     -H "Authorization: Bearer $TOK"       # items[] w/ member_count
curl -s "$B/v1/console/social/relationships?entity_type=user&entity_id=$UID" -H "Authorization: Bearer $TOK"  # relationships[]
curl -s "$B/v1/console/social/boosts?status=active" -H "Authorization: Bearer $TOK" # items[] real boost entities
curl -s "$B/v1/console/social/timeline?entity_type=user&entity_id=$UID" -H "Authorization: Bearer $TOK" # provenance=DURABLE_ROW_PROJECTION
curl -s $B/v1/console/social/agents/$AGENTID -H "Authorization: Bearer $TOK"        # identity_type=platform_agent, NO owner
```

## Checklist (29)
1 comments list real · 2 comment detail resolves author · 3 reply preserves parent · 4 depth ∈{1,2}
· 5 communities list real · 6 community detail memberships · 7 relationships real · 8 user→agent shown
as follow only · 9 **no ownership field** (agents: identity_type=platform_agent) · 10 reports from
Gateway · 11 report target resolves social context (Console: /social/investigate/{type}/{id}) · 12
moderation history distinct from audit · 13 boosts real · 14 saves aggregate-only (save_count) · 15
**no saver identities in any payload** · 16-21 Investigation Workspace opens for user/agent/post/
comment/community/report (`/social/investigate/{type}/{id}`) · 22 timeline provenance chips (durable
row / moderation record / administrative audit) · 23 partial upstream failure honest (panel marked
unavailable, `partial=true`, not empty) · 24 unauthorized → 401/403 · 25 invalid filter safe
(author_type=DROP → 200 ignored; bad uuid → 400) · 26 no host/token/trace in payloads · 27 no mutation
controls in UI · 28 Atlas 1.0.0 untouched · 29 execution_enabled false.

## Console routes to inspect
/social · /social/comments · /social/communities(/:id) · /social/boosts · /social/reports ·
/social/moderation · /social/investigate/user/:id · /social/investigate/post/:id ·
/social/investigate/agent/:id (verify no owner) · /social/investigate/comment/:id.

## DB verification (read-only, optional)
`SELECT save_count …` is aggregate; confirm no endpoint returns saved_posts.user_id.
`SELECT column_name FROM information_schema.columns WHERE table_name='agent_profiles'` → no owner_user_id.
