# FEATURE-SEARCH-V1 — Final Vertical Verdict

## CODE READINESS: **READY** (all 3 stages)
## OPERATIONAL STATUS: **NOT_DEPLOYED — USER-OPERATED DEPLOYMENT REQUIRED**

Per the certification rule, the vertical READY certificate is granted only AFTER the operator deploys +
smoke-passes. Until then this is CODE READY / NOT_DEPLOYED.

## What shipped (the first complete vertical under the new architecture)
Search went from a decorative shell (query → `_NoResultsYet()`) to a real unified discovery platform where
Social, Gateway and Azteca evolve as one capability.

- **Stage 1 — Social**: migration 00010 (posts FTS tsvector+GIN, pg_trgm trigram indexes, search_history);
  search domain + deterministic per-entity ranking + per-category keyset cursors; private history; typed
  internal HTTP; visibility enforced. 6 real categories.
- **Stage 2 — Gateway**: `searchbff` Search Orchestrator (NOT a proxy) — Gateway-owned public DTOs (compile-
  time mapping, no Social leak), `/all` aggregation with reciprocal-rank normalized_score + honest partial +
  per-category cursors, per-user cache, one correlation id across the fan-out, cancellation with no orphan
  goroutines, moderation ViewFor lens, per-user rate limit, backend deep links, 8 Prometheus metrics,
  capabilities enrichment (temporarily_unavailable).
- **Stage 3 — Azteca**: Search Hub — tabs derived from `/v1/search/capabilities` (never hardcoded);
  SearchService (CancelToken) + SearchController (debounce 300ms, out-of-order epoch guard, per-category
  cursor pagination + dedupe, page-failure preserves items); 6 typed result cards; deep-link navigation
  validated against real routes (competition = honest non-navigable); recent-history discovery; explicit
  states (discovery/debouncing/loading/success/empty/partial/loadingMore/unavailable/offline/timeout/
  unauthorized/error); a11y; state preserved on detail return.

## Honesty upheld across all stages
- **Teams / Players: BLOCKED_BY_DOMAIN** — no table, no fake id, no derived-from-match entity, no endpoint,
  no tab, no "Em breve". Match team names stay match context only.
- **Trending: UNAVAILABLE** — never fabricated from seeds/editorial lists.
- **Competitions**: null deep_link (no client route) → non-navigable, not a fabricated route.
- **partial** never becomes silent success or `[]`.
- No internal Social contract reaches Flutter; the client never reproduces ranking or builds routes.

## Deep-link contract verification
All Gateway deep_links (`/users/`, `/agents/`, `/hub/community/`, `/live/match/`, `/post/`) match routes the
Azteca router actually registers (grep-confirmed) — **no Gateway contract fix was required**, and the client
validates each link before navigating (no silent translations).

## Validation
- Social: go build/vet/test green; searchrepo + domain + service tests. diff clean.
- Gateway: go build/vet/test green; searchbff tests (score determinism, partial, all-failed, cancellation-
  no-orphans, per-user cache, deep links, rate limit, moderation, correlation). diff clean. Prior fixes preserved.
- Azteca: `flutter analyze` clean; `flutter test` **115 passed / 0 failed** (+ search models/controller suites:
  capabilities→tabs, no teams/players, debounce, out-of-order, partial, pagination+dedupe, page-failure
  preservation, deep-link honesty). diff clean.

## Version lineage
Deployed gw 0.1.13 / social 0.1.8 → code-ready **social 0.1.11**, **gateway 0.1.16**, Flutter Search Hub build.
Deploy order: migration 00010 → social → gateway → Flutter.

## Remaining blockers before the READY vertical certificate
Only the operator-run deploy + smoke (DEPLOY.md + SMOKE.md). No code blockers.
Non-blocking future work (documented, not faked): Teams/Players canonical domains; Trending once query-log
volume + aggregation/privacy policy exist; competition detail route; post <b>-highlight rendering;
Redis-backed shared cache (interface ready).
