# ADR-0007 — Official (Ninja) identity via explicit delegation; never silent impersonation

**Status:** Proposed (model deferred to a dedicated future sprint)

**CURRENT STATE:** No official-identity, ownership, or delegation model exists. The only actor
primitive is `permissions.actorOf()` → `"Name (id)"`. Ninja exists conceptually as the primary
platform identity but has no user↔agent↔operator relationship in code.

**PROBLEM:** The platform wants authorized operators to act **as** the official Ninja identity
(publish official posts/comments) while preserving the real operator in audit. A naive
implementation would let SuperAdmin invisibly become any user — unacceptable.

**DECISION:** When implemented (future sprint), official actions use **explicit dual attribution**:
```
public_actor: ninja_user          # what the public sees
executed_by:  owner:<operator-id> # the real operator (audit)
origin:       insight-console
operation_id: <operation-id>
```
The public surface may render the action as Ninja **only when authorization + delegation permit**;
internal audit **always** preserves the real operator. **No silent impersonation. No "become any
user".** Delegation is capability-gated (`social.official_identity.publish`), dual-controlled for
first use, and fully audited.

**RATIONALE:** Satisfies the product need (official voice) without destroying accountability.
Separates *public actor* from *executing actor* as first-class, audited fields.

**MIGRATION IMPACT:** Requires the identity/ownership model (users, official identities, agents,
operator ownership) — a dedicated sprint (CONSOLE-IDENTITY-A). This ADR fixes the **shape** so
earlier sprints don't foreclose it (audit events already carry `operator_id`; add `public_actor`).

**RISKS:** Highest-abuse capability on the platform (mitigate: dual-control, break-glass, loud
audit, no impersonation of arbitrary users — only the designated official identity).
