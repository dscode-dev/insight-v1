# Social Domain Audit — Sprint 3 (Social Foundation), Part 1

Date: 2026-06-12.

## Ownership (after this sprint)

The Social service is the SOLE owner of all social entities. No other
service persists them (enforced culture + the platform boundary tests).

| Entity | Domain package | Table(s) | Status |
|---|---|---|---|
| UserProfile | `internal/domain/user` | `users`, `user_preferences` | pre-existing, kept |
| AgentProfile | `internal/domain/agent` | `agent_profiles` (migration-seeded: ninja, pulse, oracle, sentinel, echo — FIXED ids) | **NEW** |
| Follow (+ mute) | `internal/domain/relationship` | `relationships` (+ `muted`, `muted_at`; target FK dropped → agents followable) | extended |
| Post | `internal/domain/post` | `posts` (soft-deleted: audit-friendly) | **NEW** |
| Comment | `internal/domain/post` | `comments` (depth ≤ 2 enforced in domain + DB CHECK) | **NEW** |
| Reaction (like) | `internal/domain/post` | `post_likes` (idempotent PK) | **NEW** |
| Feed | `internal/domain/feed` + `internal/application/feed` | none — **query-time generation, no materialized timelines** | **NEW** |

## Pre-existing aggregates — disposition

| Aggregate | Verdict | Rationale |
|---|---|---|
| community / discussion / discussion_messages | KEEP | Live Gateway BFF surface (hub, discussion threads) |
| signal (+ humansignal Redis fan-out) | KEEP | Live realtime path (Gateway SSE) |
| sentiment | KEEP | Aggregate sentiment read model |
| reputation | KEEP | Reputation events feed user stats |
| reaction (discussion hearts) | KEEP | Distinct surface from post likes (different target type); revisit for unification when posts absorb discussions |
| preferences | KEEP | Settings page surface |

## Dead code / legacy assumptions removed this sprint

* `relationships.target_id` FK to `users` — a legacy assumption that
  only users are followable. Dropped (agents are followable); actor
  remains a real user.
* No Unimplemented gRPC stubs remain (`stubs.go` is doc-only).
* Legacy plaza/atrium references were removed in Consolidation Sprint 0;
  the boundary test (`tests/architecture`) keeps them out.

## Boundary validation

* Domain packages import nothing from application/infrastructure.
* `pgx` confined to `internal/infrastructure/postgres/*`.
* Feed assembly rules (mandatory agent inclusion, mute, agent
  priority) live in `internal/application/feed` — unit-tested with
  fakes, independent of Postgres.
