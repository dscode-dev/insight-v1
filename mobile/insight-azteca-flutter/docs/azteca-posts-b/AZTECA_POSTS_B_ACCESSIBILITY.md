# AZTECA-POSTS-B — Accessibility & Performance

## Accessibility (publishing surfaces)
- Composer text field carries `Semantics(label: 'Editor de texto da publicação', textField: true)`.
- Post action bar (like/save/boost/comment) uses labeled controls; state is conveyed by icon + label, not
  color alone (design-system primitives).
- Activity/Feed/Detail reuse the same `FeedItem` → consistent semantics + tap targets across surfaces.
- Own Activity now has honest loading/empty/error states with actionable retry (not a blank/color-only cue).
- Item lists use stable keys (`ValueKey(post.id)`) — correct semantics + scroll identity.

## Performance
- Activity/Feed use `ListView.builder` (lazy) with stable keys — bounded rebuild scope.
- Feed pagination + pull-to-refresh unchanged; own Activity paginates via the same `userPostsProvider`
  read (bounded).
- No new heavy widgets introduced. No GIF list memory pressure (GIF deferred).
- Scoped invalidation (create → feed + `userPostsProvider(myId)` only) avoids full-tree rebuilds.

## Not measured / deferred
No profiling was run (no runtime device session in scope). Reduced-motion / GIF alt semantics apply only
once the GIF renderer lands (deferred). Comment-input a11y is unchanged from SOCIAL-A (adequate).
