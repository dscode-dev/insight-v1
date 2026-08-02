# Azteca Feed (Azteca-Y Part 3)

## Audit finding

The feed card is **not** Flutter-generic — `feed_item_shell.dart` is a
token-driven shell (px=20 / py=16 via `InsightSpacing`), a 40px avatar lane, an
author/metadata header row, a body slot, and a **3px lateral accent stripe for
AI / system posts** that identifies the variant at a glance. Variants
(`feed_item.dart` + `posts/`) carry the Insight identity: reading / analysis /
signal / community-signal / discussion — sports-intelligence post types, not a
generic timeline.

## This sprint

- **Motion**: the global `FadeForwardsPageTransitionsBuilder` (Part 6) now
  animates feed → post-thread navigation, improving interaction affordance
  without touching card code.
- **Keyboard**: feed `CustomScrollView` dismisses the keyboard on drag
  (Azteca-X) — composing/search no longer traps it.

## Deliberate restraint (per product guidance)

Per the directive to **keep Insight's identity and not clone Threads/X**, the
card was audited and preserved rather than re-skinned. It already meets the
"elegant + readable" bar with sports-intelligence framing; a deeper visual
reflow is intentionally deferred to avoid genericizing the product. Spacing,
avatar and metadata hierarchy were confirmed token-consistent in the audit
(`AZTECA_VISUAL_AUDIT.md`).
