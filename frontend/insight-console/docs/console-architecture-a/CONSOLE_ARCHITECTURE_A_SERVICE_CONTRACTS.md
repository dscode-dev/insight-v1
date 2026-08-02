# CONSOLE-ARCHITECTURE-A — Stage 4: Service Admin Contract Audit

Per-service: what it owns, what the Console can read/mutate today, which admin/operational
contracts exist, which are missing, and a **proposed capability namespace derived from the real
system** (not invented). Nothing here is implemented this sprint.

---

## insight-social (Cloud, Go/gRPC) — the central gap
- **Owns:** users, agents, posts, comments, feeds, relationships, follows, blocks, mutes,
  discussions (communities), reactions, signals, sentiment, reputation.
- **Console reads today:** users (via gateway admin), agents (`/v1/agents`), moderation reports.
- **Console mutates today:** only moderation actions (via gateway) — remove/restore/suspend/ban.
- **Admin/operational contracts that EXIST:** `admin/v1.ModerationService` (Create/ListReports/
  Resolve); social `AgentService.List/Get`; `UserService.List/Get/GetStats`.
- **MISSING contracts:** admin post/comment/reply inventory & moderation-state; interaction
  (likes/saves/boosts) operator visibility; community administration; relationship/follow admin
  views; agent activation & publication-state; content-origin operator query; official-identity
  publishing.
- **Never expose:** raw user PII bulk export without audit+approval; direct DB access.
- **Proposed namespace:** `social.posts.read` · `social.posts.moderate` · `social.comments.read`
  · `social.comments.moderate` · `social.interactions.read` · `social.communities.read` ·
  `social.communities.administer` · `social.relationships.read` · `social.users.read` ·
  `social.users.suspend` · `social.users.ban` · `social.agents.read` · `social.agents.activate`
  · `social.agents.publication.set` · `social.official_identity.publish` (delegated).

## insight-atlas (Robozão, Python) — **FROZEN, do not extend logic**
- **Owns:** pgvector memory, trends (22 detectors), replay, quality gate, IOC events.
- **Console reads today:** intelligence/graph/behaviors/patterns/signals/trends/market/memory,
  `/backtests`, datasets — via **direct** `X-Internal-Token`.
- **Mutates today:** none from Console (replay submit exists in API but not operator-wired).
- **EXISTS:** `/v1/internal/intelligence/*`, `/backtests` (POST/GET), `/atlas/*`, `/metrics`.
- **MISSING (Console-facing):** operator-authenticated read contract (today it's an internal
  token, not an operator identity); no admin mutations needed (frozen).
- **Proposed namespace (read-only for V1):** `atlas.intelligence.read` · `atlas.replay.read` ·
  `atlas.replay.submit` (approval-gated, future) · `atlas.quality.read`.

## insight-explorer (Robozão, Python) — real operational mutations exist
- **Owns:** missions, jobs, datasets, providers, sources, tickets, quality.
- **Console reads:** missions/jobs/datasets/sources/tickets (direct + robozao-gateway).
- **Mutates (upstream capability, not operator-gated):** `POST /explorer/missions`,
  `/missions/estimate`, `/missions/{id}/start-detached`, `/explorer/fallback`,
  `/explorer/incremental/plan`.
- **MISSING:** mission **cancel/pause**; operator identity binding (uses `X-Operator` string);
  approval gating on start/fallback.
- **Proposed namespace:** `explorer.missions.read` · `explorer.missions.start` (approval) ·
  `explorer.missions.cancel` · `explorer.datasets.read` · `explorer.providers.read` ·
  `explorer.providers.fallback` (approval) · `explorer.tickets.read`.

## insight-anvil (Cloud, Python worker) — headless
- **Owns:** ClickHouse analytics writes / derived signals.
- **Console today:** health only (gateway probe); features via gateway `anvilproxy`.
- **MISSING:** any operational/admin HTTP surface (it is a pure worker).
- **Proposed namespace (needs new worker control API):** `anvil.workloads.read` ·
  `anvil.workloads.pause` (approval) · `anvil.pipeline.retry` (approval).

## insight-nexus (Robozão, Go) — the model to copy
- **Owns:** publications, tickets, personas, LLM routing (anthropic/openai/gemini/qwen).
- **Console reads/mutates:** publication center + manual publish + tickets, **audited, tier-RBAC**
  (authed HTTP API; `RequireAuth` mux; `/replay` support).
- **EXISTS:** authed publication ops with audit + tier gating — **the reference pattern** for how
  every other service admin contract should look.
- **Proposed namespace:** `nexus.publications.read` · `nexus.publications.publish` (tier) ·
  `nexus.publications.retract` · `nexus.tickets.read` · `nexus.personas.read`.

## insight-gateway (Cloud, Go) — the admin edge
- **Owns:** operator auth/sessions/roles, social BFF, moderation admin, cloud platform-health,
  console admin reads, public app API. Holds the operator+social+moderation PG pool.
- **EXISTS:** `/v1/operator/auth/{login,me,refresh,logout}`; `/v1/console/{platform/health,audit,
  admin/users,admin/operators,admin/sessions}` (GET); `/v1/admin/moderation/*`.
- **MISSING:** operator/session **mutations** (force-logout, role change), identity delegation,
  a **platform registry** endpoint (services/environments/capabilities), a durable **operation**
  service. Also missing: uniform operator-identity binding on the moderation mutation.
- **Proposed namespace:** `platform.registry.read` · `identity.operators.manage` ·
  `identity.sessions.invalidate` · `governance.operations.*` · `governance.audit.read`.

## robozao-gateway (Robozão, Go) — ops aggregator
- **Owns:** nothing (aggregation of Explorer/Atlas via OperationsService).
- **EXISTS:** `/operations/{status,events,tickets,runs,datasets,training,history}`, `/vpn/status`.
- **Role in target:** the **Platform Operations Adapter** for the on-prem environment.

---

## Cross-service conclusions
1. **Only Nexus and gateway-moderation are real audited control surfaces.** Nexus is the pattern
   to standardise (authed + audited + tier RBAC).
2. **Social is the largest missing admin surface** and the highest-value first target
   (CONSOLE-SOCIAL-A/B).
3. **A platform registry contract is a prerequisite** — it replaces the hardcoded
   `CLOUD_META`/`SERVICE_META` and feeds Service/Environment/Capability registries (Stage 8).
4. **Every new mutation must bind operator identity server-side** (not `X-Operator`/`moderator_id`
   strings) and emit `insight.operational_event.v1` to the real audit spine.
5. **Namespaces converge on `domain.resource.action`** — adopt this as the platform capability
   grammar.
