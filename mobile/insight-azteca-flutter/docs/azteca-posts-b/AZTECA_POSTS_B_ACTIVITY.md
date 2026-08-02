# AZTECA-POSTS-B — Profile Activity as a Real Persistence Surface

## Problem (found in Stage 0)
Own-profile Activity read `profileBundleProvider` → `GET /v1/profile/me/bundle`, which is **stubbed**
Gateway-side ("until ClickHouse activity projections wired"). So a persisted post was NOT reliably visible
in the owner's Activity — even though the real per-author endpoint `/v1/users/{id}/posts` exists and the
PUBLIC profile already used it.

## Fix
Own `_ActivityTab` (profile_screen.dart) now reads `userPostsProvider(myId)` → `GET /v1/users/{id}/posts`
(the SAME authoritative endpoint + canonical `FeedItem` renderer the public profile uses). Delivered:
- real **loading / empty / error(+retry)** states;
- **pull-to-refresh** (invalidates `userPostsProvider` + stats bundle);
- **stable item keys** (`ValueKey(post.id)`);
- renderer reuse (`FeedItem`) → Feed / Activity / Public-profile / Detail stay consistent (Stage 6);
- `ProfileCompletenessCard` header preserved; tab selector visual UNCHANGED (as required).
Statistics tab still reads `profileBundleProvider` (stats/badges) — unchanged.

## Create → Activity reconciliation
Composer `submit()` success now `ref.invalidate(userPostsProvider(myId))` → the freshly persisted post
appears in Profile▸Atividades on next open/refresh, independent of feed ranking. Combined with the Stage 1
feed fix, the post is discoverable in BOTH the Global feed and Activity.

## Honesty of scope
Activity shows **persisted posts only** (real contract). Comments/boosts/follows as activity types have no
real per-user activity endpoint → NOT fabricated. The `/v1/profile/me/bundle` activity projection remains a
backend backlog (ClickHouse) — when it lands, a richer timeline can augment (not replace) the real posts.

## Tests
Backend read-back proven (feed AuthorPosts). Flutter: full suite green (72), no regression; the widget-level
create→Activity assertion is documented as a manual smoke (heavy provider harness deferred — see VALIDATION).
