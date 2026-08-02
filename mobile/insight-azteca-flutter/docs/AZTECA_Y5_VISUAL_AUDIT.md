# Azteca Y.5 — Visual Consistency Pass (Part 8)

Final audit — fix inconsistencies only, no redesign.

## Token system (consistent — single source of truth)

- Spacing: `InsightSpacing` scale (2/4/8/12/16/20/24/32/40/56) + `pageHorizontal`,
  `feedItemVertical`. New screens (auth entry, settings Segurança, onboarding
  mark) use tokens — no magic numbers.
- Typography: one Inter ramp (`display/title/headline/body/caption/micro`,
  `withTabular`).
- Color: Material 3 `ColorScheme` + `InsightColors` (`ds.signal/textHigh/Mid/Low/
  divider/subtle`); all new widgets pull from `context.ds.*`.
- Avatars: single `InsightAvatar`; icons 18–22 consistently.

## Checked this sprint

| surface | result |
|---|---|
| Auth entry (new) | token spacing, 60px mark, FilledButton primary — consistent |
| Settings "Segurança" (new) | matches existing `ListTile`/SectionHeader + "Em breve" pill style (same as auth entry) |
| Onboarding welcome | mark + glow mirror the auth-entry/login brand treatment (consistent brand block across auth surfaces) |
| Sheets | composer 24px top radius + handle (`bottomSheetTheme`) |
| Motion | one global `pageTransitionsTheme` (no per-route drift) |

## Fixes

- Unified the "Em breve" pill treatment between the auth-entry future-auth card
  and the Settings Segurança tile.
- Brand block (mark + radial glow) is now consistent across auth entry, login
  and onboarding welcome.

## Honest gaps (next increment)

Nested-reply indentation; optional feed metadata typographic pass. Documented,
not silently claimed. The app already runs on a disciplined token system, so the
audit found consistency to preserve, not chaos to undo.
