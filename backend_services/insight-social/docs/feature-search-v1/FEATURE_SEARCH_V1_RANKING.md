# FEATURE-SEARCH-V1 — Ranking (deterministic, per-entity)

No AI. No randomness. Every category orders by `(bucket ASC, entity tiebreakers, id ASC)` — the trailing
unique id makes total order deterministic and cursors stable. Buckets are computed in SQL (CTE `CASE`) from
the normalized, LIKE-escaped query.

## Users — identity-first, then standing
| Bucket | Rule |
|---|---|
| 0 | exact username |
| 1 | username prefix |
| 2 | display-name prefix |
| 3 | contains (username/display name) or exact initials |
Tiebreak: **reputation DESC** (user standing is a user-domain signal), id ASC.

## Agents (active only)
0 exact slug · 1 name prefix · 2 name contains · 3 bio contains. Tiebreak: **name ASC** (alphabetical —
agents are a small curated set; no reputation concept), id ASC.

## Communities
0 exact slug · 1 name prefix · 2 name contains · 3 topic contains. Tiebreak: **member_count DESC** (the
real popularity column; NOT user reputation — directive 3 — and no invented "activity score"), id ASC.

## Competitions (active only)
0 exact slug · 1 name/short-name prefix · 2 contains. Tiebreak: **featured DESC** (real editorial flag used
by the highlights rail), id ASC.

## Matches
0 team-name prefix or short-code exact · 1 contains. Tiebreak: **kickoff_ts DESC** (recency is the match
domain's relevance), match_id ASC. Team names are match context — never Team results.

## Posts (full-text)
`search_tsv @@ websearch_to_tsquery('simple', q)`; order **ts_rank DESC** (lexical relevance), created_at
DESC (recency), id ASC. Snippets via `ts_headline` (`<b>…</b>`, MaxWords=30). Public + non-deleted only.

## Shared properties
- The exact → prefix → contains hierarchy is the cross-category base; secondary factors are strictly
  domain-owned (reputation only for users; member_count only for communities; recency only for matches;
  ts_rank only for posts; editorial flag only for competitions).
- Determinism proof: same data + same query ⇒ same total order (no now()-dependence inside ordering; the
  only time-derived key, kickoff_ts, is stored data).
- Cursors encode the full sort key per category (see ARCHITECTURE), so pagination never reshuffles.
