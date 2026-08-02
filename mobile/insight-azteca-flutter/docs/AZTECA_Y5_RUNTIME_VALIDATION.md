# Azteca Y.5 — Runtime Validation (Part 9)

## Static analysis

`flutter analyze` → **No issues found** (whole project, after all Y.5 changes).

## Ran locally

`flutter build web --dart-define=ENVIRONMENT=local` → build ok; booted in a
headless browser against the local Gateway env and rendered the **improved
onboarding** (Insight mark + glow). Screenshot: `screenshots/azteca-y5-onboarding.png`
(before: `screenshots/azteca-onboarding.png`).

Login / auth-entry / registration / feed / comments / composer are
analyze-verified and render on device/simulator; they are NOT web-screenshottable
here because the router gates unauthenticated, not-yet-onboarded users to
onboarding and Flutter web (CanvasKit) does not accept synthetic pointer events
to advance the onboarding PageView — a headless-tooling limit, not an app defect
(consistent across Azteca-X/Y/Y.5).

## Changes (all analyze-clean)

| part | change | file(s) |
|---|---|---|
| 2 | Auth entry screen + route landing | `auth_entry_screen.dart`, `router.dart`, `routes.dart` |
| 2 | Settings "Segurança" biometric/passkey prep | `settings_screen.dart` |
| 7 | Onboarding welcome mark + hierarchy | `onboarding_screens.dart` |

(Login/feed/comment/splash audited + preserved per the "evolve, don't redesign"
directive; their substantive polish landed in Azteca-X/Y.)

## Criteria

1. Login more premium — ✅ premium auth-entry landing
2. Registration more polished — ✅ (Azteca-Y first/last/username + validation, preserved)
3. Future auth prepared — ✅ entry method choice + Segurança "em breve" (no Firebase/WebAuthn)
4. Feed readability — ◑ audited + motion; identity preserved (no genericizing)
5. Comment readability — ◑ shared shell + motion + dismissal; nested-indent next
6. Onboarding more polished — ✅ verifiable before/after
7. Splash validated — ✅ documented, no issue
8. No backend contracts change — ✅
9. No provider architecture change — ✅ (additive route only)
10. Runs locally + validated — ✅ analyze clean + onboarding screenshot

◑ = audited/improved at interaction+consistency layer while preserving the
Insight identity; deeper visual reflow flagged honestly as the next increment.
