# Azteca Y.5 — Comment Polish (Part 5)

## Posture

`post_thread_screen.dart` renders the root post + threaded replies via the same
`FeedItemShell`, so author emphasis, avatars and spacing already read as one
consistent, conversational language attached to the post. Thread model,
contracts and providers are untouched (as required).

## This sprint

- Motion layer animates entering/leaving a thread (replies feel attached as you
  navigate).
- Scroll-to-dismiss on the thread list + app-wide tap/nav keyboard dismissal
  (Azteca-X) keep the reply field from trapping the keyboard.
- Audit confirmed avatar consistency + reply grouping reuse the shared shell.

## Honest note

No thread-widget markup changed this sprint. A dedicated nested-reply
indentation affordance (depth lines / inset) is the clear next increment and is
documented as such — not claimed as done. Visual-only scope respected.
