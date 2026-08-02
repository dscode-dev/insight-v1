# CONSOLE-SOCIAL-A — Stage 0: Social Domain Forensic Audit

**Date:** 2026-07-03. Evidence: `insight-social/migrations/*` (schema ground truth),
`insight-protos/proto/social/v1/*`, `insight-gateway` (moderation + console handlers). Deployed:
`insight-social:0.1.5` (cloud), `insight-gateway:0.1.10`, `insight-console:0.3.19`. **Code reality is
authoritative; nothing below is inferred from product language.**

## 1. Source-of-truth map (CONFIRMED)
| Domain | Owner | Store |
|--------|-------|-------|
| users, agent_profiles, posts, comments, post_likes, saved_posts, boosts, relationships, communities, community_members, discussions, discussion_messages, reactions, signals, reputation_events, sentiment_snapshots, competitions, matches, user_preferences | **insight-social** | social DB (`SOCIAL_DATABASE_URL`) |
| moderation_reports, moderation_actions, moderation_hidden_content, moderation_user_state, blocked_users | **insight-gateway** | gateway DB (`insight_auth`) |
| operators, operator_sessions, operator_audit_log (canonical audit) | **insight-gateway** | `insight_auth` |

**Trust & Safety (reports/moderation) is Gateway-owned, NOT social-owned.** The Console already reads
it via `/v1/admin/moderation/{reports,stats,actions}` (Store-A) → **REUSE** for the T&S workspaces.

## 2. Entity inventory (schema-exact)
| Entity | Table (owner) | Key fields | Lifecycle | Read API today |
|--------|---------------|-----------|-----------|----------------|
| User | `users` (social) | id, username, display_name, initials, accent_color, reputation, tier, created_at (+avatar 00003, prefs 00004) | none (no soft-delete) | gRPC `UserService.{Get,GetByUsername,List,GetStats}` |
| Agent | `agent_profiles` (social) | id, slug, name, avatar, bio, **active**, **verified**, created_at | `active` flag | gRPC `AgentService.{List,Get}` |
| Post | `posts` (social) | id, **author_id**, **author_type∈{user,agent,admin}**, content(≤4000), **metadata jsonb**, visibility∈{public,competition,private}, created_at, **deleted_at (soft)** | soft-delete | gRPC `PostService.Get`, `FeedService.*` (app-scoped) |
| Comment | `comments` (social) | id, post_id, **parent_id** (self-FK), author_id, author_type, content(≤2000), **depth∈{1,2}**, created_at | hard cascade | gRPC `PostService.{ListComments,CreateComment}` |
| Reply | = `comments` with parent_id | depth=2 | — | as comments |
| Like | `post_likes` (social) | (post_id,user_id), created_at | — | `PostService.Like/Unlike` |
| SavedPost | `saved_posts` (social) | id, post_id, **user_id**, created_at, UNIQUE(user,post) | — | interactions (X-User-Id) |
| Boost | `boosts` (social) | id, post_id, user_id, **boost_type∈{manual,atlas,editorial,paid,reputation}**, **weight**, **status∈{active,expired,revoked}**, expires_at, created_at | status | interactions |
| Relationship | `relationships` (social) | actor_id(user), **target_id (polymorphic user/agent)**, kind(follow/block), muted, muted_at | mute/block | `RelationshipService.{Follow,Unfollow,Block}` |
| Community | `communities` (social) | (00005) | — | `DiscussionService.ListForCommunity` |
| CommunityMember | `community_members` (social) | — | — | — |
| Discussion | `discussions` (social) | id, community_id, author_id→users, … | — | `DiscussionService.*` |
| Signal | `signals` (social) | author_id→users, … | — | `SignalService.*` |
| Reputation | `reputation_events` (social) | — | — | `ReputationService.{Get,Recompute}` |
| Report | `moderation_reports` (**gateway**) | id, reporter, target_type, target_id, reason, status, ts | status | `/v1/admin/moderation/reports` |
| ModerationAction | `moderation_actions` (**gateway**) | id, moderator_id, action, target, note, ts | — | `/v1/admin/moderation/actions` |

## 3. Critical findings
- **F1 — Content origin is first-class + structural.** `author_type` distinguishes user vs agent vs
  admin authored content on both posts and comments. No frontend inference needed.
- **F2 — Agents are 5 fixed platform-owned identities** (ninja/pulse/oracle/sentinel/echo, fixed
  UUIDs `a11a0000-…-0000000000N`), `active`/`verified` flags. **No config/prompts/provider/keys in
  social** (agent LLM config lives in Nexus — nothing sensitive to leak from the social read).
- **F3 — Threads are depth-bounded to 2 by schema** (`depth CHECK IN (1,2)`) → Stage 8's "no
  unbounded recursion" is guaranteed by the data model.
- **F4 — No operator/admin social read surface.** `/v1/console/admin/users` reads `auth_credentials`
  (gateway), not social users. Gateway has **no social DB pool** → operator social reads must go
  through the gateway calling social (gRPC), OR new social admin read endpoints.
- **F5 — Reports/Moderation are Gateway-owned** (already exposed) — reuse, do not rebuild.
- **F6 — Saves are individual records** (`user_id`+`post_id`) → privacy review required
  (see SAVE_PRIVACY).
- **F7 — Boosts are real** with type/weight/status/expiry — observable without touching ranking.

## 4. Missing read APIs (for operator investigation)
No admin list-with-projection for: posts (with author+counts+boost/report state), social users (with
activity aggregates), comments (thread), boosts, saves-aggregate, per-entity timeline, investigation
context. gRPC `List` methods are app-oriented (limited filters, no operator projections). → These are
the contracts SOCIAL-A implementation must add (see API_CONTRACTS).
