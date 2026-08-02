# AZTECA-PROFILE-B — Public Profile Consistency

## Shared architecture (preserved)
Own + public profiles share the Sports Identity architecture: `sportsProfileProvider(userId)` +
`userPostsProvider(userId)` + canonical `FeedItem` renderer + `SportsProfileHeader`. This sprint did not
diverge them — only the OWN profile gained an Edit button (→ real form) and the OWN Activity/completeness
tweaks. Public profile rendering is unchanged.

## Consistency after an edit
Feed author labels are a live `LEFT JOIN users` (not denormalized), and avatars are versioned. So a user who
edits their display name/avatar renders coherently when opened from Feed author / Post Detail / Comment author
/ direct public profile — each surface re-reads the authoritative name (invalidated providers) or live JOIN.

## Owner-only vs public controls (verified)
- Owner profile: Edit (→ form), Settings, avatar shortcut, completeness card (owner-only).
- Public profile: follow/unfollow (real), report/block (real, Store-A) — **no Edit/Settings/completeness leak**.
- Messaging: NOT implemented (honestly absent, not a fake-disabled button).

## Status: READY
Public profile stays consistent and owner-only controls never leak to another user's profile.
