# FEATURE-SEARCH-V1 — Public API (Stage 2: Gateway Search Orchestrator)

The Gateway OWNS the public discovery contract. Social's internal `/search/*`
shapes never reach the client — each public payload is a Gateway-owned DTO
(`searchbff/dto.go`) mapped from Social at compile time. All routes are
`requireAuth`; the verified user is forwarded to Social as `X-User-Id`; the
inbound `X-Request-Id` is reused across the entire fan-out.

## Envelope: the Card
Every result is a `Card`: `{ entity_type, entity_id, deep_link, normalized_score?, data }`.
- `deep_link` is built by the backend (client never composes routes). Null for
  competitions (no client detail route exists — honest absence).
- `normalized_score` present only in `/all`.
- `data` is the category's public payload (below).

## Per-category — `GET /v1/search/{category}?q=&limit=&cursor=`
Categories: `users agents communities competitions matches posts`. Returns
`{ query, category, items[Card], next_cursor }`. Cursor is opaque + category-tagged
(replaying it on another category → 400). `q` 2..120 runes; `limit` clamped 1..50.

Public `data` payloads (Gateway DTOs): user {id, username, display_name, initials,
accent_color, avatar_url, reputation, tier, followers, is_following, follows_viewer,
mutual} · agent {id, slug, name, avatar, bio, active, verified} · community {id, slug,
name, topic, kind, member_count, accent_color} · competition {id, slug, name,
short_name, region, accent_color, featured, active} · match {match_id, competition_id,
competition_name, home_team{name,short,color}, away_team{…}, kickoff_ts, state,
home_score, away_score} — team objects are match CONTEXT, no entity_id, no deep link ·
post {id, author_id, author_type, author_name, author_avatar, snippet(`<b>` markers),
created_at, like_count, comment_count}.

## Aggregated — `GET /v1/search/all?q=`
The ONLY place "All" exists. Returns `{ query, items[Card sorted by normalized_score],
cursors{category→cursor}, partial, failed_categories[] }`. See CONTRACT_MATRIX for the
normalization strategy. A client "sees more" of one category by calling that category's
endpoint with `cursors[category]`.

## Capabilities — `GET /v1/search/capabilities`
`{ enabled[], blocked{teams,players → reason}, temporarily_unavailable[], trending }`.
The client derives its visible tabs from `enabled`. `temporarily_unavailable` is
Gateway-owned: a category that EXISTS but whose upstream is currently degraded (distinct
from `blocked`, which has no domain). If Social's capability read fails, the six known
categories are reported temporarily_unavailable (contract stays serveable). `trending`
is always `"UNAVAILABLE"` in V1.

## History — `GET | DELETE /v1/search/history`
The Gateway is the ONLY public history contract; the client never learns how Social
persists it. GET → `{ items:[{query, created_at}] }` (private, per verified user).
DELETE → `{ cleared:true }`.

## Errors (canonical)
401 unauthenticated · 429 search_rate_limited · 400 invalid_search_request /
invalid_cursor · 504 search_timeout · 503 search_unavailable (every category failed) ·
502 search_upstream_error · 499 client_cancelled. Aggregated searches degrade to
`partial=true` with `failed_categories` rather than erroring when ≥1 category succeeds.
