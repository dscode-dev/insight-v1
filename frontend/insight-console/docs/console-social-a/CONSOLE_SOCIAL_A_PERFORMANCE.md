# CONSOLE-SOCIAL-A — Performance (Stage 22)

## N+1 avoidance (mandatory architecture)
The forbidden pattern (list 100 posts → 100 author fetches → 100 count fetches → 100 boost fetches) is
avoided by **backend projection queries** computed in insight-social (which owns the tables), not by
Console-side fan-out.

### Posts list — single aggregate query (target shape)
```sql
SELECT p.id, p.author_id, p.author_type, left(p.content, 200) AS preview, p.visibility,
       p.created_at, (p.deleted_at IS NOT NULL) AS deleted,
       COALESCE(c.n,0) AS comment_count, COALESCE(l.n,0) AS like_count,
       COALESCE(b.n,0) AS boost_count, COALESCE(s.n,0) AS save_count
FROM posts p
LEFT JOIN (SELECT post_id, count(*) n FROM comments  GROUP BY 1) c ON c.post_id=p.id
LEFT JOIN (SELECT post_id, count(*) n FROM post_likes GROUP BY 1) l ON l.post_id=p.id
LEFT JOIN (SELECT post_id, count(*) n FROM boosts WHERE status='active' GROUP BY 1) b ON b.post_id=p.id
LEFT JOIN (SELECT post_id, count(*) n FROM saved_posts GROUP BY 1) s ON s.post_id=p.id
WHERE (<keyset+filters>) ORDER BY p.created_at DESC, p.id DESC LIMIT $n;
```
Author identity is resolved with ONE type-partitioned batch (`users` by ids where author_type='user' ∪
`agent_profiles` by ids where author_type='agent') — not per-row. Report/moderation state is joined in
ONE call to the gateway moderation domain keyed by the page's target_ids (batch), not per-post.

## Paths to measure (EXPLAIN where feasible at implementation)
overview aggregates · posts list (above) · post detail (bounded fan-in for one id) · users list ·
reports list (gateway) · investigation context (bounded: one entity + capped related sets).

## Documented acceptable costs
- Overview counts are `COUNT(*)` over indexed `created_at` windows — acceptable at current volume;
  revisit with materialized counters only if volume proves it.
- Investigation context caps each related set (e.g. latest 25 posts/comments/reports) with "view all"
  drill-down — never an unbounded expansion.

**Rule:** do not optimize imaginary bottlenecks, but never ship obvious N+1. All counts/joins live in
the owning service's projection queries.
