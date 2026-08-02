# AZTECA-POSTS-B — Final Verdict

## CODE READINESS: **READY** (mandatory publishing lifecycle) — GIF legitimately deferred
## OPERATIONAL STATUS: **NOT_DEPLOYED** (agent did not deploy; backend changes require user-operated rollout)

The mandatory publishing lifecycle is closed: write → authoritative persistence → Global feed (now includes
own posts) → Own Activity (real persisted posts) → Post Detail → comments/replies → save/boost. GIF was
explicitly optional under the Stage 0 gate and is DEFERRED_OPERATIONAL — this does not make the sprint PARTIAL.

## Domain status
| Domain | Status |
|---|---|
| Post persistence | READY (proven; single-INSERT, query-time read-back) |
| Feed self-post semantics | READY — FEED_SELF_EXCLUSION fixed; own public posts participate by recency; regression-tested |
| Composer | READY — already production-grade (COMPOSER-A); + Activity reconciliation on success |
| Activity | READY — own Activity now reads real `/v1/users/{id}/posts` (was stubbed), renderer-reused, real states |
| Post Detail | READY — canonical `FeedItem` reuse; interaction reconciliation intact |
| Comments | READY (SOCIAL-A; authoritative count; no regression) |
| Replies | READY (depth-capped; real identity) |
| Save | READY (SOCIAL-B hydration; survives restart) |
| Boost | READY (SOCIAL-B hydration; survives restart) |
| Attachment foundation | DEFERRED (design documented; no speculative migration) |
| GIF provider | DEFERRED_OPERATIONAL (no provider provisioned; server-side-key mandate) |
| GIF picker | DEFERRED (depends on provider) |
| Renderer consistency | READY — `FeedItem` shared Feed/Activity/Public-profile/Detail |
| Retry/idempotency | DOCUMENTED — UI duplicate-guard + GET-only auto-retry; create-post server dedupe recommended (deferred) |
| Accessibility | ADDRESSED — semantics/keys/honest states; profiling + GIF a11y deferred |
| Live contract state | deployed gw 0.1.13 / social 0.1.8; code-ready social 0.1.9 + gw 0.1.14 (QUALITY-A) pending |

## Disappearing-post root cause: **A. FEED_SELF_EXCLUSION** (proven, fixed).

## Changes
- insight-social: `feed/service.go` Global public-fill no longer excludes own posts (+2 regression tests).
- insight-azteca-flutter: own `_ActivityTab` → `userPostsProvider` + `FeedItem` (real posts, real states,
  renderer reuse); composer invalidates `userPostsProvider(myId)` on success.
- insight-gateway: unchanged (QUALITY-A 0.1.14 preserved).

## Validation
Flutter analyze clean, 72 tests, diff clean. Social go build/vet/test green (11 application tests incl. 2
new), diff clean. Gateway untouched.

## Backend repos changed
insight-social (required). Gateway unchanged (0.1.14 still pending from QUALITY-A).

## Deployed-vs-code-ready delta
social 0.1.8→0.1.9 (feed fix); gateway 0.1.13→0.1.14 (QUALITY-A avatar, unchanged here); Flutter app build.

## Required manual deployment
Build/push social 0.1.9 + gateway 0.1.14; deploy social then gateway + nginx reload; ship app build; smoke
per DEPLOY.md. No migration. Avatar still needs MinIO (independent QUALITY-A follow-up).

## Remaining blockers before AZTECA-PROFILE-B
NONE that block PROFILE-B. Follow-ups (not blockers): deploy social 0.1.9 + gateway 0.1.14; provision MinIO;
(optional) create-post idempotency key; GIF provider provisioning when desired. PROFILE-B (real Edit Profile
+ PATCH /v1/users/me) is independent and can start.

## Principles honored
Backend source of truth; no mock persistence; no fake optimistic success; no vendor coupling; text-only
backward compatible; no unrelated redesign; no deploy; QUALITY-A gateway fix preserved.
