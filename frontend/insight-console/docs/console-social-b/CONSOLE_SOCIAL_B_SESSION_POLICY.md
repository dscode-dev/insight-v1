# CONSOLE-SOCIAL-B — Session & Authentication Policy

## Authoritative enforcement = the Social mutation boundary
`moderation.EnsureCanAct(userID)` gates every participation mutation (post, comment, like, follow,
boost, save). It is **fail-closed**: a moderation-store error blocks the mutation
(`moderation_check_failed`). This guarantee does NOT depend on session state — even a user holding a
live, valid session cannot participate while banned/suspended.

Coverage after SOCIAL-B (gaps from Stage 0 closed):
- post ✓ comment ✓ (pre-existing) · like ✓ follow ✓ boost ✓ save ✓ (added).
- Reductive actions (unlike/unfollow/unboost/unsave/mute) are intentionally NOT blocked.

## Session effect of ban/suspend
Ban and suspend additionally call `RefreshSessionRepo.RevokeAllForUser(userID)` — the authoritative
end-user session store — so a non-active user is force-logged-out and cannot ride an indefinite
session. This is best-effort **on top of** the authoritative write-gate: if revoke fails, the write-gate
still blocks all participation. Re-authentication after unban/unsuspend is allowed by the auth layer
(no separate re-auth block is added).

## Reads / public browsing
NOT blocked for suspended/banned users — enforcement targets participation, not consumption. `ViewFor`
already hides a non-active user's content from *others*; it does not blind the user. Their own content
is excluded from consumer surfaces (author-hidden) but preserved and operator-visible.

## Deliberately NOT done
- No synchronous Social→Gateway call added to every request (Gateway already fronts Social and holds
  enforcement state).
- No distributed-consistency dependency. Stale-session risk is bounded by the authoritative write-gate.
- Fail-closed on the write-gate; fail-open on the read filter (never break the feed on a filter error).
