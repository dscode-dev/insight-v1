# AZTECA V1 — Test Suite & Quality Audit (Stage 11)

## Results (this audit, real runs)
- `flutter analyze` → **No issues found** (clean, 4.1s).
- `flutter test` → **+51 passed / -6 failed**.
- `git diff --check` → clean (see validation).

## Failing tests (6) — triaged (NOT modified per audit rules)
| Test | Verdict | Cause / hotfix |
|---|---|---|
| `widget_test.dart:36` "authenticated boot renders the floating shell with 5 tabs" | **STALE** | Asserts `find.byType(FloatingBottomNav)`. NAVIGATION-A intentionally made the nav FIXED (non-floating); `FloatingBottomNav` no longer the mounted type. Hotfix: replace with the current fixed nav widget type + keep the 5-tab assertion. |
| `test/ui_screenshots/splash_nav_screenshots_test.dart` (nav variants) | **STALE (same cause)** | Same floating→fixed nav rename ripple. |
| `home_screen_test.dart` "home boots from the global feed and renders post content" | **TEST-HARNESS** | Test binding returns HTTP 400 (no network); the feed provider isn't stubbed → renders error not posts. Needs a mocked `socialApiProvider` override. Not a production regression. |
| `home_screen_test.dart` "re-tapping Home refreshes feed + clears pending pill" | **TEST-HARNESS** | Same unstubbed-network cause. |
| `home_screen_test.dart` "tapping the new-posts pill refreshes the feed" | **TEST-HARNESS** | Same. |
| `api_client_test.dart` "environment config defaults are production-safe" | **LIKELY STALE** | env.dart defaults changed (single cloud base URL, STAGING-INTEGRATION-B); assertion likely encodes an older default. Verify exact expectation before touching. |

**None are confirmed production regressions.** 2 clusters: (a) stale nav-widget-type assertions (FloatingBottomNav→fixed),
(b) home_screen tests that require provider-override mocking of the feed API (they hit the 400 test-network).
Exact audit-unblocking hotfix (do in AZTECA-QUALITY-A, not here): (1) update nav widget type in
`widget_test.dart`/screenshot tests; (2) override `socialApiProvider` with a fake in home_screen_test;
(3) reconcile api_client_test env default assertion.

## Test debt matrix (coverage vs need)
| Domain | Current | Debt |
|---|---|---|
| Auth | some (api_client, boot) | refresh/rotation edge cases |
| Navigation | present but STALE | fix widget-type; add fixed-nav coverage |
| Feed | present but harness-broken | stub feed provider; add pagination/refresh tests |
| Post create | weak | add persist + optimistic-prepend + refresh-eviction test (encode the own-post/feed-semantics reality) |
| Comments/replies | none found | add |
| Save/Boost/Like | none found | add optimistic + rollback |
| Profile/Identity | partial | add sports-profile render + tabs |
| Avatar | none | add upload success/failure(404) handling |
| Follow | none | add |
| Settings persistence | none | add theme-not-persisted regression + prefs PUT |
| Search/Communities/Notifications/Realtime | none | add once real |

## Verdict
Quality baseline is GOOD (analyze clean, 51 green). The 6 failures are stale/harness issues, not
regressions. Test debt is concentrated in social mutations, profile, settings persistence, and the missing
domains. AZTECA-QUALITY-A should fix the 6, add a feed-provider test harness, and lock the own-post/feed
reality with a regression test.
