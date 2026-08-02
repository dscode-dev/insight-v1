# AZTECA-QUALITY-A — Theme Persistence

## Problem
`themeModeProvider` was a bare `StateProvider<ThemeMode>` (system default) with no persistence — a user's
choice was lost on restart, while the Settings UI already CLAIMED "O tema é salvo apenas neste dispositivo".

## Implementation (device-local, reuses existing storage)
- `lib/core/theme_store.dart` — `ThemeStore` over `flutter_secure_storage` (same strategy as TokenStorage/
  ComposerDraftStore; NO new dependency, NO second storage mechanism, NO backend endpoint — theme is a
  DEVICE preference). Encodes `system|light|dark`; read/write both **degrade safely** (read failure → system;
  write failure swallowed).
- `lib/providers/settings_provider.dart` — `themeModeProvider` is now a `NotifierProvider`
  (`ThemeModeNotifier`) with `set(mode)` that updates state + fire-and-forget persists (`.catchError` so a
  throwing store never crashes the app). `bootThemeModeProvider` seeds the initial value.
- `lib/main.dart` — hydrates `await ThemeStore().read()` BEFORE `runApp` and overrides `bootThemeModeProvider`
  → the app opens in the saved theme with **no flash**.
- `settings_screen.dart` — 3 call sites migrated `.state = X` → `.set(X)`. Semantics unchanged (device-only);
  the existing "salvo apenas neste dispositivo" copy is now truthful.

## Tests (`test/theme_persistence_test.dart`, 5)
default=system; encode/decode round-trip (unknown→system); set() updates+persists; **persisted choice
restored after container recreation (restart sim)**; storage write failure degrades safely (no throw).

## Result
Theme survives restart; system/default preserved when never changed; failure-safe; flash-free. analyze clean.
