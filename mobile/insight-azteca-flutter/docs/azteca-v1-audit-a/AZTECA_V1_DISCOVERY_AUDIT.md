# AZTECA V1 — Explore & Search Readiness (Stage 5)

## Current state (CONFIRMED)
`/search` and Explore are the SAME screen (`lib/features/search/search_screen.dart`, AppBar "Explorar").
- No search service, no `/v1` call, no provider. Debounced text field only.
- Empty query → `_Discovery()` (static discovery content); non-empty query → `_NoResultsYet()`.
⇒ **Search returns NO results for any query. Explore is a static/decorative shell. SUPERFICIAL.**
Unified Search is confirmed backlog (sprint item 13); Communities discovery is separate (Stage 9).

## Backend discovery capability matrix (evidence-based)
| Entity | Backend owner | Search endpoint | List endpoint | Detail endpoint | Pagination | Filter | Azteca integration | V1 recommendation |
|---|---|---|---|---|---|---|---|---|
| Users | Social (via Gateway) | ❌ none | partial (`/v1/users/{id}` get; no list-search) | ✅ `/v1/users/{id}` | — | — | profile links only | needs a user search endpoint |
| Agents | Social | ❌ none | ✅ `/v1/agents` | ✅ `/v1/agents/{id}` | list is small/full | active-only | READY to surface (browse, not search) | V1: agent browse |
| Communities | Social/Hub | ❌ none | `/v1/hub/bundle` (mock) | `/v1/hub/communities/{id}` (mock) | — | segment | mock | depends on COMMUNITIES-A |
| Teams | (competition/hub) | ❌ | partial (onboarding teams) | ❌ | — | — | onboarding only | POST-V1 unless trivial |
| Players | none found | ❌ | ❌ | ❌ | — | — | none | POST-V1 |
| Competitions | Social/competition | ❌ | ✅ `competition_service` | ✅ | — | — | onboarding + highlights | V1: browse |
| Matches | live/context (gated) | ❌ | gated (`/v1/live/*` absent) | gated | — | — | gated | POST-V1 / LIVE-RADAR |
| Posts | Social | ❌ none | feed only | ✅ `/v1/posts/{id}` | cursor | — | feed/detail | needs post search endpoint |

## Finding
There is **no unified search backend** today. A production Search requires new Gateway/Social search
endpoints (users, agents, communities, competitions, posts) with pagination + a typed multi-entity result
DTO. None exist. The Explore screen can be made real cheaply for **browse** (agents, competitions,
trending) using existing list endpoints, without a search backend.

## AZTECA-SEARCH-A scope (defined here; do NOT build now)
1. Backend prerequisite: multi-entity search endpoint(s) `GET /v1/search?q=&types=&cursor=` owned by Social/
   Gateway (users/agents/communities/competitions/posts). This is a BACKEND sprint dependency — Search-A is
   BLOCKED on it.
2. Flutter: real `SearchService`, `searchProvider` (debounced, paginated), typed `SearchResult` union,
   recent searches (local), entity result cells reusing existing detail routes.
3. Interim (SEARCH-A phase 1, no backend): convert Explore into a real BROWSE hub (agents list, competitions,
   trending highlights) using existing endpoints — ship value while the search backend is built.
