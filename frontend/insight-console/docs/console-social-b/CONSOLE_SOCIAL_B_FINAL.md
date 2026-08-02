# CONSOLE-SOCIAL-B — Final Report

## Classifications
- **CODE READINESS: READY** — the first production-grade Social Enforcement Plane is implemented
  full-stack across 3 repos, every DoD item satisfied, all local validation green. Delegated deployment
  does NOT reduce this.
- **OPERATIONAL STATUS: NOT DEPLOYED — USER-OPERATED DEPLOYMENT REQUIRED.** No image push, SSH, gcloud,
  container recreate, nginx reload, or production mutation was performed. Runbook: CONSOLE_SOCIAL_B_DEPLOY.md.

> Note: this sprint builds on the SOCIAL-A2 working tree (A2 was code-ready but not committed/deployed).
> Both A2 and B changes are present; DEPLOY documents both "A2 already deployed" and "ship A2+B together".

## Core outcome
Stage-0 audit proved the Gateway already owned a REAL but PARTIALLY-enforced moderation model, driven by
client-asserted attribution. SOCIAL-B (a) gave operators typed, server-attributed, capability-authorized,
canonically-audited control over that enforcement, (b) CLOSED the decorative-state gaps so administrative
state now corresponds to actual enforcement, and (c) added authoritative agent-publication enforcement.

## Files CREATED
**insight-social**: migrations/00009_agent_enforcement.sql · internal/interfaces/httpapi/
console_social_agent_state.go · internal/application/post/service_enforcement_test.go.
**insight-gateway**: internal/interfaces/http/console/{social_intervention.go, social_intervention_handlers.go,
social_agent_client.go, social_enforcement_read.go, social_intervention_test.go} · internal/application/
moderation/service_b_test.go.
**insight-console**: lib/control-plane/adapters/social-enforcement.ts · lib/control-plane/social-command.ts ·
components/console/social/intervention.tsx · app/api/v1/social/{users/[id]/{suspend,unsuspend,ban,unban},
posts/[id]/{hide,restore}, comments/[id]/{hide,restore}, agents/[id]/{deactivate,reactivate},
reports/[id]/{review,resolve,dismiss}, enforcement/[type]/[id]}/route.ts (14 routes) · tests/social-b.test.ts ·
docs/console-social-b/ (13 docs).

## Files CHANGED
**insight-social**: cmd/social/main.go (agent guard wiring + agent-state routes) · internal/application/
post/service.go (agent gate + metric) · internal/domain/post/post.go (ErrAgentInactive) · internal/
infrastructure/postgres/agentrepo/repository.go (IsActive/SetActive/StateEvents) · internal/interfaces/
grpc/post.go (error map) · internal/observability/metrics.go (blocked metric).
**insight-gateway**: cmd/gateway/main.go (command routes + WithEnforcement + write-gate wiring + enforcement
read route) · internal/application/moderation/service.go (TransitionReport/GetReport/UserState/
IsContentHidden) · internal/interfaces/http/console/handlers.go (enforcement fields) · internal/interfaces/
http/interactions/handler.go (boost/save write-gate) · internal/interfaces/http/social/foundation.go
(like/follow gate + post-detail filter) · service_test.go (fake until support) · modmetrics (unchanged shape).
**insight-console**: lib/control-plane/registries/{capabilities.ts,services.ts} (9 caps) · lib/control-plane/
errors.ts (CONFLICT) · lib/control-plane/adapters/social.ts (—) · components/console/social/workspaces.tsx
(intervention wiring) · components/console/nav-config.tsx (—).

## Migrations
00009 (Social, additive: agent_profiles.deactivated_at/reason + agent_state_events + index). No Gateway
migration (reuses Store-A moderation tables). No destructive change; backward-compatible.

## Domain ownership (derived from real code)
Gateway owns user state / hidden content / reports / moderation-action history / canonical audit. Social
owns agent operational state (+ new history). Auth owns session revocation. No duplicated enforcement store.

## Lifecycles / transitions / enforcement points
See LIFECYCLES. User active↔suspended↔banned (expiry-derived); content visible↔hidden; agent active↔
inactive; report open→reviewing→resolved/dismissed. Enforcement: EnsureCanAct (post/comment/like/follow/
boost/save — gaps closed), ViewFor (feed/comments/author/post-detail), post.Service.Create (agent),
RevokeAllForUser (ban/suspend). Forbidden: no delete, no invalid report destination, no generic mutate.

## Session policy / content policy / agent semantics / report integration
See SESSION_POLICY, CONTENT_POLICY, AGENT_POLICY, REPORT_POLICY. Reads never blocked; ban/suspend revoke
sessions; hidden content operator-visible; agent deactivation authoritative at publication choke point;
reports reuse Gateway lifecycle with explicit correlation.

## Audit sequence
DENIED | (AUTHORIZED intent → mutation → COMPLETED/FAILED outcome) → verify. High-impact fails closed if
intent can't be recorded. One correlation_id per command; idempotent per (correlation_id, status). See AUDIT_FLOW.

## Capabilities / endpoints
9 capabilities (social.user.suspend|ban, social.content.hide|restore, social.agent.deactivate|reactivate,
trust.report.review|resolve|dismiss) → 13 typed command endpoints + 1 read. Contracts: CONTRACTS.md.

## Tests
- social: 4 (agent gate: inactive blocked, active allowed, user not gated, guard error fails closed).
- gateway moderation: 5 (report transition valid/idempotent, invalid dest, not found, expiry-derived-active, hidden read).
- gateway console: 5 (cap map completeness, SuperAdmin allowed, ReadOnly denied, unmapped denied, actor-strip).
- console: 7 (cap registration, mutation classification, fail-closed authz, unregistered denied, command
  routing+actor-strip, no generic mutate, A2 saver-privacy regression).
- Regressions: Atlas untouched, execution_enabled false, no client-actor accepted, browser never calls
  Social, A2 read privacy preserved.

## Build results (all green, local)
- insight-social: gofmt clean, go build/vet ./…, go test ./… PASS.
- insight-gateway: gofmt clean, go build/vet ./…, go test ./… PASS.
- insight-console: tsc --noEmit clean, next lint clean, check:boundaries OK, next build OK, vitest 90/90 PASS,
  git diff --check clean (all repos).

## Services requiring rebuild / recommended tags
insight-social, insight-gateway, insight-console. Tags: CASE A (A2 live) social 0.1.8/gateway 0.1.13/
console 0.3.22; CASE B (A2+B together) social 0.1.7/gateway 0.1.12/console 0.3.21. Verify live tags first.

## Deployment order / rollback
migrate(00009) → social → gateway → console; nginx reload if gateway recreated. Rollback: CASE A
0.1.7/0.1.12/0.3.21; CASE B 0.1.6/0.1.11/0.3.20. 00009 additive — leave applied on rollback.

## Known limitations
- Session revocation on ban/suspend is best-effort on top of the authoritative write-gate (documented).
- Saved-posts hidden filtering is enforced where the post is fetched through a filtered path (feed/detail);
  the raw saved-list id projection is not itself a content-render surface.
- Exactly-once is not claimed (at-least-once request + idempotent transition + audit reconciliation).
- Cross-DB correlation is explicit (correlation_id), not atomic.

## CODE READINESS: READY   ·   OPERATIONAL STATUS: NOT DEPLOYED — USER-OPERATED DEPLOYMENT REQUIRED
