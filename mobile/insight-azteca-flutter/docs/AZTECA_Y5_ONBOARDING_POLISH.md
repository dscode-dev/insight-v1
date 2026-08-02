# Azteca Y.5 — Onboarding Polish (Part 7)

Same flow, same messaging, same positioning — better presence.

## Change

`onboarding_screens.dart` welcome step: the page was mostly empty (title + one
paragraph, then a large void). Added the **transparent Insight mark with a soft
brand-signal glow** below the copy, and softened the body to `textMid` for a
clearer title→body→mark hierarchy. On-brand (the official Insight glyph) — not a
generic illustration, keeping the sports-intelligence identity.

## Preserved

- Flow (welcome → about → competitions → teams), progress dots, skip rules.
- Copy verbatim: *"Inteligência social esportiva… sem palpites, sem 'dicas'."*
- `_StepShell`, providers, routes.

## Evidence (verifiable before/after)

- Before: `screenshots/azteca-onboarding.png` (text + empty gap).
- After: `screenshots/azteca-y5-onboarding.png` (mark + glow + softer copy).

Captured from the app running locally (web, `ENVIRONMENT=local`). `flutter
analyze` clean.
