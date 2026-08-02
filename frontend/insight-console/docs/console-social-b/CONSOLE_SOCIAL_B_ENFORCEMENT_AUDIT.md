# CONSOLE-SOCIAL-B — Stage 0 Enforcement Semantics Audit

Derived from the real code (not assumed). This audit is the foundation for every
Stage 1+ decision. Baseline: social 0.1.7 / gateway 0.1.12 / console 0.3.21 code targets.

## TL;DR — the enforcement plane already partly exists (and is partly decorative)

The Gateway (Store-A) already owns a **real, enforced** moderation model. SOCIAL-B does
NOT invent enforcement state — it (a) gives operators *typed, attributed, capability-authorized,
canonically-audited* control over the existing state, and (b) **closes the decorative gaps**
where administrative state does NOT correspond to actual enforcement.

### What already exists and IS enforced
- `moderation_user_state(user_id, state ∈ active|suspended|banned, until, updated_at)` — Gateway-owned.
- `moderation_hidden_content(target_type ∈ post|comment, target_id, hidden_at)` — Gateway-owned.
- `moderation_reports(status ∈ open|reviewing|resolved|dismissed)` — Gateway-owned.
- `moderation_actions(report_id?, moderator_id, action, target, note, created_at)` — durable Gateway action log.
- `moderation.Service.EnsureCanAct(userID)` → `ErrUserBanned`/`ErrUserSuspended`; suspension expiry is
  **derived** (`until == nil || until.After(now)`), so an elapsed suspension is effectively active.
- `moderation.Service.ViewFor(viewer)` → per-request filter lens (blocked authors + globally
  non-active users + admin-hidden posts/comments) applied to proxied Social responses.
- `agent_profiles.active` (Social-owned) column exists.
- `RefreshSessionRepo.RevokeAllForUser(userID)` — session-revocation primitive exists.
- Operator permission model (`console/roles.go`): SuperAdmin already carries `user.suspend`,
  `user.ban`, `user.force_logout`, `user.invalidate_sessions`, `feed.hide`, `feed.delete`, `feed.restore`.
- Console `Permission` type already includes those. Console capability registry already has
  `social.moderation.read` / `social.content.moderate` and A2 `trust.*` read caps.

### What is DECORATIVE / gaps (administrative state without real enforcement)
1. **Write-gate coverage is partial.** `EnsureCanAct` is called ONLY on `CreatePost`
   (foundation.go:366) and `CreateComment` (foundation.go:446). A banned/suspended user can still:
   **Like** (`toggleLike`), **Follow** (`relationshipAction`), **Boost** & **Save**
   (`interactions.Handler.proxyPost` just forwards `X-User-Id`, no gate).
2. **Read-filter coverage is partial.** `ViewFor` filtering is applied ONLY to the feed
   (`serveFeed`) and comments (`ListComments`). Hidden/banned content still surfaces via:
   **single post detail** (`GetPost`), **author/profile posts** (`serveAuthorPosts`),
   **agent posts**, **saved posts** (`interactions` saved list).
3. **Agent deactivation is fully decorative for publication.** Nexus `PublishAgentPost` →
   Social gRPC `PostServer.Create` → `post.Service.Create` → `InsertPost` **never checks
   `agent_profiles.active`.** Setting `active=false` does NOT stop an agent from publishing.
4. **Ban/suspend does not revoke sessions.** `RevokeAllForUser` exists but is never called by
   moderation; a banned user keeps a live session until it expires (mutations are blocked only
   at write time, and only on the two gated paths).
5. **Operator attribution is client-asserted.** `POST /v1/admin/moderation/actions` takes
   `moderator_id` from the request body (`ActDTO.ModeratorID`); Console `lib/moderation.ts`
   sends it from the client. There is no server-derived operator identity and no canonical
   (SECURITY-A1 `operator_audit_log`) audit for moderation actions — only the domain
   `moderation_actions` row.
6. **No typed per-action operator contracts.** Only a single generic
   `POST /admin/moderation/actions {action:"..."}` gated by service-token (`requireConsole`),
   not by operator session + capability.
7. **No operator control for report `open→reviewing`** (only auto-resolve/dismiss as a side effect of Act).
8. **Investigation read models (A1/A2) don't surface enforcement state** (no user state, no hidden
   flag, no agent operational state, no enforcement history on entity detail).

## Domain ownership decision (final)

| Concern | Owner | Store | Rationale |
|---|---|---|---|
| User enforcement state (active/suspended/banned + expiry) | **Gateway** | `moderation_user_state` | already owned + enforced; reuse, do not duplicate in Social |
| Content hidden state (post/comment) | **Gateway** | `moderation_hidden_content` | already owned + filtered; reuse |
| Reports lifecycle | **Gateway** | `moderation_reports` | already owned; reuse |
| Moderation action history (user/content/report) | **Gateway** | `moderation_actions` | already the durable log; reuse |
| Canonical administrative audit (all interventions) | **Gateway** | `operator_audit_log` (SECURITY-A1) | correlate every intervention |
| Agent operational state + history | **Social** | `agent_profiles.active` (+ new additive `agent_state_events`) | agents are Social-owned entities |
| End-user session revocation | **Gateway (auth)** | `refresh_sessions` via `RevokeAllForUser` | authoritative session store |

**Consequence:** SOCIAL-B adds **no** duplicate user/content enforcement store. It adds only a
Social-owned agent state-history table (additive) and correlates everything via `correlation_id`
in the canonical audit. Cross-database consistency is **explicit correlation**, not a distributed
transaction.

