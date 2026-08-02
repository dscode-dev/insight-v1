# CONSOLE-SOCIAL-A — Query Model, Pagination & Safety (Stage 21)

## Pagination
- **Keyset (cursor) pagination** on `(created_at DESC, id DESC)` for all list reads — matches existing
  social indexes (`ix_posts_author_created`, `ix_posts_public_created`, `ix_comments_post_created`) and
  the SECURITY-A1 audit-read pattern. Cursor = base64url(`created_at|id`). Bounded page size (default
  50, max 200). No offset for high-cardinality tables.
- Deterministic ordering always includes the tiebreaker `id`.

## Filter/sort safety
- Filters are a **fixed whitelist** per endpoint (author_type∈{user,agent,admin}, author_id (uuid),
  since/until (timestamptz), boosted (bool), status (enum), post_id (uuid)). Values validated/typed;
  parameterized SQL only. **No arbitrary order-by, no raw filter language, no client SQL.**
- Sort fields whitelisted (created_at only for V1) — no order-by injection.

## Indexes (reuse; additive only if justified)
Existing indexes cover the core list paths (posts by author+created / public+created / author_type;
comments by post+created and parent; boosts by post; likes by user). New composite indexes are added
**only** if an EXPLAIN on a real operator list query shows a seq scan on a large table — e.g. a
`boosts (status, created_at DESC)` index for the boosts workspace. Any migration is additive
(`CREATE INDEX IF NOT EXISTS`), tested on fresh + existing schema.

## No entire-table loads
High-cardinality tables (posts, comments, post_likes, boosts, saved_posts) are never fully loaded into
the Console — always paginated server-side with bounded pages.
