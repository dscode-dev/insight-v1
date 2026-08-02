# Azteca Y.5 — Feed Polish (Part 4)

## Posture

Per the directive ("do not redesign cards · keep Insight identity · do not
imitate Threads · do not create a generic social network"), the feed card was
**audited, not restyled**. `feed_item_shell.dart` is already a disciplined,
scannable layout:
- token paddings (px=20 / py=16), 40px avatar lane, author/metadata header row,
  body slot;
- a **3px lateral accent stripe for AI / system posts** — an Insight-specific
  affordance, not a generic timeline;
- variants carry the sports-intelligence taxonomy (reading / analysis / signal /
  community-signal / discussion).

## This sprint

- The global **motion layer** (Azteca-Y) animates feed→thread navigation,
  improving perceived flow without touching card code.
- Keyboard dismissal on feed drag (Azteca-X) retained.
- Audit confirmed avatar/metadata/action-row spacing is token-consistent
  (`AZTECA_Y5_VISUAL_AUDIT.md`).

## Honest note

No card markup was changed this sprint — deliberately, to avoid genericizing a
card that already meets the "easy to scan + Insight identity" bar. A deeper
typographic pass (metadata weight / line-height) remains an optional, identity-
guarded follow-up. Stated plainly rather than claimed.
