# FEATURE-SEARCH-V1 — Architecture (Stage 1: insight-social)

## Layering (mirrors post/feed)
```
Gateway (Stage 2)                           ← auth, moderation lens, rate limit, "All" aggregation
   ↓ internal HTTP (X-User-Id, gateway-only port)
httpapi/search.go                           ← typed handlers, explicit error mapping
   ↓
application/search.Service                  ← normalize, clamp, cursor decode, history side-effect
   ↓
domain/search                               ← categories, cursors, validation, Repository port
   ↓
postgres/searchrepo                         ← per-category SQL: CTE bucket ranking + keyset
```

## Category independence (directives 1–3)
Each of the six categories has its OWN query path, OWN entity-specific ranking and OWN typed cursor
(category-tagged; cross-category replay → 400). There is **no giant "All" SQL** — multi-category aggregation
is the Gateway's job (Stage 2), which will return a per-category cursor structure.

## Teams / Players — BLOCKED_BY_DOMAIN (binding architectural directive)
> The planned presence of Teams and Players in the discovery experience does not imply those domains exist.
> They may only be activated when there is a canonical source of truth, persistent identity, public
> contracts, ingestion, and their own detail routes. Until then they remain BLOCKED_BY_DOMAIN.

Enforcement in this stage: no teams/players table, no artificial IDs, no entities derived from match
strings, no persisted aliases, no endpoints pretending canonicity, no deep links to nonexistent entities.
`home_team_name`/`away_team_name` appear ONLY inside Match results as match context (`MatchResult` doc
comment + handler comment restate this). `/search/capabilities` reports both as blocked with reasons.

## Capabilities contract (client tabs derive from backend, never hardcoded)
`GET /search/capabilities` → `{enabled: [users, agents, communities, competitions, matches, posts],
blocked: {teams: …, players: …}, trending: "UNAVAILABLE"}`. Trending stays UNAVAILABLE until real query-log
volume + a documented aggregation rule (time window, privacy) exist — never seeded/editorial/fabricated.

## Pagination
Keyset only (no OFFSET). Every query fetches limit+1: overflow row proves a next page; the cursor encodes
the **full sort key of the last kept row** (`{c: category, b: bucket, s1[, s2], id}`, base64url JSON).
Numeric tiebreakers ride as strings (floats via strconv 'g'/-1 → bit-exact round-trip). Stable ordering ends
in the unique id ⇒ no duplicated/skipped rows between pages.

## Visibility & moderation (split mirrors the feed)
- Social enforces what it OWNS: posts `visibility='public' AND deleted_at IS NULL`; agents `active=TRUE`;
  competitions `active=TRUE`.
- Gateway (Stage 2) applies its moderation lens (`ViewFor`: admin-hidden content + banned/suspended
  authors + viewer blocks) exactly as it post-filters the feed. Documented here so Stage 2 cannot skip it.

## Search history (private per user)
`search_history(user_id, query UNIQUE per user, created_at)` — normalized queries (trim/lower/collapse),
dedupe via upsert (re-search refreshes recency), pruned to 20 on every write, `DELETE /search/history`
clears. Recorded only on FIRST pages (pagination is not a new search), best-effort (never fails the
search). All access scoped by the gateway-verified `X-User-Id` — one user can never read another's history.

## Indexing (migration 00010, additive)
- Posts FTS: STORED generated `search_tsv = to_tsvector('simple', content)` + GIN. Config `'simple'` is
  deliberate: language-neutral, no stemming surprises, deterministic `ts_rank`. Query via
  `websearch_to_tsquery('simple', $1)` — user syntax is parsed safely, never interpolated.
- `pg_trgm` (TRUSTED extension, PG≥13 — database owner can CREATE) + GIN trigram indexes on
  users(username, display_name), agents(name), communities(name, topic), competitions(name),
  matches(home/away_team_name) — serving the "contains" tier.
- If a target cluster lacked pg_trgm privileges the migration would fail loudly at deploy (goose aborts) —
  preferred over silently missing indexes; the operator runbook (Stage 3) will note this precondition.

## AppSec
Parameterized SQL only; LIKE metacharacters (`% _ \`) escaped from user input (`EscapeLike`, wildcard-abuse
test); query bounds 2..120 runes; limit clamp 1..50; cursor ≤512 bytes, JSON-validated, category-tagged,
id-required; UUID casts via `::uuid` params; timeouts owned by the Gateway (Stage 2) + pgx context.

## Performance notes / EXPLAIN
No local Postgres was available in this environment — EXPLAIN plans are pending and belong to the deploy
smoke (documented, not fabricated). Expected plans: prefix tiers hit the trigram GIN (trgm also accelerates
LIKE prefix/contains); posts hit the tsvector GIN; history uses `(user_id, created_at DESC)`. Follower
count/EXISTS subqueries run per returned row (≤51) on the `relationships` PK/indexes.

---

# Stage 2 — insight-gateway (Search Orchestrator)

The Gateway is the platform's Search Orchestrator, NOT an HTTP proxy. Package
`internal/interfaces/http/searchbff`.

```
Client → Gateway /v1/search/*  (requireAuth, per-user rate limit, per-user cache)
   ↓  SearchAggregator (/all only): parallel fan-out, ONE correlation id, global timeout
   ↓  SocialClient: typed per-category fetch → Gateway public DTO mapping
   ↓  internal Social /search/*  (X-User-Id, X-Request-Id reused)
   ↑  moderation ViewFor lens applied to results (users + posts)
   → canonical response (partial semantics, per-category cursors, deep links)
```

## Components
- **dto.go** — Gateway-owned public contract (Card + Public{User,Agent,Community,
  Competition,Match,Post}); deep-link builder; capabilities response with
  `temporarily_unavailable`.
- **client.go** — internal Social client; generic `fetchCategory[T]` maps Social JSON →
  public DTO at compile time (no leak); reuses the inbound correlation id + forwards
  X-User-Id on every call.
- **aggregator.go** — the ONLY "All" view. Parallel goroutines over the 6 categories,
  `sync.WaitGroup` join (no orphans), global `context.WithTimeout`, reciprocal-rank
  normalized_score, deterministic merge, honest partial + failed_categories.
- **cache.go** — per-user TTL cache keyed by user|category|query|cursor|limit (sha256).
- **metrics.go** — Prometheus on the shared registry (10 series).
- **handlers.go** — auth → rate limit → cache → orchestrate → moderation lens →
  canonical response/errors; capabilities enrichment; history proxy.

## Ownership boundary
Social knows individual categories only. "All" aggregation, normalized score, the public
contract, caching, moderation filtering and deep links all live in the Gateway. Adding a
future category (e.g. teams once canonical) is: Social endpoint + one public DTO + one
fetcher registration — no orchestrator rewrite.

## Not in Stage 2 (belongs to Stage 3 / future)
Client UI (Azteca hub). Redis-backed shared cache (interface is ready; in-memory suffices
single-instance). Trending (still UNAVAILABLE — no data). Teams/Players (still
BLOCKED_BY_DOMAIN).
