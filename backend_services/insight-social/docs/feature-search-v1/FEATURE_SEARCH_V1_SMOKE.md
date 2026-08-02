# FEATURE-SEARCH-V1 — Post-Deploy Smoke (operator-run)

Authenticated as a real test user. $B=https://insight-api.konohalabs.com.br, $TOK=access token.
Never paste secrets; do not log full queries/results in prod.

## Database (Social host, read-only unless noted)
1. Extension: `psql -c "\dx pg_trgm"` → present (created by migration).
2. Indexes: `psql -c "\di ix_posts_search_tsv"` + `\di ix_users_username_trgm` → present.
3. EXPLAIN (Users prefix): `EXPLAIN ANALYZE SELECT id FROM users WHERE lower(username) LIKE 'ney%';`
   → expect a Bitmap Index Scan on `ix_users_username_trgm` (not a Seq Scan) on realistic data.
4. EXPLAIN (Posts FTS): `EXPLAIN ANALYZE SELECT id FROM posts WHERE search_tsv @@ websearch_to_tsquery('simple','gol') AND deleted_at IS NULL AND visibility='public';`
   → Bitmap Index Scan on `ix_posts_search_tsv`.

## API (curl via Gateway)
5. Capabilities: `curl $B/v1/search/capabilities -H "Authorization: Bearer $TOK"` →
   `enabled:[users,agents,communities,competitions,matches,posts]`, `blocked:{teams,players}`, `trending:"UNAVAILABLE"`.
6. Six categories: `for c in users agents communities competitions matches posts; do curl -s "$B/v1/search/$c?q=fla&limit=5" -H "Authorization: Bearer $TOK" | jq '.items|length'; done`.
7. All: `curl "$B/v1/search/all?q=fla" -H "Authorization: Bearer $TOK" | jq '{n:(.items|length), partial, failed:.failed_categories, cursors:(.cursors|keys)}'`
   → items sorted by normalized_score; per-category cursors; partial=false when healthy.
8. Partial: stop insight-social's community path (or induce one category failure) → `/all` returns `partial:true` + `failed_categories:["communities"]`, other categories still populated. **Never `[]`**.
9. Pagination: take a category `next_cursor`, refetch with `&cursor=…` → new page, no duplicate ids across pages.
10. History: run a first-page search, then `curl $B/v1/search/history … | jq '.items[].query'` → your normalized query present. `curl -X DELETE $B/v1/search/history …` → `{cleared:true}`; re-GET → empty.
11. Moderation: an admin-hidden post / banned user must NOT appear in `/v1/search/posts` or `/users` (reuses feed ViewFor). Verify with a known-hidden fixture.
12. Rate limit: fire >30 searches in 10s for one user → 429 `search_rate_limited`.
13. Deep links: every card `deep_link` matches a real route (`/users/`, `/agents/`, `/hub/community/`, `/live/match/`, `/post/`); competition cards have `deep_link:null`.

## App
14. Open Search (Explorar). Tabs shown = All + the 6 enabled (derived from capabilities).
15. **No Teams / Players tabs**; no "Trending" section.
16. Type "fla": debounce → results; switch tabs preserves the typed query.
17. Scroll a category → pagination loads more, no dup rows; a page failure keeps loaded items.
18. Partial: with an induced category failure, All shows results + the discreet "incompletos" banner (not blank).
19. Offline (airplane mode) → offline state + retry (query preserved).
20. Tap a user/agent/community/post card → detail opens; press back → **query, tab, results and scroll preserved** (no re-search).
21. Tap a competition card → non-navigable (informative), no crash.
22. Recent searches appear on empty query; select one re-runs it; "Limpar" clears history.
23. A11y: TalkBack reads result count + card labels; tab selected state announced; clear-search / clear-history labeled.
