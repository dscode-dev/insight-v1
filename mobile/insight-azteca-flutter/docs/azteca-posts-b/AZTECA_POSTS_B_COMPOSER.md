# AZTECA-POSTS-B — Composer

## Audit verdict: already production-adequate (COMPOSER-A); targeted verification, no rebuild
Full-screen `ComposerScreen` (not a cramped bottom sheet). Evidence it already meets the bar:
- **Layout**: author identity row (avatar + name), multiline `TextField` (`minLines:7`, `maxLines:null`),
  rounded container with focus border, hint text, line-height 1.48.
- **Padding/cursor**: `contentPadding` = `lg`(16) horizontal / `md`(12) vertical — cursor never touches the
  container edge; `cursorColor`/`cursorWidth:2`/`cursorRadius` set. (Audit's "insufficient padding" was
  already resolved by COMPOSER-A.)
- **Keyboard/SafeArea**: full-screen route + scrollable body; no fixed height that breaks small devices.
- **Interaction**: draft persistence (`ComposerDraftStore`, secure storage) across close/reopen; publish CTA
  with a visible `publishing` state; **duplicate-submit guarded** (`if (publishing.value) return`);
  character limit is real (`_maxChars`, counter shown against a genuine limit); inline error near the CTA;
  retry without losing content (draft kept on failure).

## Change made this sprint
On successful create, the composer now also invalidates `userPostsProvider(myId)` so the owner's Activity
surface reconciles immediately (Stage 5). No visual redesign — the existing composer UX is preserved.

## Not done (deliberate, scope discipline)
No speculative rebuild of the composer chrome. If a future sprint adds media, the composer's action row is
the extension point (documented in MEDIA_ARCHITECTURE.md).
