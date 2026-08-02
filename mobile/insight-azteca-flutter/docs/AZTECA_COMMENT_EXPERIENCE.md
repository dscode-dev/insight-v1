# Azteca Comment Experience (Azteca-Y Part 4)

## State (`post_thread_screen.dart`)

The thread renders the root post + threaded replies (`state.threaded`) reusing
the same `FeedItemShell` (consistent avatars, spacing, author emphasis) so
comments read as a continuation of the post rather than a separate widget
language. `reply_preview.dart` attaches the parent context to a reply.

## This sprint

- **Keyboard**: the thread `ListView` dismisses on drag
  (`ScrollViewKeyboardDismissBehavior.onDrag`, Azteca-X) — the reply field never
  traps the keyboard; combined with the app-wide tap/nav dismissal.
- **Motion**: entering/leaving a thread uses the global page transition (Part 6),
  so replies feel attached as you navigate in/out.

## Audit + restraint

Author emphasis, avatar consistency and reply grouping reuse the shared shell
(verified in `AZTECA_VISUAL_AUDIT.md`). Deeper nested-reply indentation styling
is flagged as the next increment; this pass prioritized the verifiable
interaction + consistency layer over an unverifiable visual reflow, keeping the
conversational-but-Insight tone.
