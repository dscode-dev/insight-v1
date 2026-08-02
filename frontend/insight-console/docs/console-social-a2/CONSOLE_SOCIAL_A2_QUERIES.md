# CONSOLE-SOCIAL-A2 — Query Model & Performance

## No N+1 (service-owned projections + batched resolution)
- Comments list: one query; author resolved via LEFT JOIN users ∪ agent_profiles on
  (author_type,author_id); reply_count as correlated subquery; parent post preview joined.
- Communities: member/moderator counts as correlated subqueries in one statement.
- Community detail: identity + 2 bounded member queries (recent + moderators), capped 20.
- Relationships: 3 bounded queries (followers/following/memberships), capped 100 each — batched, not
  per-relationship.
- Boosts: single query + post preview join.
- Timeline: one UNION query (entity-scoped), capped by limit.
- InvestigationService: composes ≤6 adapter calls concurrently (bounded), each a bounded projection —
  no browser fan-out, no per-row calls.

## Pagination / safety
Keyset cursor (created_at,id) on comments/boosts; bounded lists (limit≤200) on communities/
relationships/members. Filters whitelisted + typed (author_type enum, status enum, UUID-validated
ids); invalid values ignored (safe 200); invalid ids → 400. Parameterized SQL only; sort fixed to
created_at DESC (no order-by injection). No SELECT *.

## Migrations / indexes
**None.** All new queries hit existing indexes (ix_comments_post_created / ix_comments_parent /
ix_posts_author_created / relationships PK + actor). Likely-heavy paths (comments observatory,
relationships, community detail, investigation, timeline) are bounded + index-backed at current
volume. Add a `boosts(status, created_at DESC)` index only if a future EXPLAIN shows a seq scan on a
large boosts table (documented, not added speculatively).
