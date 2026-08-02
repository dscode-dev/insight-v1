# CONSOLE-SOCIAL-A1 — Query Model & Performance

## No N+1 (service-owned projections)
- Posts list: one query with correlated subquery counts (comments/likes/active-boosts/saves) + author
  resolved via LEFT JOIN users + LEFT JOIN agent_profiles on (author_type,author_id). Author identity
  is NOT fetched per row.
- Users list: aggregate LEFT JOINs (post/comment/follower/following counts) in one statement.
- Overview: a single multi-subquery row.
- Post detail: one post query + one comments query (≤500, batched author resolution) + one boosts query
  — bounded fan-in for a single id.

## Pagination / safety
- Keyset cursor on (created_at, id) — opaque base64url; default limit 50, max 200.
- Filters whitelisted + typed: author_type∈{user,agent,admin}, author_id (UUID-validated), boosted
  (bool), q (ILIKE, parameterized). Invalid values are IGNORED (author_type=DROP → 200, ignored),
  invalid ids → 400. Parameterized SQL only; sort fixed to created_at DESC (no order-by injection).
- Uses existing indexes (ix_posts_author_created / public_created / author_type,
  ix_comments_post_created / parent). No new migration required for A1.

## Live query-plan note
Current volume is small (posts 14, users 1, agents 5). Projections are index-backed; revisit
materialized counters only if volume proves it. EXPLAIN on posts-list at scale is a follow-up.
