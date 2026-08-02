# CONSOLE-SOCIAL-A1 — Final Report

**Date:** 2026-07-04 · **Classification: `READY`**

## 1. Final classification — READY
The full A1 vertical slice is implemented across three repos, deployed to both environments, and
live-validated against production Social data. The Console is now a real Social investigation surface:
Overview, Activity, Users, User Detail, Agents, Agent Detail, Posts, Post Detail — all backed by real
data, behind the operator security boundary, with the browser never touching Social.

## 2. Executive result
Operators authenticate → the Console BFF resolves OperatorContext + authorizes a `social.*.read`
capability → a typed Social adapter calls the Gateway (`/v1/console/social/*`) → the Gateway
(operator-session authed) proxies to the internal Social read plane → Social computes projection
queries (no N+1) over its own DB. author_type origin is preserved end-to-end; agents show no owner
(no fabricated user↔agent link); saves are aggregate-only; failures are honestly distinguished.

## 3. Files created
- insight-social: `internal/interfaces/httpapi/console_social.go` (8 read handlers).
- insight-gateway: `internal/interfaces/http/console/social_proxy.go` (SocialConsoleProxy).
- insight-console: `lib/control-plane/adapters/social.ts`, `lib/control-plane/social-bff.ts`,
  `components/console/social/workspaces.tsx`, 8 BFF routes (`app/api/v1/social/**`), 8 pages
  (`app/(console)/social/**`), `tests/social-adapter.test.ts`, docs (7).

## 4. Files changed
- insight-social `cmd/social/main.go` (register 8 routes).
- insight-gateway `console/handlers.go` (socialHTTP field + NewHandlers param), `cmd/gateway/main.go`
  (NewHandlers call + 8 proxy routes).
- insight-console `registries/{capabilities,services}.ts` (6 capabilities), `components/console/nav-config.tsx` (Social group).

## 5. Contracts / 6. Endpoints
See CONTRACTS.md. 8 social read endpoints + gateway proxy + console BFF; moderation/reports reuse
existing Gateway contracts (not in A1 slice). No mutation endpoints.

## 7. DB migrations/indexes
**None.** Read-only over existing schema + existing indexes (QUERIES.md).

## 8. Capabilities
Added social.overview.read / social.activity.read / social.user.read / social.agent.read /
social.post.read / social.comment.read (evidence-backed; permission-mapped; enforced by authorize()).

## 9. Adapter
`SocialControlPlane` — resource-split readers (overview/activity/users/agents/posts), adminFetch seam,
canonical error normalization, correlation propagation, no service token to browser.

## 10-17. Workspace results (all real, deployed, live-smoked)
Overview (real totals + author_type distribution + honest unavailable list, no fake deltas) · Activity
(projection over durable rows, drill-down, provenance labelled) · Users (list + search + counts, no
N+1) + User Detail (identity/content/relationships/recent posts) · Agents (5 seeded, status) + Agent
Detail (owner=none platform) · Posts (list + author_type/boosted filters + counts) + Post Detail
(resolved author, engagement, boosts, depth-≤2 comments with resolved authors).

## 18. author_type end-to-end — verified (posts_by_user 14 / agent 0; UI author-type chips + colored).
## 19. user↔agent — no ownership fabricated (agent detail owner "none (platform)").
## 20. comments — depth-bounded (schema depth∈{1,2}); root+replies, no recursive infra.
## 21. save privacy — aggregate save_count only; no saver identities.

## 22. Test results
Console `tsc`/`lint`/`check:boundaries`/`build` clean; **vitest 77 pass** (+8 social: adapter error
mapping, capability/authorization). Gateway + Social `go build`/`vet`/`test ./...` pass. `git diff
--check` clean.

## 23-24. Images / deploy
social 0.1.6, gateway 0.1.11 (cloud), console 0.3.20 (Robozão, digest sha256:4e9b472f…). Rollback:
social 0.1.5, gateway 0.1.10, console 0.3.19. See DEPLOY.md. restarts=0 everywhere; nginx reloaded.

## 25. Live smoke (SMOKE.md)
Cloud: unauth→401; overview/agents(5 incl ninja)/users/posts/post-detail return REAL data; author
resolved; author_type preserved; invalid filter→200 (ignored); invalid uuid→400; unauthorized→401.
Robozão: console social routes gated (BFF 401 / page 307 login with deep-link). No data mutated;
temporary admin session deleted.

## 26. Query plans / latency
Small volume (posts 14). Projections index-backed; EXPLAIN-at-scale is a follow-up (QUERIES.md).

## 27. Rollback versions
social 0.1.5 (ea7690ced9fe) · gateway 0.1.10 (482a0ff38ca3) · console 0.3.19 + `.pre-social-a1`
compose backups on both hosts.

## 28. Known limitations
- Communities/relationships/reports workspaces are out of the A1 slice (SOCIAL-A design; SOCIAL-A2/B).
- Cursor pagination is wired end-to-end for users/posts; activity uses time-ordered limit (no cursor).
- Full authenticated browser UI flow not driven (no operator creds in harness) — layers validated
  independently.
- Moderation correlation on posts not shown in A1 (Gateway-owned; SOCIAL-B).

## 29. Capabilities available for SOCIAL-B
Read plane + capability/authz/audit foundation established. B can add capability-gated, canonically-
audited (SECURITY-A1) interventions: content hide/restore, user suspend/ban (gateway moderation
tables), agent activate/deactivate (`agent_profiles.active` exists) — each reusing the operator-bound
proxy pattern with a mutation contract.

## 30. Backend contracts missing for SOCIAL-B
Social admin WRITE endpoints (agent active toggle; content moderation-state), gateway operator-authed
mutation proxies with canonical audit emission, per-action Social capabilities + dual-control for
destructive actions.

## 31. Identity questions deferred to CONSOLE-IDENTITY-A
No user↔agent ownership exists (confirmed live). IDENTITY-A must decide whether to add owner/operator
modelling, whether official Ninja links a user to the `ninja` agent, and formalize the shared-actor
(author_type,author_id) resolution into an Identity service.

---
**Verdict:** a real, deployed, live-validated Social read plane — real data, proper admin contracts,
operator security boundary, no browser→Social, no fabricated metrics/relationships, honest partial
states, author_type preserved, saves aggregate-only, Atlas untouched, zero mutation. READY; SOCIAL-B
can add interventions without redesigning this observability.
