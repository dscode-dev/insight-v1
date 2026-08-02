# Azteca Splash Validation (Azteca-Y Part 2)

## State

- **Flutter splash** (`splash_screen.dart`): transparent mark
  (`insight-logo-transparent.png`, 1024 RGBA), `BoxFit.contain` in a square box,
  size = clamped shortest-side ratio → never stretched; fade+scale entrance +
  breathing glow + 3-dot pulse on a single `#0A0E1A` background.
- **Native splash** (`flutter_native_splash`): `insight-splash.png` (512 RGBA,
  transparent glyph) on `#0A0E1A`; iOS `contentMode=center`, Android
  `gravity=center` (neither stretches). Regenerated (Azteca-X) to clear stale
  generated assets.
- **Login mark fixed** (Azteca-X): was loading the non-transparent
  `insight-logo.png` (black square) → switched to the transparent asset.

## Validation

- Assets re-checked: corner alpha = 0 (transparent), same official glyph at
  512/1024 — **no distortion, no stretching, no black artifacts, no wrong scale**.
- App built + run locally (web): boots through the native frame → Flutter splash
  → onboarding with no flash/size-jump (single shared `#0A0E1A`).
- Logo unchanged — official Insight mark, no redesign/replacement.

Definitively resolved: the only outstanding source (login using the black-square
asset) is fixed; native + Flutter splashes share one transparent mark + one
background.
