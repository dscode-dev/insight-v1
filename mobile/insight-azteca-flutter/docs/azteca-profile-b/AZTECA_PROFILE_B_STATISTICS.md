# AZTECA-PROFILE-B — Statistics

## Status: READY (real metrics only; no fabrication)
The Statistics tab renders from the enriched sports-profile payload (`GET /v1/users/{id}/sports-profile`),
which computes **backend-authoritative totals** via SQL subqueries — never client-side counts from one
pagination page.

## Exact real metrics used
| Metric | Source (backend-authoritative) |
|---|---|
| Reputation | `users.reputation` |
| Level | derived from reputation (deterministic, server value rendered) |
| Followers | `COUNT(relationships WHERE target_id=u.id AND kind='follow')` |
| Following | `COUNT(relationships WHERE actor_id=u.id AND kind='follow')` |
| Communities | `COUNT(community_members WHERE user_id=u.id)` |
| Posts | `COUNT(posts WHERE author_id=u.id AND author_type='user' AND deleted_at IS NULL)` |
| Signals | `COUNT(signals WHERE author_id=u.id)` |
| Role | const "supporter" (rendered, not fabricated per-user) |

## Not fabricated
No engagement KPIs, no misleading totals from partial lists, no sparkline for a single number, no
time-series (none exist → none drawn). No `fl_chart` added (no genuine series). If a real trend endpoint
lands later, INSIGHTS-A can add series primitives.

## Accessibility
Metrics use existing design-system tiles (icon + label + value); direction/deltas are not applicable (no
series). Semantic labels + contrast + text scaling honored by the shared primitives.
