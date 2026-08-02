# AZTECA-QUALITY-A — Test Repairs (6 failures → 0)

Full suite before: **51 passed / 6 failed**. After: **72 passed / 0 failed** (+ new guardrail tests).
Root cause understood before each change; no assertion weakened; no production behavior changed for tests.

| # | Test | Root cause | Fix |
|---|---|---|---|
| 1 | `api_client_test.dart` "defaults are production-safe" | STALE: expected old LAN default `http://192.168.1.61:8080`; STAGING-INTEGRATION-B removed LAN/loopback, every env resolves to the cloud Gateway. Production code correct. | Updated expected to `https://insight-api.konohalabs.com.br` (the production-safe default) + explanatory comment. |
| 2 | `widget_test.dart` "authenticated boot … 5 tabs" | STALE: asserted `FloatingBottomNav`; production uses `FixedBottomNav` (shell.dart:84). | Import `fixed_bottom_nav.dart`; assert `FixedBottomNav`; description "fixed bottom nav shell". |
| 3-5 | `home_screen_test.dart` (boot renders post / re-tap refresh / new-posts pill) | STALE `FloatingBottomNav` assertions (lines 156/168/188). The feed API was ALREADY correctly stubbed (`socialApiProvider.overrideWithValue(_CountingSocial)`), so the 400-network warning was a red herring. | Swap `FloatingBottomNav`→`FixedBottomNav` (import + 3 refs). |
| 6 | `launch_flow_test.dart` "authenticated user goes straight to Home" | STALE `FloatingBottomNav` (findsOneWidget at :84; the findsNothing cases already passed). | Swap type (import + 4 refs). |

## Notes / decisions
- `test/ui_screenshots/splash_nav_screenshots_test.dart` constructs `FloatingBottomNav` directly as a
  golden **UI-capture harness** (matchesGoldenFile) and **passes**. It is not a behavioral nav test.
  Intentionally left untouched: regenerating goldens introduces font/platform flakiness into a stability
  sprint for zero behavioral value. Production nav behavior is covered by widget_test/home_screen/launch_flow.
- `FloatingBottomNav` widget is now orphaned in production, BUT its file `floating_bottom_nav.dart` also
  hosts the shared `FloatingNavDestination` MODEL used by `fixed_bottom_nav.dart` + `shell.dart` — so the
  file is a live dependency and was NOT deleted. Renaming the model (misleading name) is tracked as
  non-urgent tech-debt (out of scope for a quality sprint).
- New guardrail tests: `theme_persistence_test.dart` (5), `avatar_error_message_test.dart` (8),
  `legal_org_test.dart` (2).
