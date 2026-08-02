# FEATURE-SEARCH-V1 — Stage 0 Audit (evidence-based, no code written)

Repos inspected: insight-azteca-flutter, insight-gateway, insight-social. Atlas read-only/untouched.

## Headline: Search does not exist anywhere. There is nothing to extend — only to build.

## 1. Azteca (client)
- `lib/features/search/search_screen.dart` is the ONLY search file. AppBar "Explorar".
- Behaviour: empty query → `_Discovery()` (static); **any non-empty query → `_NoResultsYet()`**. It is
  structurally incapable of returning a result.
- `grep searchProvider|SearchService|/v1/search lib/` → **no matches**. No service, no provider, no DTO, no
  network call, no pagination, no cancellation, no cache, no history.
- Debounce: the ONLY real piece — a 250ms `Timer` debounce on the text controller (`search_screen.dart`).
- Classification: **SUPERFICIAL / decorative**. Not a stub of a real thing — a shell.

## 2. Gateway
- `grep '"/v1/search'` on `cmd/gateway/main.go` → **no matches**. No search route, no search BFF, no
  aggregation, no search rate-limit/cache/timeout.
- Classification: **ABSENT**.

## 3. Social
- No search route in `cmd/social/main.go`. No search domain/service/repository. No ranking. No cursor search.
- **No search indexing of any kind**: no `tsvector`, no `to_tsquery`/`websearch_to_tsquery`, no `pg_trgm`, no
  GIN/GIST index, no ILIKE search query anywhere in `migrations/` or `internal/infrastructure/postgres/`.
  (A naive grep appears to hit "gin" — that is a false positive: the substring inside `-- +goose StatementBegin`.)
- **No `search_history` / `recent_search` table.**
- Classification: **ABSENT**.

## 4. Entity domain reality (what could be searched at all)
Tables that exist: `users, agent_profiles, agent_state_events, communities, community_members, competitions,
matches, posts, comments, post_likes, saved_posts, boosts, relationships, discussions, discussion_messages,
reactions, reputation_events, sentiment_snapshots, signals, user_preferences`.

| Requested category | Backing domain | Verdict |
|---|---|---|
| **Users** | `users` (username UNIQUE, display_name, initials, reputation, tier, avatar) | ✅ REAL — searchable |
| **Agents** | `agent_profiles` (slug, name, bio, active, verified) | ✅ REAL — searchable |
| **Communities** | `communities` (slug, name, topic, kind, member_count) + `community_members` | ✅ REAL — searchable |
| **Competitions** | `competitions` (slug, name, short_name, region, is_active) | ✅ REAL — searchable |
| **Matches** | `matches` (team names denormalized, kickoff_ts, state, competition_id) | ✅ REAL — searchable |
| **Posts** | `posts` (content VARCHAR(4000), visibility, deleted_at) | ✅ REAL — searchable (needs FTS index) |
| **Teams** | ❌ **NO canonical team entity.** Teams exist only as DENORMALIZED strings on `matches` (`home_team_id VARCHAR(48)`, `home_team_name VARCHAR(80)`, `home_team_short`, `home_team_color`). There is no `teams` table, no team id domain, no team detail route. | ❌ **BLOCKED_BY_DOMAIN** |
| **Players** | ❌ **NO players domain at all.** No table, no DTO, no endpoint, anywhere. | ❌ **BLOCKED_BY_DOMAIN** |

This corroborates AZTECA-PROFILE-B, which deferred `favorite_team` precisely because *"a free-text team would
conflict with canonical team identity"* — the canonical team relation still does not exist.

## 5. Supporting capability reality
| Capability | State |
|---|---|
| Ranking | **ABSENT** (nothing to rank) |
| Cursor pagination for search | **ABSENT** (feed has keyset cursors — a reusable *pattern*, not a search impl) |
| Debounce | PRESENT (client, 250ms) — the only existing piece |
| Cancellation | **ABSENT** (no in-flight request to cancel) |
| Cache | **ABSENT** |
| Search history | **ABSENT** (no table, no client store) |
| Trending searches | **ABSENT** — and there is **no query-log data** to derive it from ⇒ must be classified unavailable, never fabricated |
| Moderation filtering for search | N/A — but the mechanism exists and MUST be reused (`moderation.ViewFor`: hidden posts/comments + non-active authors; `EnsureCanAct`) |
| Search perf | N/A (no query exists to measure) |

## 6. Reusable assets (do NOT rebuild)
- **Keyset/cursor pagination pattern** — `feedrepo` (`created_at, id` keyset + base64 cursor encode/decode).
- **Moderation lens** — Gateway `moderation.ViewFor` (hidden content + non-active authors) — search MUST apply it.
- **Gateway BFF conventions** — `requireAuth`, `route(...)` + metrics instrumentation, `X-User-Id` forwarding to
  the internal Social HTTP port, canonical error mapping.
- **Client conventions** — dio `getJson` + interceptors, Riverpod providers, `FeedItem` canonical post card
  (reuse for Post results), agent/user/community detail routes for deep links.
- **Intelligence primitives** (INSIGHTS-A) for any metric shown on result cards.

## 7. Scope consequence (must be decided before Stage 1)
6 of 8 categories are implementable against real domains. **Teams and Players are not** — delivering them
would require inventing canonical entities (new tables, ingestion/source of truth, ids, detail routes), which
is a separate domain sprint and is explicitly forbidden by this sprint's own rule: *"If a capability does not
exist, classify it as absent… Never fabricate."*

Recommended: implement **Users, Agents, Communities, Competitions, Matches, Posts**; classify **Teams** and
**Players** as **BLOCKED_BY_DOMAIN** with the canonical-entity requirement documented. Trending →
**unavailable** (no query-log data).

## 8. Build required (nothing pre-exists)
- **Social**: migration (pg_trgm + GIN indexes on users/agents/communities/competitions/matches; FTS tsvector
  + GIN on posts; `search_history` table) · search domain/repo/service (deterministic ranking, keyset cursors)
  · internal HTTP handlers.
- **Gateway**: `/v1/search` BFF (auth, per-user rate limit, timeouts, cache, canonical errors, correlation id,
  moderation `ViewFor` filtering, aggregation for "All").
- **Azteca**: SearchService + providers (debounce/cancel/paginate/cache) · Search Hub (tabs, states, history)
  · 6 result cards + deep links · a11y · tests.
- **Docs/tests** across all three repos.
