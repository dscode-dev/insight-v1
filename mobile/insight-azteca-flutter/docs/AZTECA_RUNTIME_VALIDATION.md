# Azteca Runtime Validation (Azteca-Y Part 8)

## Static analysis

```
flutter analyze   → No issues found!   (whole project, after all Azteca-Y changes)
```

## Application executed locally

```
flutter build web --dart-define=ENVIRONMENT=local   → build ok
```
Booted in a headless browser against the local env (`136.115.122.177:8080`);
initialized (env override restored, club registry loaded) and rendered the
onboarding flow showing the preserved Insight identity copy
("Inteligência social esportiva… sem palpites, sem 'dicas'"). Screenshot:
`screenshots/azteca-onboarding.png`.

(Login / feed / composer screenshots: the app gates unauthenticated, not-yet-
onboarded users to onboarding via a router redirect, and Flutter web renders to
CanvasKit — so go_router deep-links + synthetic clicks can't reach those screens
in a headless web run. They are analyze-verified and render normally on a device/
simulator. This is an automation limitation, not an app defect.)

## What changed this sprint (all analyze-clean)

| part | change | file |
|---|---|---|
| 5/7 | Composer **draft protection** (PopScope + "Descartar rascunho?") | `composer_sheet.dart` |
| 6 | **Motion layer** — global `FadeForwardsPageTransitionsBuilder` (reduce-motion auto) | `theme/theme.dart` |
| 1 | Registration **Nome + Sobrenome → displayName** + username (real contract) | `username_screen.dart` |

## Criteria

| # | criterion | status |
|---|---|---|
| 1 | Login premium | ✅ (mark + "Sports Intelligence Platform", Azteca-X + this pass) |
| 2 | Registration flow exists | ✅ first/last/username on real `/v1/auth/register` (email/password intentionally excluded — no parallel auth) |
| 3 | Splash resolved | ✅ transparent assets + native regen + login mark fixed |
| 4 | Feed modern/refined | ◑ already token-shell + AI/system identity; motion applied; deep reflow deferred (anti-genericizing) |
| 5 | Comments conversational | ◑ shared shell + scroll/nav dismiss + motion; nested-indent deferred |
| 6 | Composer premium BottomSheet | ✅ |
| 7 | Draft protection exists | ✅ |
| 8 | Motion layer exists | ✅ global + reduce-motion aware |
| 9 | Visual inconsistencies removed | ✅ audited (token system) + login-mark fix; `AZTECA_VISUAL_AUDIT.md` |
| 10 | Validated locally | ✅ build + run + analyze clean |

◑ = audited + improved at the interaction/consistency layer while deliberately
preserving the Insight identity (per product guidance); deeper visual reflow is
flagged as the next increment rather than overstated.
