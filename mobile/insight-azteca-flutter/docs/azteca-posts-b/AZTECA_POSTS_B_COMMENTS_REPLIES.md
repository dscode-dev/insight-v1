# AZTECA-POSTS-B — Comments & Replies

## Current state (SOCIAL-A, verified — no regression this sprint)
- Create comment/reply → `POST /v1/posts/{id}/comments` (real, depth-capped 1..2 by backend CHECK).
- Reply context indicator + cancel-reply + target identity (real user/agent identity resolution via
  getUser/getAgent) preserved.
- `comment_count` reconciled authoritatively via `feed_provider.setCommentCount` (backend count, not a
  client-only increment).
- Collapse/expand reply tree + Semantics preserved.

## Input ergonomics
The comment input already has multiline behavior, keyboard-aware layout, sending state, and preserves text
on failure (mirrors the composer's authoritative pattern). Internal padding is consistent with the design
system spacing. No redesign of the Comments screen (per scope).

## Not done (deliberate)
No comment-input rebuild beyond verification — the existing SOCIAL-A implementation meets the V1 bar
(backend-derived counts, no fake local increments surviving failed requests, real identity). Any residual
padding polish is low-risk cosmetic and out of the correctness scope of this sprint; flagged for CERTIFY-A.

## Guarantee
comment_count never increments purely on the client for a failed request; the reply tree remains
depth-capped by the backend schema; identity resolution is unchanged.
