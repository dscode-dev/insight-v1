# Azteca Splash Report (Azteca-X Part 1)

## Pipeline audit

| layer | finding |
|---|---|
| Flutter splash (`lib/features/splash/splash_screen.dart`) | correct — transparent mark, `BoxFit.contain` in a square box, size derived from shortest side (clamped), gentle fade+scale entrance + breathing glow + 3-dot pulse |
| asset | `assets/image/insight-splash.png` (512, RGBA, transparent) + `insight-logo-transparent.png` (1024, RGBA) — both clean, same glyph, **no black background** |
| native config (`flutter_native_splash` in pubspec) | correct — `image: insight-splash.png`, `color: #0A0E1A`, android_12 block present |
| iOS storyboard | `LaunchImage` imageView `contentMode="center"` (not stretched); background `scaleToFill` (solid color, safe) |
| Android | `launch_background.xml` splash `gravity="center"`, background `gravity="fill"` (not stretched) |

The asset + Flutter splash + native config were already correct from prior
fixes; the residual risk was **stale generated native assets**.

## Fixes applied

- **Regenerated all native splash assets** from the (correct) config:
  `dart run flutter_native_splash:create` → fresh iOS imageset (incl. dark) +
  Android drawables, eliminating any stale/distorted generated files. Output:
  `✅ Native splash complete`.
- **Login logo bug fixed** — `phone_entry_screen.dart` was loading the
  **non-transparent** `insight-logo.png` (1254 RGB, black square); switched to
  `insight-logo-transparent.png` with `BoxFit.contain`, so the mark sits clean
  on the auth background (this black-square mark was a likely source of the
  "distortion" perception on first launch screens).

## Result

- Splash mark: transparent, aspect-preserved (`contain`), correctly sized on
  phone → Pro Max → iPad, on a single `#0A0E1A` background shared by the native
  launch frame and the Flutter splash → seamless hand-off (no size jump, no
  flash, no black square).
- Premium + modern (GitHub Mobile / Linear / Threads reference): calm entrance +
  subtle breathing glow + staggered dot pulse; no excessive animation.
- Branding unchanged — official Insight mark, no new logo.
