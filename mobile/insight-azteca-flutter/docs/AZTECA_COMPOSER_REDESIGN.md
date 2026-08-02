# Azteca Composer (Azteca-Y Part 5)

`lib/features/home/widgets/composer_sheet.dart`

## Already BottomSheet-first (kept + verified)

The composer is a `showModalBottomSheet(isScrollControlled, useSafeArea)` sheet
with: drag handle, sticky header (avatar + name + close), scrollable body, and a
**sticky footer that stays above the keyboard** (`AnimatedPadding` on
`viewInsets.bottom`), a live character counter (`/2000`), a publishing spinner
state, and post-on-failure draft retention. This Threads-style presentation was
already in place; this sprint adds the missing safety + keeps the **Insight
identity**: the kind chips are **Leitura · Análise · Sinal · Sinal da comunidade
· Discussão** (sports-intelligence post types, not a generic "what's happening").

## Added this sprint — Draft protection (criterion #7)

`PopScope` now guards every dismissal path (swipe-down, system back, close
button):
```dart
PopScope(
  canPop: forceClose.value || publishing.value || !hasDraft,
  onPopInvokedWithResult: (didPop, _) async {
    if (didPop) return;
    if (await _confirmDiscard(context) == true) Navigator.pop();
  },
  child: …
)
```
`_confirmDiscard` shows **"Descartar rascunho?"** with
**Continuar editando / Descartar**. A successful publish sets `forceClose` so it
pops without the prompt. With no unsaved text the sheet closes freely.

## Keyboard awareness

Footer rides `MediaQuery.viewInsetsOf().bottom` via `AnimatedPadding` (fluid
resize, Publish always reachable); focus is requested post-open-frame to avoid
sheet/keyboard jitter. Combined with the app-wide dismissal layer (Azteca-X),
the composer keyboard behaves natively.

Verified: `flutter analyze` clean.