## Per-intervention specification

### USER: suspend / unsuspend / ban / unban
- CURRENT OWNER: Gateway `moderation_user_state`.
- STATE MODEL: `active | suspended(until?) | banned`.
- TRANSITIONS (allowed): active→suspended, active→banned, suspended→active (unsuspend),
  suspended→banned (escalate), banned→active (explicit unban), banned→suspended (de-escalate, allowed).
- FORBIDDEN: no-op transitions are idempotent (return current), not errors; there is no "delete user".
- ENFORCEMENT POINTS: `EnsureCanAct` on ALL Social create/mutation paths (post, comment, like,
  follow, boost, save — SOCIAL-B closes like/follow/boost/save); `ViewFor` hides non-active authors' content.
- SESSION EFFECT: **ban** and **suspend** revoke active sessions via `RevokeAllForUser`
  (force logout). Re-auth after unban/unsuspend is allowed by the auth layer (no separate block added).
- CONTENT EFFECT: existing content of a non-active user is hidden from consumer reads by `ViewFor`
  (author-hidden); it is NOT deleted; operator investigation still sees it.
- REVERSIBILITY: fully reversible via unsuspend/unban.
- EXPIRY: suspension supports `until` (days); derived-active after expiry. Ban has no expiry (explicit unban).
- REASON: mandatory (recorded in `moderation_actions.note` + canonical audit `reason`).
- AUDIT: `moderation_actions` (domain) + `operator_audit_log` (canonical, intent→outcome).
- CROSS-SERVICE: none synchronous; Social reads reflect state only through Gateway's `ViewFor` post-filter.

### CONTENT: hide / restore (post, comment)
- OWNER: Gateway `moderation_hidden_content`.
- STATE: `visible | hidden`. Transitions visible↔hidden, idempotent.
- ENFORCEMENT: `ViewFor` excludes hidden posts/comments from consumer reads (SOCIAL-B extends to
  post-detail, author posts, saved posts). No physical delete.
- THREAD INTEGRITY: a hidden parent comment is removed from the consumer list; because Social
  keyset/threading is by `parent_id`, replies whose parent is hidden are represented truthfully
  (parent excluded from the consumer projection; operator projection still shows it). We do NOT
  fabricate deleted text and do NOT cascade-hide replies (each is hidden explicitly).
- REASON: mandatory. AUDIT: domain + canonical.

### AGENT: deactivate / reactivate
- OWNER: Social `agent_profiles.active` (+ new `agent_state_events` history, additive).
- STATE: `active | inactive`. Transitions active↔inactive, idempotent.
- ENFORCEMENT POINT (NEW, authoritative): `post.Service.Create` rejects `author_type=agent` when the
  agent is inactive (`ErrAgentInactive`) — this is the single choke point every publication path
  (Nexus, any worker) funnels through (all call `PostServiceClient.Create`).
- HISTORICAL CONTENT: preserved; not deleted; not hidden by deactivation (hide separately if needed).
- NO ownership/user-linkage/delegation implied (IDENTITY-A stays out of scope).
- REASON: mandatory. AUDIT: `agent_state_events` (Social) + canonical (Gateway).

### REPORT: review / resolve / dismiss
- OWNER: Gateway `moderation_reports`.
- STATE: `open | reviewing | resolved | dismissed` (existing vocabulary — reused, none invented).
- TRANSITIONS: open→reviewing, open→resolved, open→dismissed, reviewing→resolved, reviewing→dismissed,
  and (re-open) resolved/dismissed→reviewing allowed for correction.
- CORRELATION: a report-driven enforcement (e.g. hide/ban) records `report_id` on the action and,
  where the operator chooses, transitions the report — explicit correlation, no cross-DB atomicity.
- AUDIT: domain `moderation_actions` (dismiss) / status change + canonical.

## Session & authentication policy (Stage 3 answer)
- Enforcement is **authoritative at the Social mutation boundary** via `EnsureCanAct` (fail-closed:
  a moderation-store error blocks the mutation with `moderation_check_failed`). This is the primary
  guarantee and does not depend on session state.
- Administrative **ban/suspend additionally revokes active sessions** (`RevokeAllForUser`) so a
  non-active user cannot continue an indefinite session. This is best-effort on top of the
  authoritative write-gate (if revoke fails, the write-gate still blocks mutations).
- **Read / public browsing is NOT blocked** for suspended/banned users (policy: enforcement targets
  participation, not consumption) — matching the existing `ViewFor` design (hides *their* content
  from *others*, does not blind them). Documented in SESSION_POLICY.
- We do NOT add a synchronous Social→Gateway call into every request. Gateway is the single place
  that holds enforcement state and already sits in front of Social.

## Enforcement gaps SOCIAL-B will close (to make state non-decorative)
1. `EnsureCanAct` added to Like, Follow, Boost, Save.
2. `ViewFor` filtering added to single post detail, author/profile posts, agent posts, saved posts.
3. Agent `active` enforced at `post.Service.Create` (authoritative publication choke point).
4. Ban/suspend revoke sessions (`RevokeAllForUser`).
5. Operator identity server-derived (never body) on all interventions + canonical audit intent→outcome.
6. Typed per-action operator endpoints (capability-authorized, operator-session-gated).
7. Operator report `review` transition.
8. Enforcement state surfaced in investigation read models.
