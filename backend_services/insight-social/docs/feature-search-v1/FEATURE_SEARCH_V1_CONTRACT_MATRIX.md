# FEATURE-SEARCH-V1 — Contract & Aggregation Matrix (Stage 2)

## Gateway ← Social mapping (no internal leak)
| Category | Social internal | Gateway public DTO | Mapping |
|---|---|---|---|
| users | /search/users | PublicUser | compile-time struct map + mutual = is_following && follows_viewer |
| agents | /search/agents | PublicAgent | direct |
| communities | /search/communities | PublicCommunity | real fields only |
| competitions | /search/competitions | PublicCompetition | direct |
| matches | /search/matches | PublicMatch (+ PublicTeamContext) | team strings = context, no entity |
| posts | /search/posts | PublicPost | snippet passthrough (`<b>`) |
A Social field rename breaks the Gateway mapping's compilation — it can never silently leak.

## normalized_score (deterministic, no AI)
Each category is already deterministically ranked internally by Social (exact→prefix→
contains→domain tiebreakers). Raw per-domain values (reputation vs member_count vs
ts_rank) are NOT comparable, so `/all` derives the score purely from each item's
POSITION in its own domain ranking:

    normalized_score = 1 / (1 + position)   // 0-based → 1.00, 0.50, 0.33, 0.25, …

- Every domain's #1 scores 1.0 ⇒ the best of each category surfaces first (discovery UX),
  then all #2s, etc. (reciprocal-rank interleave).
- Merge order: score DESC → fixed category priority (users, agents, communities,
  competitions, matches, posts) → entity_id. Total order ⇒ same data+query ⇒ same
  response (tested: `TestAll_NormalizedScoreDeterministicMerge`).
- The score is a PRESENTATION-layer function of the domain's own order — it invents no
  relevance and mixes no cross-domain magnitudes.

## Partial responses
`/all` fans out to all six categories. Any category failure ⇒ `partial=true` +
`failed_categories` naming exactly which failed; successful categories still return items.
Only when EVERY category fails is it an error (503) — never a silent `[]`. Partial
responses are NOT cached (a transient failure must not be pinned for the TTL).

## Per-category cursors
`/all` returns `cursors{category→opaque}`. There is no shared "All" cursor — continuation
is per category via that category's endpoint (upholds Stage 1 directive: independent
cursors per type).

## temporarily_unavailable
Gateway-owned capability state for a category that exists but is upstream-degraded.
Lets teams/players/live/radar surface as temporarily_unavailable in the future without
a contract change — distinct from `blocked` (no domain) and `enabled` (working).
