# CONSOLE-SOCIAL-A2 — Final Report

## Two classifications
- **CODE READINESS: READY** — full-stack investigation plane implemented across 3 repos, all local
  validation green. Delegated deployment does NOT reduce this.
- **OPERATIONAL STATUS: NOT DEPLOYED — USER-OPERATED DEPLOYMENT REQUIRED.** No image push, SSH,
  gcloud, container recreate, or nginx reload was performed. Runbook in CONSOLE_SOCIAL_A2_DEPLOY.md.

## What shipped (10 domains)
Comments & Replies Observatory · Communities Observatory · Relationship Explorer · Reports
Investigation (Gateway-owned) · Moderation History (Gateway-owned, distinct from audit) · Boost
Observability · Save Aggregate Observability (aggregate-only) · cross-domain Investigation Workspace ·
Correlated Administrative Timeline (provenance-tagged) · cross-entity navigation.

## Boundaries honored
Read-only (no ban/hide/remove/agent-toggle/impersonation/delegation). Source split authoritative
(Social owns users/agents/posts/comments/communities/memberships/relationships/follows/boosts/saves;
Gateway owns reports/moderation/operator sessions/audit). No browser cross-domain join — correlation
is server-side (InvestigationService/TimelineService). Atlas 1.0.0 untouched. execution_enabled false.

## Mandatory semantic correction — DONE
A1 `owner: none (platform)` removed. Agent detail now `identity_type: platform_agent`, no owner field
in schema, model, contract, or UI. user→agent follow shown as follow only. user↔agent identity remains
deferred to CONSOLE-IDENTITY-A. No owner_user_id/managed_by/linked_user_id created.

## Privacy — backend-enforced
Saves aggregate-only (save_count); no saver-identity endpoint/adapter/read-model exists; regression
test asserts no saver reader. No fabricated metrics/scores/relationships.

## Validation
- Console: 83 tests pass; tsc, lint, check:boundaries, next build clean; git diff --check clean.
- Gateway: go build, vet, test pass.
- Social: go build, vet, test pass.
- No migrations (additive, existing indexes).

## Images to rebuild (user)
insight-social 0.1.6→0.1.7 · insight-gateway 0.1.11→0.1.12 · insight-console 0.3.20→0.3.21.
Rollback: 0.1.6 / 0.1.11 / 0.3.20 (no migration rollback).

## Docs
DELTA, CONTRACTS, INVESTIGATION, TIMELINE, PRIVACY, QUERIES, SECURITY, DEPLOY, SMOKE, FINAL.
