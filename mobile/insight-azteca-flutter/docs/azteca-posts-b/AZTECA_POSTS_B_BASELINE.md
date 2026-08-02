# AZTECA-POSTS-B — Stage 0 Forensic Baseline

Verified against real code (not audit assumptions). Repos: insight-azteca-flutter, insight-social,
insight-gateway.

## Publishing chain (Flutter → Social)
- Composer `composer_screen.dart` (full-screen ComposerScreen, COMPOSER-A) → `socialApiProvider.createPost`
  → `POST /v1/posts` → Social. Persistence REAL.
- Feed: `FeedNotifier`(feed_provider) → `socialApi.globalFeed/followingFeed` → `/v1/feed/global|following`.
- Own Activity (BEFORE this sprint): `profileBundleProvider` → `GET /v1/profile/me/bundle` — **STUBBED**
  ("until ClickHouse activity projections wired"). Public Activity: `userPostsProvider` → `/v1/users/{id}/
  posts` — REAL. **Inconsistency found + fixed** (Stage 5).
- Post detail/comments: `/v1/posts/{id}`, `/v1/posts/{id}/comments` — REAL.

## Disappearing-post root cause: **FEED_SELF_EXCLUSION** (proven)
`insight-social/internal/application/feed/service.go:126` — the Global feed's public fill explicitly
`continue`d on `item.Post.AuthorID == userID`; the followed-authors path never includes self (a user
doesn't follow themselves). ⇒ a persisted own public post was structurally absent from `/v1/feed/global`,
so the composer's optimistic `prepend` was evicted by the authoritative refresh. NOT a persistence/ranking/
pagination/client defect. Confirmed via feed/service.go + feedrepo `RecentPublic` (returns own public posts).

## Creation lifecycle (already sound)
`composer.submit()`: `if (publishing.value) return` (duplicate-submit guard); validates empty/max; sets
publishing; `createPost`; on success prepend + clear draft + pop; on failure keeps draft + inline error.
No false optimistic success (draft cleared only after backend confirms). Idempotency: none server-side
(see IDEMPOTENCY.md) — retry-after-timeout risk documented; not exactly-once.

## Composer UX
Already improved by COMPOSER-A: rounded field, focus border, cursor styling, `minLines:7`, contentPadding
`lg`(16)/`md`(12) — adequate (cursor does not touch edges). Keyboard/SafeArea handled by the full-screen
route. No full rebuild justified ("avoid redesign for redesign's sake").

## Post model / media
Text-only (`content` + `metadata` JSONB + `visibility`); NO media/attachment fields (social.dart/feed.dart).
FeedRenderers: `feed_item_renderer.dart` registry (TextPostRenderer). Canonical card `FeedItem` reused by
Feed + public profile.

## Gateway
QUALITY-A avatar fix (`avatarStorageUnavailable` + always-registered route + 503) is **present + committed**
(code = 0.1.14, deployed = 0.1.13). NOT touched by this sprint — preserved. No GIF routes/env anywhere.

## GIF feasibility
No provider configured (no `/v1/gifs/*`, no TENOR/GIPHY env). Server-side-key mandate + absent media infra
(avatar object storage still unprovisioned) ⇒ see GIF_DECISION.md → **DEFERRED_OPERATIONAL**.

## Live delta (read-only)
Deployed gateway 0.1.13 / social 0.1.8. This sprint's code: social 0.1.9 (feed fix) + Flutter app +
gateway 0.1.14 already-pending (QUALITY-A). See LIVE_DELTA.md.
