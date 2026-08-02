# FEATURE-SEARCH-V1 — Security (Stage 1 + Stage 2)

## Boundary & authentication
Client → Gateway (`requireAuth`, JWT) → internal Social `/search/*` (gateway-only port).
The browser/app NEVER reaches Social directly. Identity is server-derived: the Gateway
forwards the verified user as `X-User-Id`; a client can never assert another user id.
Search history is scoped to that verified id in EVERY query ⇒ one user cannot read
another's history.

## Moderation & visibility (the feed's split, reused)
- **Social** enforces what it owns: posts `visibility='public' AND deleted_at IS NULL`;
  agents `active=TRUE`; competitions `active=TRUE`. Hidden/private content never enters
  the result set at the source.
- **Gateway** applies the SAME `ViewFor` lens the feed uses (`searchModerationLens` →
  `moderation.Service.ViewFor`): banned/suspended users (`AuthorHidden`), admin-hidden
  posts (`PostHidden`) and hidden post AUTHORS are dropped from results
  (`applyLens`, tested). Filtering may shrink a page below `limit` — the same honest
  behaviour as the feed. Fail-open on a lens error (read path), matching the feed.
- Blocked users: `ViewFor` already folds the viewer's blocks into hidden authors.

## AppSec (input validation)
- Query: 2..120 runes, trimmed/normalized. LIKE metacharacters (`% _ \`) escaped from
  user input before any pattern is composed (`EscapeLike`, wildcard-abuse test) — no
  wildcard injection, no `%%` catch-all abuse.
- Posts FTS uses `websearch_to_tsquery('simple', $1)` — user text is PARSED by Postgres,
  never interpolated into SQL.
- Cursors: ≤512 bytes, base64url+JSON validated, category-tagged (cross-category replay →
  400), id required; numeric fields parsed with explicit error handling.
- Limit clamped 1..50; UUIDs cast via `::uuid` params. All SQL parameterized — no string
  concatenation of user data anywhere.
- Upstream body cap 1 MiB per category; response never echoes internal host/error detail
  to the client (canonical `detail` codes only).

## Abuse / DoS controls
- **Per-user rate limit** (30 searches / 10s / user, fixed window; limiter map bounded).
  Rejections → 429 + `search_rate_limited_total` metric.
- **Global timeout** on `/all` (4s) and per-category (4s); expiry cancels all in-flight
  upstream calls (context propagation) — no orphan goroutines (WaitGroup join, tested).
- **Per-user cache** keyed by user|category|query|cursor|limit (sha256) — never shared
  across users; bounded size; TTL 30s; partial `/all` responses not cached.
- **Cancellation**: client disconnect propagates via request context to every worker.

## No leakage
- No internal Social DTOs, host names, SQL, or stack traces reach the client.
- No fabricated entities: teams/players are `blocked` (not queryable); competitions get a
  null deep link rather than an invented route; trending is `UNAVAILABLE`.
- API key / credential surface: none (search adds no external provider).

## Observability (security-relevant)
`search_rate_limited_total`, `search_partial_responses_total`, `search_upstream_timeouts_total`,
`search_cancelled_total` — feed anomaly detection + the future Console.
