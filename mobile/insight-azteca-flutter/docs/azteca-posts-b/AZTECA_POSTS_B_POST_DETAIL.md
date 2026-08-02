# AZTECA-POSTS-B — Post Detail Consistency

## Renderer reuse (Stage 6)
The canonical `FeedItem` post card is now shared across **Feed**, **Public profile**, and **Own Activity**
(this sprint aligned Own Activity to it). Post Detail (`/post/:postId`, `post_thread_provider`) renders the
post header + content + action bar + comments; it reuses the same identity/action primitives. There are no
longer three divergent own-vs-public post widgets for the list surfaces.

## State reconciliation (existing, verified — SOCIAL-A/SOCIAL-B)
- **Like**: optimistic + `interactionSnapshotsProvider`; hydrated per feed page via
  `POST /v1/posts/interaction-states` → survives restart; detail and feed converge on backend state.
- **Comment**: `feed_provider.setCommentCount` reconciles the feed card's reply count from a backend count.
- **Save/Boost**: backend-persisted; hydrated from `interaction-states` after restart (SOCIAL-B) — not
  client-only.
- **Deleted/hidden**: backend soft-delete/moderation (`deleted_at`, ViewFor) — Flutter renders whatever the
  authoritative read returns; no moderation semantics invented client-side.

## Not changed
No Post Detail redesign. No new moderation UI. Attachment rendering is a no-op until media lands (deferred).
