# Azteca UX Maturity Report (Azteca-X)

Evolution of the existing Azteca experience — no redesign, no new design system.

## Part 1 — Splash
Native splash regenerated; login mark switched to the transparent asset (was
loading the black-square logo). See `AZTECA_SPLASH_REPORT.md`.

## Part 2 — Login
`phone_entry_screen.dart`: transparent logo (`BoxFit.contain`, no black square),
stronger wordmark (titleLarge / w700) + a **"Sports Intelligence Platform"**
positioning line under "Insight" — the login now communicates the product on
first contact instead of reading as a generic form. Existing loading/error
states (OTP round-trip) retained; the bottom-anchored CTA already keeps clear of
the keyboard.

## Part 3 — Onboarding
Existing flow kept (no new architecture). The first-access onboarding renders
(see `screenshots/azteca-onboarding.png`) with clear product positioning copy
("Inteligência social esportiva…"). The flow + transitions are preserved;
deeper illustration work is a follow-up (flagged honestly — this sprint
prioritized the splash, login, keyboard and integration where the defects were).

## Part 4 — Feed & comments
`feed_list.dart` + `post_thread_screen.dart`: added `keyboardDismissBehavior:
onDrag` so scrolling the feed/thread dismisses the keyboard (conversational
feel — the reply field never traps it). No backend contracts or data structures
changed (UI/UX only).

## Part 5 — Keyboard
App-wide dismissal: tap-outside (root gesture), navigation (router observer),
scroll (list behavior). See `AZTECA_KEYBOARD_FIX_REPORT.md`.

## Part 6/7 — Integration & environments
`local` environment (136.115.122.177) + runtime environment switcher (Settings →
Ambiente, secure-storage persisted, production-locked). Live gateway validated
(`/v1/auth/otp/request` → 202). See `AZTECA_BACKEND_INTEGRATION_REPORT.md` +
`AZTECA_ENVIRONMENT_STRATEGY.md`.

## Verification
`flutter analyze` → **No issues found** across the whole project. App **runs
locally** (web target) booting to the onboarding flow against the local env.
See `AZTECA_RUNTIME_VALIDATION.md`.

## Honest scope note
Highest-impact, defect-driven areas (splash, login branding, keyboard,
env+integration) are fully implemented and analyze-clean. Onboarding illustration
depth and a full feed/comment visual reflow are lighter-touch this pass and are
the natural next increment — called out rather than overstated.
