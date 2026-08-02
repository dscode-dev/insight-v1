# CONSOLE-ARCHITECTURE-A — Stage 0: Reality Baseline

**Date:** 2026-07-03
**Method:** Static codebase audit (modules_v1 tree) + live inspection (Robozão SSH from the
same operational session; Google Cloud via authenticated `gcloud`). Read-only. No production
mutations were performed for this baseline.

**Evidence legend:** `CONFIRMED` (observed in code or live) · `INFERRED` (derived from a
contract/config, not directly observed) · `MISSING` (searched, does not exist) · `DEPRECATED`
(exists but marked/behaving as retired) · `UNKNOWN` (not established this sprint).

---

## 1. Live topology (CONFIRMED)

Two production environments. Both inspected live.

### 1.1 Google Cloud — project `focus-semiotics-496119-b4`, VM `instance-20260604-195317` (us-central1-c)
`docker ps` (CONFIRMED):

| Container | Image | Role |
|-----------|-------|------|
| insight-cloud-nginx | nginx:1.27-alpine | Edge reverse proxy (public entrypoint) |
| **insight-gateway** | konohalabs/insight-gateway:**0.1.9** | Operator auth, Social BFF, moderation admin, console platform-health/admin, public app API |
| **insight-social** | konohalabs/insight-social:**0.1.5** | Social domain owner (users/agents/posts/feeds/relationships/discussions) — Go + gRPC |
| **insight-anvil** | konohalabs/insight-anvil:**0.1.0** | Analytics worker (ClickHouse writes) — Python, **no HTTP admin surface** |
| insight-cloud-postgres | postgres:16-alpine | Social + operator/auth + moderation DB |
| insight-cloud-redis | redis:7.4-alpine | Sessions / streams |
| insight-cloud-clickhouse | clickhouse-server:24.12 | Analytics store (Anvil target) |

### 1.2 Robozão — `insight-robozao.konohalabs.lab` (on-prem Docker Compose)
`docker ps` (CONFIRMED, prior live session):

| Container | Image | Role |
|-----------|-------|------|
| **insight-console** | konohalabs/insight-console:**0.3.18** | The subject of this audit (Next.js 14 BFF+UI) |
| **insight-atlas** | konohalabs/insight-atlas:**1.0.0** | Intelligence layer — **FROZEN, certified (ATLAS-CERTIFY-B)**. Do not redesign. |
| **insight-explorer** | konohalabs/insight-explorer:**0.0.20** | Data collection / missions / datasets — Python FastAPI |
| **insight-robozao-gateway** | konohalabs/insight-robozao-gateway:**0.0.2** | Unified Operations Protocol aggregator (:8095) |
| **insight-nexus** | konohalabs/insight-nexus:**0.0.2** | Publication engine — Go, own DB, authed HTTP API |
| insight-sport-hub | konohalabs/insight-sport-hub:0.0.3 | Sports data hub |
| insight-postgres | pgvector/pgvector:pg16 | Atlas + explorer store (pgvector 0.8.3, HNSW) |
| insight-redis | redis:7.4-alpine | Atlas/explorer queues |
| insight-qwen-runtime | ollama/ollama:0.30.10 | Local LLM runtime (Nexus) |

### 1.3 Cross-environment fact (CONFIRMED, architecturally important)
The **Console runs on Robozão** but **authenticates operators against the Cloud gateway**
(`ADMIN_API_BASE_URL = https://insight-api.konohalabs.com.br/v1`). Operator identity, sessions,
roles, permissions, moderation, and cloud platform-health are **cloud-owned**; intelligence
(Atlas/Explorer) and the operations protocol are **on-prem**. The Console straddles both.

---

## 2. Service inventory & ownership (CONFIRMED unless noted)

| Service | Env | Lang | Owns (DB/domain) | Admin/console contract today |
|---------|-----|------|------------------|------------------------------|
| insight-gateway | Cloud | Go | — (BFF/proxy; holds operator+social+moderation PG pool) | operator auth, `/v1/console/*` (read), `/v1/admin/moderation/*` |
| insight-social | Cloud | Go/gRPC | users, agents, posts, comments, feeds, relationships, discussions, reactions, signals, reputation, sentiment | **gRPC app contracts only** — no operator/admin surface |
| insight-anvil | Cloud | Python | ClickHouse analytics/derived signals | **MISSING** (pure worker; observable only via gateway health/anvilproxy) |
| insight-atlas | Robozão | Python | pgvector memory, trends, replay, quality gate | rich internal REST (`/v1/internal/intelligence/*`, `/backtests`, `/atlas/*`) — consumed **direct** by Console BFF |
| insight-explorer | Robozão | Python | missions, jobs, datasets, providers, tickets | rich REST (missions/jobs/datasets/providers) — consumed **direct** + via robozao-gateway |
| insight-robozao-gateway | Robozão | Go | — (ops aggregator) | Unified Operations Protocol: `/operations/{status,events,tickets,runs,datasets,training,history}`, `/vpn/status` |
| insight-nexus | Robozão | Go | publications, tickets, personas | authed HTTP API (publication ops, audited mutations, tier RBAC) |
| insight-sport-hub | Robozão | — | sports reference data | UNKNOWN (not central to control plane) |

---

## 3. Canonical contracts (CONFIRMED)

- **Operational event:** `insight.operational_event.v1` (used by Atlas IOC and by the Console
  Operation domain; schema fields: event_type/service/severity/timestamp/operation_id/
  correlation_id/previous_state/current_state/target_service/target_resource/operator_id/metadata).
- **Admin protos** (`insight-protos/proto/admin/v1`): `ModerationService` (Create/ListReports/
  Resolve), `AuditService` (Append/Query), `SourceMonitorService`, `HealthService`.
- **Operations proto** (`proto/operations/v1`): `OperationsService` (Ping/Health/Status/
  Capabilities/Metrics) — the Robozão gateway aggregation contract.
- **Social protos** (`proto/social/v1`): User/Post/Feed/Agent/Relationship/Discussion/Reaction/
  Signal/Sentiment/Reputation — **application** contracts, not admin.

---

## 4. Baseline classification summary

| Area | State | Note |
|------|-------|------|
| Live topology (both envs) | CONFIRMED | 16 containers across 2 envs, all inspected |
| Console → Gateway auth/admin seam | CONFIRMED | `lib/admin-api.ts`, operator Bearer + service token |
| Console → Atlas/Explorer direct seam | CONFIRMED | `lib/cloud.ts` — bypasses gateway, uses internal token |
| Console → Robozão gateway ops seam | CONFIRMED | `lib/robozao.ts` |
| Operator RBAC catalog | CONFIRMED | `console/roles.go` — rich vocabulary, mostly unenforced by contracts |
| Operation domain persistence | CONFIRMED / DEPRECATED-worthy | local JSON file in `/tmp`, ephemeral (see Control Audit) |
| Social admin depth | MISSING | only moderation; no posts/agents/community admin |
| Anvil admin surface | MISSING | pure worker |
| Cloud VM internal per-service RBAC (moderation binding) | INFERRED | see Security audit |
| `lib/db.ts` direct Postgres | DEPRECATED | file is a no-op stub; `pg` dep vestigial |

**Baseline verdict:** The environment is **sufficiently inspectable**. Topology, contracts,
seams, and ownership are CONFIRMED. No blocking UNKNOWNs remain for architecture work.
