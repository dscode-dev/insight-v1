# CONSOLE-ARCHITECTURE-A — Stage 3: Control Plane Capability Gap Analysis

Every capability the Human Control Plane must eventually provide, classified against **today's
reality** (code + live topology).

**Status key:** `EXISTS_AND_USABLE` · `EXISTS_BUT_READ_ONLY` · `EXISTS_BUT_FRAGMENTED` ·
`PREVIEW_ONLY` · `BACKEND_CONTRACT_MISSING` · `CONSOLE_INTEGRATION_MISSING` ·
`NOT_IMPLEMENTED_ANYWHERE` · `OUT_OF_SCOPE_V1`.

---

## PLATFORM
| Capability | Status | Evidence |
|-----------|--------|----------|
| Service health (cloud) | EXISTS_AND_USABLE | gateway `/v1/console/platform/health` (real probes) |
| Service health (robozão) | EXISTS_AND_USABLE | robozao-gateway `/operations/status` (OperationsService) |
| Environment/topology registry | BACKEND_CONTRACT_MISSING | topology is hardcoded in `operations-adapters.ts` |
| Dependencies graph | EXISTS_BUT_FRAGMENTED | hardcoded `SERVICE_META.deps`, not service-reported |
| Metrics | EXISTS_BUT_FRAGMENTED | robozão counters real; cloud metrics minimal |
| Logs | BACKEND_CONTRACT_MISSING | no log-access contract exposed to Console |
| Current activity | EXISTS_BUT_FRAGMENTED | derived from counters + static `state` strings |
| Incidents | PREVIEW_ONLY | "Incidents" tab is derived, no incident store |
| Platform operations (execute) | PREVIEW_ONLY | Operation domain = JSON file, `execution_enabled:false` |

## SOCIAL
| Capability | Status | Evidence |
|-----------|--------|----------|
| Reports / moderation queue | EXISTS_AND_USABLE | gateway `/v1/admin/moderation/{reports,stats,actions}` |
| Moderate content (remove/restore/mark) | EXISTS_AND_USABLE | `POST /v1/admin/moderation/actions` (feed.hide/restore) |
| Suspend / ban user | EXISTS_AND_USABLE (narrow) | moderation actions suspend_user/ban_user (user.suspend/ban) |
| Post/comment/reply inventory (admin) | BACKEND_CONTRACT_MISSING | social gRPC is app-facing; no admin list-all |
| Likes/saves/boosts visibility (admin) | BACKEND_CONTRACT_MISSING | interaction states are per-user, not operator-queryable |
| Communities administration | BACKEND_CONTRACT_MISSING | DiscussionService has no admin CRUD |
| Follows/relationships (admin view) | BACKEND_CONTRACT_MISSING | RelationshipService is actor-scoped |
| Content origin (human vs agent) | EXISTS_BUT_FRAGMENTED | agent/author distinguishable via AgentService, not surfaced for ops |
| Official / manual publishing | CONSOLE_INTEGRATION_MISSING (Social) / EXISTS (Nexus) | Nexus publishes agent posts; no "official Ninja" path |
| Agent-generated content controls | BACKEND_CONTRACT_MISSING | no admin toggle on agent posting |

## IDENTITY
| Capability | Status | Evidence |
|-----------|--------|----------|
| User read | EXISTS_BUT_READ_ONLY | gateway `/v1/console/admin/users` |
| Operator read | EXISTS_BUT_READ_ONLY | `/v1/console/admin/operators` |
| Session read | EXISTS_BUT_READ_ONLY | `/v1/console/admin/sessions` |
| Force logout / invalidate sessions | BACKEND_CONTRACT_MISSING | permission exists (`user.force_logout`), no route |
| Change operator permissions/roles | BACKEND_CONTRACT_MISSING | permission exists, no mutation route |
| Official identity (Ninja) | NOT_IMPLEMENTED_ANYWHERE | no official-identity/ownership/delegation model |
| Operator→identity delegation | NOT_IMPLEMENTED_ANYWHERE | only `actorOf()` string exists |

## AGENTS
| Capability | Status | Evidence |
|-----------|--------|----------|
| Registry / list / get | EXISTS_BUT_READ_ONLY | social `AgentService.List/Get`, `/v1/agents` |
| Activation state | BACKEND_CONTRACT_MISSING | no activate/deactivate RPC |
| Publication state | EXISTS_BUT_FRAGMENTED (Nexus) | Nexus governs publishing, not per-agent admin |
| Execution history / provider route / fallback | EXISTS_BUT_FRAGMENTED | Nexus/explorer have pieces; not agent-centric |
| Capabilities / errors / artifacts | BACKEND_CONTRACT_MISSING | not exposed per agent |

