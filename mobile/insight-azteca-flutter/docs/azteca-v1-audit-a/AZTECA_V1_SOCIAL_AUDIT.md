# AZTECA V1 — Social Flow Forensic Audit (Stage 2)

## Posts — create → persist → feed
- Composer `POST /v1/posts` via `social_service.createPost` (visibility default `public`; only `public`
  enabled in `composer_screen.dart:63-69`). **Persistence is REAL** — the post is written to Social.
- On success: `feed_provider.prepend(post)` (optimistic, post-success ONLY — `feed_provider.dart` comment
  is accurate; never local-only).
- Feed read: `/v1/feed/global` (default) / `/v1/feed/following`; cursor pagination + pull-to-refresh +
  infinite scroll all REAL and correct.

### ⚑ ROOT CAUSE — "post appears then disappears after refresh"
**NOT a persistence failure. It is feed-query semantics vs optimistic UI.**
Traced to `insight-social/internal/application/feed/service.go`:
- `Global()` assembles: (1) followed agents' posts, (2) followed users' posts, (3) **public fill**.
- The public fill EXPLICITLY excludes the viewer's own posts:
  `service.go:126` → `if seen[...] || item.Post.AuthorID == userID || muted[...] { continue }`.
- Followed-authors paths never include self (a user doesn't follow themselves).
⇒ The viewer's own just-created post is **by design absent from `/v1/feed/global`**. The optimistic
`prepend` shows it; the authoritative refresh correctly evicts it. The post is fully persisted and is
retrievable via `GET /v1/users/{id}/posts` (the Profile ▸ Atividades tab, which works).
**Classification: optimistic-UI vs feed-semantics mismatch (backend product decision), NOT a bug in
persistence, ranking, cursor, cache, or moderation.** Fix boundary (later sprint, NOT now): either
include the author's own recent posts in Global, OR route post-publish confirmation to Profile ▸ Atividades,
OR add an "own posts" surface. This is exactly the reliable-activity-surface need (sprint point 6) — already met.

## Post detail, comments, replies
- `/post/:postId`: `getPost`+`listComments`+`createComment` REAL. Reply target/bounded nesting handled
  by backend (depth CHECK 1,2). `feed_provider.setCommentCount` reconciles the feed card's reply count
  from a backend-sourced count — real reconciliation. Comment author identity resolved server-side.
- Risk: comment pagination/collapse depth and optimistic-comment rollback need live verification (PARTIAL).

## Save / Boost / Like
- `save/unsave`, `boost/unboost`, `like/unlike` REAL (`social_service` + `interactionStates` hydration in
  `feed_provider._hydrateInteractions`). State hydrated per feed page via `POST /v1/posts/interaction-states`;
  merged into `interactionSnapshotsProvider`. Saved posts list via `/v1/me/saved-posts` (real, self-joined DTO).
- Hydration-after-restart: interaction state is re-fetched per feed page load ⇒ survives restart. Counter
  semantics + failure rollback for boost/save need live verification (PARTIAL but architecturally sound).

## Composer UX (document only — DO NOT redesign now)
`composer_screen.dart` is a full-screen ComposerScreen (COMPOSER-A). Defects to fix in AZTECA-POSTS-B:
- TextField `contentPadding` at `:352` is a fixed `fromLTRB` — audit for insufficient internal padding &
  cursor placement (sprint observation 2). `maxLines: null` (grows) is correct; verify scroll for long posts.
- Verify: autofocus/focus timing, keyboard + safe-area interplay, bottom CTA overlap, duplicate-submit guard
  (disable CTA while pending — `submit()` sets pending but confirm re-entrancy lock).
- Draft preservation exists (`composer_draft_store`). No attachment architecture (text-only) — GIF needs Stage 8.
- Target quality: Instagram/Threads-grade field ergonomics (padding, caret, growth, dismissal) — no literal copy.

## Verdict
Social **core is the strongest domain**: create/read/detail/comment/like/save/boost are real, persisted,
paginated. The two real issues are (a) the own-post/feed-semantics UX mismatch and (b) composer field ergonomics.
