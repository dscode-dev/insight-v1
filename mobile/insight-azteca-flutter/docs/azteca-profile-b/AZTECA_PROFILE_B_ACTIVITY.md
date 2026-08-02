# AZTECA-PROFILE-B — Activity (POSTS-B preservation)

## Status: READY (unchanged; verified not regressed)
POSTS-B made own Activity read real `userPostsProvider` → `GET /v1/users/{id}/posts` with the canonical
`FeedItem` renderer. This sprint does NOT rewrite it. Verified:
- own Activity uses `userPostsProvider(myId)`; public profile uses `userPostsProvider(userId)` — same source;
- pagination / pull-to-refresh / loading / empty / error states intact;
- stable keys (`ValueKey(post.id)`); canonical `FeedItem` shared Feed/Activity/Public/Detail;
- Post Detail navigation intact.

## Interaction with this sprint
A display-name edit invalidates `userPostsProvider(myId)` (author label refresh) — Activity re-reads the same
authoritative endpoint, so content is unchanged, only the rendered author name updates. No new defect
introduced; full test suite green.
