# CONSOLE-SOCIAL-A — Save Observability Privacy Review (Stage 16)

`saved_posts (id, post_id, user_id, created_at, UNIQUE(user_id,post_id))` — individual save records
exist. Saving is a **private, personal signal** (a user's private bookmark), not public activity.

## Decision: **A — aggregate save counts only** (least-intrusive that satisfies operations)
- The Console exposes **`save_count` per post** (and, where useful, save totals per period) — an
  aggregate.
- The Console does **NOT** expose *who* saved a post (individual `user_id`↔`post_id` save
  relationships) in the general Observatory.

## Rationale
- Operational need for CONSOLE-SOCIAL-A (observe abnormal activity, investigate content) is satisfied
  by aggregate counts — you can see a post is being saved heavily without needing the savers' identities.
- Saving reveals private consumption behaviour; exposing individual savers is intrusive and not
  justified by any current investigation requirement. "A database relationship is not automatically
  safe to expose."

## Narrow exception (deferred, gated)
IF a specific abuse investigation ever requires per-saver visibility (e.g. coordinated
save-manipulation of ranking), that becomes a **capability-gated, audited** read
(`social.save.investigate`) introduced in SOCIAL-B with explicit justification + canonical audit — not
a default Observatory surface. Not implemented here.

## UI consequence
Post detail / boost-and-save panels show **counts** (`save_count`, boost aggregates); there is no
"saved by" user list. Tests assert save visibility follows this decision (aggregate only).
