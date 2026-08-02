# CONSOLE-SOCIAL-B — Enforcement Lifecycles

## User (Gateway `moderation_user_state`; enforced by EnsureCanAct + ViewFor)
```
                 suspend(days?)            ban
   ┌──────────┐ ───────────────▶ ┌───────────┐ ─────────▶ ┌────────┐
   │  active  │ ◀─── unsuspend ── │ suspended │            │ banned │
   └──────────┘                   └───────────┘ ◀─ unban ──└────────┘
        ▲                              │  (expiry: until<=now ⇒ derived active)
        └────────────── unban / unsuspend ──────────────────┘
```
- Allowed: active→suspended, active→banned, suspended→active, suspended→banned, banned→active (explicit unban), banned→suspended.
- No-op (same-state) transitions are idempotent (not errors). No "delete user".
- Expiry: suspension may carry `until` (days); an elapsed suspension reads as active everywhere (single derived evaluation in `UserState`/`EnsureCanAct`).
- Ban has NO expiry — reversal is an explicit Unban.

## Content — post & comment (Gateway `moderation_hidden_content`; enforced by ViewFor)
```
   ┌─────────┐ ── hide ──▶ ┌────────┐
   │ visible │ ◀─ restore ─│ hidden │
   └─────────┘             └────────┘
```
- Idempotent both directions. No physical delete. Operator investigation always sees hidden content.
- Thread integrity: hiding a parent comment removes it from consumer surfaces; replies are not cascade-hidden or fabricated.

## Agent (Social `agent_profiles.active`; enforced at post.Service.Create)
```
   ┌────────┐ ── deactivate ──▶ ┌──────────┐
   │ active │ ◀─ reactivate ────│ inactive │
   └────────┘                   └──────────┘
```
- Idempotent (durable history row only on a real transition). Inactive ⇒ publication rejected (`ErrAgentInactive`) at the single choke point every path funnels through.
- Historical content preserved. No ownership/user-linkage/delegation implied.

## Report (Gateway `moderation_reports.status`)
```
   open ──▶ reviewing ──▶ resolved
     │          │      └▶ dismissed
     └──▶ resolved / dismissed
   resolved/dismissed ──▶ reviewing   (re-open for correction)
```
- Destinations limited to reviewing|resolved|dismissed (open is only an initial state). Idempotent same-state.
- Report-driven enforcement records `report_id` on the moderation action; the operator may also transition the report (explicit correlation, no cross-DB atomicity).
