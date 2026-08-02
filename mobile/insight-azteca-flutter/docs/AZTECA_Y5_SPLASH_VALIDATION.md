# Azteca Y.5 — Splash Final Validation (Part 6)

Real visual validation of the splash pipeline. **No issue found; documented.**

## Verified

| check | result |
|---|---|
| logo rendering | official Insight glyph (`insight-splash.png` 512 native / `insight-logo-transparent.png` 1024 Flutter) — both the same mark |
| transparency | RGBA, corner alpha = 0 (no black box) |
| scaling | `BoxFit.contain` in a square box; size = clamped shortest-side ratio → never stretched |
| safe areas | Flutter splash centered; native frame uses the same `#0A0E1A` so the hand-off has no jump |
| dark backgrounds | single `#0A0E1A` shared by native + Flutter (no second background, no flash) |

## Method

App built + run locally (web, `ENVIRONMENT=local`): boots through the native
frame → animated Flutter splash (fade+scale mark, breathing glow, 3-dot pulse) →
onboarding, on one continuous dark background. Assets re-inspected for alpha +
dimensions. Native splash was regenerated in Azteca-X; the only prior defect
(login using the opaque `insight-logo.png`) was fixed there.

## Conclusion

No distortion, no stretching, no black artifacts, no wrong scaling. Logo
unchanged (official Insight mark — not replaced). Splash is validated.
