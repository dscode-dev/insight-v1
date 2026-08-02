# AZTECA-POSTS-B — Own-Post Feed Semantics

## Decision: self-authored PUBLIC posts participate in the authoritative Global feed by normal recency
No pin, no priority, no bypass, no client-only cache — just removal of the special-case exclusion.

## Change (insight-social)
`internal/application/feed/service.go` — Global feed public-fill loop: removed `item.Post.AuthorID ==
userID` from the skip condition. Now only `seen` (dedupe) + `muted` exclude a candidate.

```
// before: if seen[id] || item.Post.AuthorID == userID || muted[author] { continue }
// after:  if seen[id] || muted[author] { continue }
```

## Why this is safe (verified)
- **No duplicates**: own posts enter ONLY via the public fill (a user never follows themselves, so they are
  absent from the followed-agents/followed-users candidates). `seen` still dedupes.
- **Ranking**: own posts compete by `created_at DESC` in `RecentPublic` like any public post — no pin.
- **Cursor/pagination**: unchanged — `RecentPublic(before, …)` keyset by created_at; own posts slot in by time.
- **Following feed**: unchanged — still followed-authors-only (own posts intentionally not there; the Global
  landing feed + Profile▸Activity cover discoverability).
- **Agent/admin posts**: unaffected (this only concerns the viewer's own authorship).
- **Private/competition visibility**: unaffected — `RecentPublic` filters `visibility='public'`, so a private
  self-post never leaks (regression-tested).

## Regression tests (tests/application/social_foundation_test.go)
- `TestOwnPublicPostAppearsInGlobalFeed` — own public post appears exactly once in Global.
- `TestOwnPrivatePostStaysOutOfGlobalFeed` — private self-post never enters the public fill.
- Existing feed proofs (mandatory agent inclusion, agent priority, following isolation, query-time, mute)
  still pass — no regression.

## Client consequence
The composer's optimistic `prepend` is now consistent with the authoritative refresh (the post is in both),
eliminating the "appears then disappears" contradiction. Profile▸Activity independently guarantees recovery.