## INTELLIGENCE
| Capability | Status | Evidence |
|-----------|--------|----------|
| Missions (read) | EXISTS_AND_USABLE | Explorer `/explorer/missions`, jobs, catalog |
| Missions (create/start/cancel) | EXISTS_BUT_FRAGMENTED | Explorer POST create/estimate/start-detached exist; **no cancel**; not wired behind approvals |
| Atlas reports / intelligence | EXISTS_AND_USABLE (read) | Atlas `/v1/internal/intelligence/*` |
| Datasets | EXISTS_AND_USABLE (read) | Explorer `/explorer/datasets` |
| Similarity / replay / quality gate | EXISTS_AND_USABLE (read) | Atlas `/backtests`, `/atlas/*` (frozen) |
| Regression / promotion | EXISTS_BUT_READ_ONLY | Atlas quality gate (recommend-only, frozen) |
| Oracle / Behavior / Reasoning | EXISTS_AND_USABLE (read) | Atlas intelligence routes |

## DATA
| Capability | Status | Evidence |
|-----------|--------|----------|
| Ingestion / datasets / freshness | EXISTS_AND_USABLE (read) | Explorer datasets/sources/quality |
| Processing failures / retries | EXISTS_BUT_FRAGMENTED | tickets + DLQ |
| DLQ | EXISTS_AND_USABLE (maybe mutable) | `/api/v1/dlq` + `/dlq/[id]/replay` (verify backend) |
| Lineage | BACKEND_CONTRACT_MISSING | no lineage contract |
| Anvil workloads | BACKEND_CONTRACT_MISSING | Anvil is a headless worker |
| ClickHouse flows | EXISTS_BUT_READ_ONLY | health only via gateway probe |

## REALTIME
| Capability | Status | Evidence |
|-----------|--------|----------|
| Active matches / streams / consumers / lag | BACKEND_CONTRACT_MISSING (for Console) | realtime SSE exists in gateway for the app, not operator ops |
| Snapshots / state engines / signals | EXISTS_BUT_FRAGMENTED | sport-hub/atlas signals not operator-surfaced |
| Stale sources / reconnects | BACKEND_CONTRACT_MISSING | not exposed |

## SUPPORT
| Capability | Status | Evidence |
|-----------|--------|----------|
| User search / account state | EXISTS_BUT_READ_ONLY | admin users read; no cross-domain support view |
| Activity / moderation history per user | EXISTS_BUT_FRAGMENTED | moderation actions exist; not user-centric aggregated |
| Relationships / communities per user | BACKEND_CONTRACT_MISSING | see Social |
| Operational diagnostics per user | NOT_IMPLEMENTED_ANYWHERE | no support case model |

## GOVERNANCE
| Capability | Status | Evidence |
|-----------|--------|----------|
| Permissions catalog | EXISTS_AND_USABLE | gateway `console/roles.go` (rich) |
| Approvals | PREVIEW_ONLY | Operation-domain approve() in JSON file |
| Audit (read) | EXISTS_AND_USABLE | gateway `/v1/console/audit`, `AuditService` |
| Operation history | PREVIEW_ONLY | JSON file |
| Break-glass / sensitive-action confirmation | NOT_IMPLEMENTED_ANYWHERE | no break-glass model |

---

## Gap summary
- **Real & usable today:** platform health (both envs), moderation, publication (Nexus),
  intelligence/data **reads** (Atlas/Explorer), audit read, permission catalog.
- **The dominant gap is the absence of *domain admin contracts*** — Social (posts/comments/
  communities/agents/relationships), Identity (mutations + official identity), Agents (activation),
  Support (case model), Realtime, and a **platform registry** (services/environments/capabilities)
  to replace hardcoded topology. Governance mutation (approvals/operations) exists only as a
  preview file.
- **RBAC vocabulary is far ahead of contracts:** `PermissionsForRole` already names
  suspend/ban/shadow_ban/force_logout/change_permissions/scheduler.*/provider.*/model.* — almost
  none have a backing mutation route. Permissions are a *promise*, not an *enforcement point*.

**Capability verdict:** The Console can **observe** much and **control** little. Becoming a
control plane is **primarily a backend-contract problem** (service admin APIs) gated by a
**boundary/security problem** (Stages 2/6), not a UI problem.
