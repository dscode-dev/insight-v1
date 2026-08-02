# Azteca Keyboard Fix (Azteca-X Part 5)

A production-grade, app-wide keyboard strategy — no per-screen unfocus hacks, no
repeated `unfocus()` calls.

## Three layers (all global)

1. **Tap outside dismisses** — `lib/app.dart` wraps the whole app in a single
   translucent `GestureDetector` (`_DismissKeyboard`). `onTap` only fires when
   no child gesture (button, field, list) claims the tap, so it never steals
   interactions; tapping any non-interactive area unfocuses the active editable.
2. **Navigation dismisses** — `lib/routing/router.dart` adds a
   `_KeyboardDismissObserver` (NavigatorObserver) to GoRouter; every
   push/pop/replace unfocuses, so a field focused on one screen never leaves the
   keyboard up on the next.
3. **Scroll dismisses** — the feed (`feed_list.dart` CustomScrollView) and the
   comment thread (`post_thread_screen.dart` ListView) set
   `keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag` — dragging
   the list closes the keyboard.

## Why this is correct (not a hack)

- One root gesture + one router observer cover **every** screen (login, posts,
  comments, search, forms) without touching each FocusNode.
- `HitTestBehavior.translucent` + `onTap` (not `onTapDown`) means buttons and
  fields keep working; the dismiss only triggers on otherwise-unhandled taps.
- `excludeFromSemantics` keeps the a11y tree clean.
- Bottom sheets: closing a sheet is a route pop → the observer unfocuses; taps
  on the scrim already dismiss.

## Affected areas (all covered)

login · posts · comments · search · forms — via the global layers above. No
screen needs bespoke keyboard code anymore.

Verified: `flutter analyze` → No issues found.
