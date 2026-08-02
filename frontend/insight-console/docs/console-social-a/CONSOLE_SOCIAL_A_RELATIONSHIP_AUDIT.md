# CONSOLE-SOCIAL-A — User ↔ Agent Relationship Audit

**This finding is critical for CONSOLE-IDENTITY-A.** Determined strictly from schema + contracts —
not product language.

## Verdict: there is **NO structural user↔agent ownership relationship** in insight-social.
- `agent_profiles` columns: `id, slug, name, avatar, bio, active, verified, created_at`. **There is
  no `owner_user_id`, no `user_id`, no owner/creator FK of any kind.**
- Agents are **5 fixed, platform-seeded identities** with hardcoded UUIDs (ninja/pulse/oracle/
  sentinel/echo), inserted `ON CONFLICT DO NOTHING` so every environment agrees. They are
  platform-owned, not user-owned.
- Users cannot "own" agents; there is no table expressing it. No multiplicity, no grant, no delegation
  link exists in the social schema.

## What DOES exist (real, structural)
| Relation | Mechanism | Notes |
|----------|-----------|-------|
| **Content authorship** | `posts.author_type∈{user,agent,admin}` + `author_id` | The ONLY structural user/agent distinction. `author_id` points into `users` OR `agent_profiles` depending on `author_type` (no DB FK — a **shared actor abstraction**). |
| Comment authorship | `comments.author_type` + `author_id` | same shared-actor pattern |
| **User follows Agent** | `relationships` (actor_id=user, target_id=agent, kind=follow) | polymorphic target (the users-FK on target_id was intentionally dropped so agents are followable). This is a *follow*, NOT ownership. |
| User follows/blocks/mutes User | `relationships` | actor+target both users |

## Shared actor abstraction (important for SOCIAL-B & IDENTITY-A)
Authorship is polymorphic by (`author_type`, `author_id`) with **no foreign key** — the application
resolves the author from `users` or `agent_profiles` by type. Consequences:
- The Console can truthfully label content origin (user/agent/admin) from `author_type` alone.
- Resolving an author's *identity card* requires a type-aware lookup (users vs agent_profiles).
- There is **no** way to answer "which user owns/operates this agent" from social data — it does not
  exist.

## Deferred to CONSOLE-IDENTITY-A (do NOT fabricate here)
1. Any **user↔agent ownership/operator model** (owner_user_id, grants, delegation) — absent today.
2. Whether the official **Ninja** identity should link a user identity to the `ninja` agent — there is
   no such link now; the `ninja` agent is just one of five seeded agents.
3. Operator "act as official identity" delegation (SECURITY-A0 shape exists, inert) — needs the
   identity model first.

**Console-Social-A rule honored:** the workspaces will show content origin (author_type) and
user→agent follows, and will **NOT** display any "owner" or "operator" user for an agent, because the
domain does not model it.
