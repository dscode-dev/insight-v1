# AZTECA-POSTS-B — Persistence Trace

## Create → persist (PROVEN correct)
`POST /v1/posts` → gateway `foundation.CreatePost` (write-gated by moderation EnsureCanAct) → social gRPC
`PostServer.Create` → `post.Service.Create` → `repo.InsertPost` (single INSERT into `posts`). Returns the
persisted projection (id, author, content, visibility, created_at). No fanout / no timeline materialization.

## Read-back paths (all real)
- `GET /v1/feed/global|following` → feed.Service (query-time generation).
- `GET /v1/users/{id}/posts` → feed.Service.AuthorPosts (own + public Activity).
- `GET /v1/posts/{id}` → post detail.
Schema: `posts(id, author_id, author_type, content, metadata JSONB, visibility, created_at, deleted_at)`
(migration 00005). Soft-delete via `deleted_at`; all reads filter `deleted_at IS NULL`.

## Transaction boundary
Single-row INSERT is atomic. Read-back is query-time (no eventual-consistency window beyond the DB commit).

## Classification of the disappearing-post issue
**A. FEED_SELF_EXCLUSION** — persistence is correct; the post was excluded from the Global feed query by an
explicit self-post filter (fixed in Stage 1). Verified by: feed/service.go:126, feedrepo RecentPublic
(includes own public posts), and the new regression tests
(`TestOwnPublicPostAppearsInGlobalFeed`, `TestOwnPrivatePostStaysOutOfGlobalFeed`).

## Evidence of persistence (no live mutation performed)
- Code + migration prove the INSERT + read-back.
- Read-only live: `/v1/users/{id}/posts` and `/v1/feed/global` return 401 (registered) on the deployed stack.
- Authenticated create + read-back is provided as a manual smoke (no test account credentials available;
  no production post created).
