# CONSOLE-SOCIAL-A1 — Live Production Smoke (read-only)

Real authorized operator session (temporary admin session minted + DELETED after; no data mutated).
No Social write, no ban, no removal. Atlas untouched; execution_enabled false.

## Cloud (Gateway → Social)
| # | Check | Evidence |
|---|-------|----------|
| gate | unauth /v1/console/social/overview | **401** |
| 1 | Overview real | users:1, agents:5, posts:14, comments:10, follows:4, active_boosts:3; source insight-social; unavailable=[dau,mau,engagement_rate] (honest, no fabrication) |
| 5,12 | Authorship (author_type) | posts_by_user:14, posts_by_agent:0, comments_by_user:10 — origin distinguished |
| 5,6 | Agents real | 5 seeded: ninja/pulse/oracle/sentinel/echo, all active |
| 3,11 | Users real | staging_1782061859, 12 posts |
| 7,9 | Posts real + author resolved | author_type=user, author username resolved, counts present |
| 8,9,10 | Post detail | author "Staging B1" (@staging_…) RESOLVED, engagement + comments + boosts present |
| 13 | Save aggregate-only | save_count exposed; no saver identities |
| 14 | Invalid filter safe | author_type=DROP → 200 (ignored); invalid uuid → 400 |
| 15 | Unauthorized fail-closed | 401 |
| 16 | No secret/host/DB in payload | responses carry only projected fields + source label |

## Robozão (Console)
- console 0.3.20 healthy. `/console/api/v1/social/{overview,posts}` → **401** (BFF gated, no session).
- `/console/social`, `/console/social/posts` → **307** → `/console/login?next=%2Fsocial…` (deep-link
  preserved). 8 social pages + 8 BFF routes present in the build.

## Not driven (documented)
Full authenticated browser UI flow requires operator login credentials (not available to the harness);
every layer is validated independently (gateway→social returns real data with a real session; console
BFF/adapter unit-tested + gated live). No production data mutated.
