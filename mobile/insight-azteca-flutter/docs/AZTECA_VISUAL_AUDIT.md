# Azteca Visual Consistency Audit (Azteca-Y Part 7)

## Token system (single source of truth — consistent)

- **Spacing** (`theme/spacing.dart`): a strict scale `xs2 2 · xs 4 · sm 8 ·
  md 12 · lg 16 · xl 20 · xl2 24 · xl3 32 · xl4 40 · xl5 56`, plus semantic
  aliases `pageHorizontal = xl (20)`, `feedItemVertical = lg (16)`. Screens use
  these tokens — no magic numbers in the audited surfaces (login, registration,
  composer, feed shell, settings).
- **Typography** (`theme/typography.dart`): one family (Inter via google_fonts)
  with `display / title / headline / body / bodyMedium / caption / micro` +
  `withTabular` for numerics — consistent ramp across screens.
- **Color/theme** (`theme/theme.dart`): Material 3 `ColorScheme` + the
  `InsightColors` extension (`ds.signal`, `ds.textHigh/Mid/Low`, `divider`,
  `subtle`, confidence colors). All audited widgets pull from `context.ds.*`
  rather than literals.
- **Avatars**: a single `InsightAvatar` (initials + accent) used by the feed
  shell, composer header and thread → consistent sizing/treatment.

## Findings + actions

| area | finding | action |
|---|---|---|
| Login mark | loaded the black-square `insight-logo.png` | → transparent asset (fixed) |
| Composer chips | already token-spaced, Insight post types | preserved |
| Feed card | token shell + AI/system stripe (not generic) | preserved (no genericizing) |
| Motion | inconsistent/none across navigation | unified `pageTransitionsTheme` (Part 6) |
| Sheets | composer uses 24px top-radius, safe-area, handle | consistent with `bottomSheetTheme` |
| Buttons | FilledButton hierarchy (primary CTA), TextButton (secondary) | consistent |

## Consistency posture

The app already runs on a disciplined token system, so the audit found
**structural consistency, not chaos**. The fixes this pass were targeted (login
mark, global motion) rather than a sweeping restyle — consistent with the
product directive to evolve, keep Insight's sports-intelligence identity, and
not converge on a generic social look. Icon sizing (nav 22 / inline 18–20),
avatar sizing (36 composer / 40 feed) and paddings were confirmed token-driven.

## Honest gaps (next increment)

- Nested-reply indentation styling in the thread (depth affordance).
- A deeper feed-card typographic pass (line-height/metadata weight) — optional,
  guarded against genericizing.
These are documented, not silently claimed as done.
