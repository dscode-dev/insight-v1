# AZTECA-PROFILE-B — Communities Membership Projection

## Audit (real domain data EXISTS)
Social has `communities` + `community_members(user_id, community_id, is_moderator, joined_at)` tables (00001).
The sports-profile handler counts real memberships: `SELECT COUNT(*) FROM community_members cm WHERE
cm.user_id = u.id` → surfaced as the `communities` stat. So membership DATA is real, but:
- there is **no read endpoint** returning a user's community LIST (name/role) — only the count;
- the Hub/community product surfaces are mock-backed (`hub_service` fixtures) — see AZTECA-V1-AUDIT-A.

## Decision: honest state; do NOT build the Communities product
This stage is explicitly NOT AZTECA-COMMUNITIES-A. The profile Communities tab remains an honest state (the
real membership COUNT is shown in Statistics; the tab shows a truthful "find communities in Hub" placeholder).
Building a `GET /v1/users/{id}/communities` list projection + a real community destination is deferred to
COMMUNITIES-A (the Hub destinations are not yet real).

## Status: BLOCKED_BY_DOMAIN (honest)
Membership rows exist (count is real + shown), but a production list projection needs a real community
destination (Hub is mock). No mock communities, no generated memberships, no hardcoded cards are rendered.
