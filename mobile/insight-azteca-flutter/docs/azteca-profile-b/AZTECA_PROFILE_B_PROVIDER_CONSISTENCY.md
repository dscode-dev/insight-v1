# AZTECA-PROFILE-B — Provider Reconciliation

## Feed author identity architecture (verified)
Feed author display fields are NOT denormalized in `posts` — the feed repo LEFT JOINs `users` live
(`feedrepo`: `LEFT JOIN users u ON … u.id = p.author_id`). So a display-name change is reflected by any fresh
feed read; invalidating `feedProvider` re-fetches with the new name. Avatar is versioned (`?v=avatar_updated_at`).

## Scoped reconciliation after a successful display-name save
```
updateDisplayName(confirmed) →
  authProvider.updateDisplayName(confirmed)      // in-memory identity (header, composer author, comments)
  invalidate sportsProfileProvider(myId)         // profile header/stats read model
  invalidate userPostsProvider(myId)             // own Activity author label
  invalidate profileBundleProvider               // stats/badges bundle
  invalidate feedProvider                         // feed author label (live JOIN → new name)
```
No blind whole-app invalidation. Activity pagination is reset intentionally (author label must refresh) —
acceptable since it re-reads the same authoritative endpoint.

## Avatar success reconciliation
cache evict(old+new) → authProvider.updateAvatar → invalidate sportsProfile + profileBundle + feed.

## Public profile consistency
Public profile reads the same `sportsProfileProvider(userId)` + `userPostsProvider(userId)` + `FeedItem`
renderer. After the owner edits, another viewer opening that profile gets the updated name/avatar on their next
fetch (no client cache of other users' identity beyond the image cache, which is versioned/evicted).

## Regression coverage
`edit_profile_test.dart` covers the form contract; full suite (75) green proves no profile/feed/identity
regression. Author-label reconciliation is a live-read consequence (documented) + covered by the feed's live
JOIN architecture.
