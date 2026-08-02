# AZTECA-POSTS-B — Publishing Consistency Matrix

Scoped invalidation (never blind whole-app invalidation).

| Action | Optimistic | Authoritative resp | Invalidation / reconcile | Rollback | Persists after restart |
|---|---|---|---|---|---|
| Create post | feed `prepend` (post-success only) | created post DTO | feed prepend + **`userPostsProvider(myId)`** (Activity) | draft kept on failure | YES (DB) + now in Global feed (Stage 1) + Activity |
| Like / Unlike | yes | 200 | `interactionSnapshotsProvider` merge | revert snapshot on failure | YES (interaction-states hydration) |
| Save / Unsave | yes | 200 | interaction snapshot | revert on failure | YES (SOCIAL-B hydration) |
| Boost / Unboost | yes | 200 | interaction snapshot | revert on failure | YES (SOCIAL-B hydration) |
| Create comment | pending state | comment DTO | comment list + `feed_provider.setCommentCount` (backend count) | input kept on failure | YES (DB); count from backend |
| Create reply | pending state | comment DTO | reply subtree + count | input kept on failure | YES (DB) |

## Key guarantees
- Create reconciles at minimum: Global feed (now includes own posts) + Own Activity + Post Detail availability.
- comment_count is authoritative (backend count), never a client-only increment surviving a failed request.
- save/boost/like hydrate from `interaction-states` on feed load ⇒ survive restart (SOCIAL-B preserved).
- No action triggers a global refetch; invalidation is scoped to the affected providers.

## Fixed this sprint
- Create → Own Activity was NOT reconciled (Activity read a stubbed endpoint). Now: Activity reads real
  `/v1/users/{id}/posts` + composer invalidates it on success.
- Create → Global feed contradiction (self-exclusion) resolved at the backend.
