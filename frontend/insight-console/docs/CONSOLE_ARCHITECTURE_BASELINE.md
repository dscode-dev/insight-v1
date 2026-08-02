# Insight Console — Architectural Baseline (Reconstruction after CONSOLE-SOCIAL-B)

> **Status:** Reconstructed from the code as source of truth. Where the code does not permit a
> conclusion, that is stated explicitly ("NÃO CONCLUSIVO"). This document reflects the *implemented*
> architecture, not the original plan; divergences are documented in Part 10.
>
> **Method:** read of `insight-console` (lib/control-plane, lib/*, app/, middleware, scripts, docs),
> `insight-gateway` console/operator/admin routes, `insight-social` console httpapi. Not every page/
> adapter was read line-by-line — per-module maturity claims cite the evidence I did read and flag
> the rest.

---

## PART 1 — Executive Summary

**O que o Console é (verificado em código):** o **Human Control Plane** do Insight — um app Next.js 14
(App Router) que é ao mesmo tempo **UI + BFF server-only**, através do qual operadores autenticados
observam/administram a plataforma distribuída. Não é um dashboard: a medida de maturidade é
*capability auditada sobre recurso real de domínio* (ratificado em `docs/console-architecture-a/
CONSOLE_V1_DEFINITION.md`).

**Estágio atual.** A **fundação arquitetural está madura e é a espinha dorsal real do código**:
- **Control Plane** (`lib/control-plane/`) — registries server-owned (Environments/Services/
  Capabilities), adapters tipados, PlatformSnapshotService, error model canônico, seam de ator.
- **Segurança** (`lib/control-plane/security/`) — OperatorContext server-owned, authorization
  fail-closed (SuperAdmin + permission), **audit spine canônico durável** (intent/outcome,
  correlation, superset do `operator_audit_log` do Gateway).
- **Social** — plano de **leitura** (SOCIAL-A/A1/A2: overview/users/agents/posts/comments/
  communities/relationships/boosts + InvestigationService/TimelineService compostos server-side) e
  plano de **enforcement** (SOCIAL-B: suspend/ban/hide/restore/agent deactivate/report review-
  resolve-dismiss) — cada mutação com capability→authorize→audit intent/outcome.

**Domínios maduros (com backend real observado):** Platform (health/registries/capabilities/audit),
Social read, Social enforcement, Auditoria. Identity existe **implicitamente** (operator == identity
hoje; split planejado para IDENTITY-A).

**Módulos pendentes / parciais.** Existem **páginas para muitos domínios além de SOCIAL-B**
(operations, data-intelligence, atlas, agents, cloud, dlq, llm, publication-center, analytics,
moderation, administration, live, explorer). Estas **precedem ou correm à frente** da sequência
oficial CONSOLE-ARCHITECTURE-A (foram construídas por sprints Console anteriores — Ops-A/A2/A3,
Publication-Control, i18n-A). A maturidade real por página varia de "adapter real" a "empty honesto"
a "stub". Ver Parts 3 e 8 (com marcações de NÃO CONCLUSIVO onde não li a página inteira).

**Riscos principais (Part 11):** (1) o **BFF acessa Postgres diretamente** (`pg` em package.json;
`lib/db.ts`; handlers social console no Gateway recebem `*pgxpool.Pool`) — defensável hoje, mas é um
acoplamento de dados que a doutrina V1 quer evitar; (2) **superfícies de UI à frente dos contratos**
(páginas de domínios ainda não oficialmente entregues) criam risco de "maturidade aparente"; (3)
`identityId == operatorId` é uma simplificação explícita que IDENTITY-A precisa desfazer sem quebrar
atribuição de auditoria; (4) audit é **honesto mas não atômico** entre serviços (reconciliation flag).

**Visão geral da arquitetura.** Browser → **Console (Next.js UI + BFF server-only)** → **Gateway
(BFF/orchestrator, dono da identidade de operador/sessão/roles/permissions)** → **Social/Atlas/
Explorer/Nexus/Robozão** → Postgres/Redis/ClickHouse. Dois ambientes federados pelo Environment
Registry: **`robozao`** (on-prem) e **`google-cloud`**. Boundary server-only imposto por convenção
(`SERVER-ONLY`), por `middleware.ts` (sessão) e por `scripts/check-boundaries.mjs` (sem dependências
de módulos legados).

---

## PART 2 — Arquitetura Consolidada

### Camadas
```
Browser (React/Next client components — só hints de UI)
    │  cookie de sessão (SESSION_COOKIE); nunca declara identidade
    ▼
Console Next.js  ── app/(console)/* (páginas)  +  app/api/* (BFF server-only)
    │  lib/control-plane/*  (SERVER-ONLY: registries, adapters, security, audit)
    │  lib/session.ts, lib/api-guard.ts, lib/admin-api.ts
    ▼
Gateway (Go) ── /v1/operator/auth/* (identidade/sessão), /v1/console/*, /v1/admin/*
    │  dono de operator identity, sessions (operator_sessions token_hash=sha256), roles, permissions,
    │  operator_audit_log (spine canônico), moderation (moderation_* tabelas)
    ▼
Social (Go/gRPC + httpapi console_social*) · Atlas (FastAPI, FROZEN) · Explorer (FastAPI) ·
Nexus (Go) · Robozão Gateway (Go) · Anvil (worker)
    ▼
Postgres (pgvector) · Redis · ClickHouse
```

### Bounded contexts (ownership — verificado no `services.ts` `ownership:`)
- **platform** — console, gateway, robozao-gateway, postgres, redis, cloud-postgres/redis/clickhouse.
- **social** — social (dono do domínio social; users/agents/posts/comments/communities/relationships).
- **intelligence** — atlas (FROZEN).
- **data** — explorer, sport-hub.
- **publication** — nexus, qwen.
- **analytics** — anvil.
- **gateway** — gateway, robozao-gateway (fronteira de rede).

### Registries (server-owned — `lib/control-plane/registries/`)
- **EnvironmentRegistry** — `robozao` (on-prem) e `google-cloud`; federa a fronteira lógica única.
- **ServiceRegistry** — descriptor por serviço: `id, displayName, domain, environmentId, serviceType,
  ownership, protocol, adapterKind, observable, mutable, dependencies, lifecycle, endpointKey,
  capabilities[]`.
- **CapabilityRegistry** — descreve capabilities `domain.resource.action` com **evidence** real; NÃO
  autoriza. Estados DECLARED/DISCOVERED/AVAILABLE/DEGRADED/UNAVAILABLE/UNSUPPORTED. READ resolve por
  health; MUTATION nunca é elevada pela fundação (fica DECLARED).

### Adapters (`lib/control-plane/adapters/`)
`base.ts` = transporte server-side único: timeout (5s default), AbortController, cap de resposta
(2MB), normalização canônica de erro (`ControlPlaneError`), atribuição por `SourceStatus`, headers de
auth injetados server-side (`operatorToken` nunca serializado ao browser), `X-Request-Id`=
correlationId. **NÃO é proxy genérico** — todo call mira um upstream fixo resolvido por config/
registry; o browser nunca escolhe host/path. Adapters específicos: `atlas, explorer, explorer-
privileged, nexus, robozao, social, social-enforcement, trust-safety, gateway`.

### Boundaries
- **SERVER-ONLY** — todo `lib/control-plane/*` é server-only (comentado no topo de cada arquivo); o
  browser nunca importa.
- **middleware.ts** — exige `SESSION_COOKIE` para `/(console)` e `/api/v1`; anônimo → `/login`.
- **check-boundaries.mjs** — proíbe imports/URLs de módulos legados (playmaker/pundit/atrium/plaza/
  magnus); roda em CI ao lado de lint+typecheck.

### Capability model
Ver Part 5.

### Autenticação
Gateway é a autoridade. `lib/session.ts` lê o cookie; `currentOperator()` verifica server-side via
Gateway `/v1/operator/auth/me`. Login/logout/refresh: `/v1/operator/auth/{login,logout,me,refresh}`.
Sessão real = `sha256(token)` (`operator_sessions.token_hash`).

### Autorização
`lib/control-plane/security/authorization.ts` — **decisão**, não lookup. Fail-closed. Regra real
pré-existente: `role === "SuperAdmin"` (bypass) OU `permissions.includes(requiredPermission)`. Registry
presence é **pré-condição, não autorização**. Frontend (`hasPermission`, `types/auth.ts`) só decide
afordância de UI; o BFF re-valida toda mutação.

### Auditoria
Ver Part 6.

### Comunicação entre serviços
Console→Gateway via HTTP (adapters); Gateway→Social via gRPC + httpapi console; Console→Atlas/Explorer/
Nexus/Robozão via adapters HTTP dedicados. Correlation id propagado como `X-Request-Id`.

---

## PART 3 — Mapa de Módulos do Console

> Páginas em `app/(console)/`. **Marca de maturidade** baseada no que li: **[CORE]** fundação
> verificada; **[REAL]** backend real observado (adapter/rota do Gateway/Social); **[PARCIAL/NÃO
> CONCLUSIVO]** existe página/rota mas não verifiquei o backing de ponta a ponta.

### Fundação (lib) — [CORE, verificado]
| Módulo | Objetivo | Publica | Consome | Observações |
|---|---|---|---|---|
| `control-plane/registries/*` | topologia server-owned | descriptors | config | fonte da verdade de topologia |
| `control-plane/adapters/*` | transporte tipado por serviço | AdapterResult | upstreams fixos | base.ts = timeout/normalize/attribution |
| `control-plane/snapshot.ts` | PlatformSnapshot (health+capabilities) | snapshot | adapters+registries | resolve estado efetivo de capability READ |
| `control-plane/security/*` | operator-context, authorization, audit, delegation, observability | decisão+evento | Gateway `/me`, repo audit | fail-closed; audit durável |
| `control-plane/social-bff.ts` / `social-command.ts` | leitura/mutação Social BFF | Response | adapters social/enforcement | padrão canônico de rota |
| `control-plane/services/investigation.ts` | composição cross-domain (SOCIAL-A2) | painéis | social+trust-safety+audit | allSettled, failure-isolated, partial honesto |
| `session.ts` / `api-guard.ts` / `admin-api.ts` | sessão, guard, erro canônico | ConsoleApiError | Gateway | withApiHandler shape |

### Domínios (páginas + BFF)
| Página `app/(console)/` | BFF `app/api/` | Estado | Backend evidência |
|---|---|---|---|
| `social` | `/api/v1/social/*` (+ `/enforcement`, users/{id}/ban…) | **[REAL]** | Gateway `/v1/console/social/*` + Social `console_social*.go`; enforcement SOCIAL-B |
| `moderation` | `/api/v1/moderation/{reports,actions,stats}` | **[REAL]** | Gateway `/v1/admin/moderation/*` (Gateway-owned) |
| `audit` | `/api/v1/audit`, `/api/v1/audit/events(/:id)` | **[REAL]** | Gateway `/v1/console/audit(/events)` → operator_audit_log |
| `administration` (operators/sessions/users) | `/api/v1/admin/{operators,sessions,users}` | **[REAL]** | Gateway `/v1/console/admin/*` |
| `dashboard` / `operations` / `console` | `/api/v1/platform/{snapshot,health,services,environments,capabilities}` | **[REAL/CORE]** | PlatformSnapshotService + registries + Gateway `/v1/console/platform/health` |
| `dlq` | `/api/v1/dlq(/:id/replay)` | **[PARCIAL/NÃO CONCLUSIVO]** | rota existe; backing durável não verificado nesta leitura |
| `data-intelligence` (tickets/datasets/pipelines/executions/sources/dashboard) | `/api/v1/data-intelligence/[...path]`, `/api/v1/atlas-datasets` | **[PARCIAL]** | adapters explorer/atlas existem; profundidade por sub-página NÃO CONCLUSIVO |
| `atlas` (intelligence/knowledge) | `/api/v1/atlas-datasets/*`, providers | **[PARCIAL]** | adapter atlas (FROZEN, read); knowledge NÃO CONCLUSIVO |
| `agents` | `/api/v1/social/agents*` | **[REAL parcial]** | leitura via social console; admin de agente = enforcement SOCIAL-B (deactivate/reactivate) |
| `publication-center` (tickets/manual) / `analytics/publications` / `llm` | `/api/v1/llm`, providers | **[PARCIAL]** | Nexus adapter; herança de Console-Publication-Control; NÃO CONCLUSIVO em detalhe |
| `cloud` | `/api/cloud/services`, `/api/ops/*` | **[PARCIAL/STUB conhecido]** | memória do projeto indica stubs quando cloud down; NÃO reverificado linha a linha |
| `live` / `explorer` | `/api/operations/status`, `/api/explorer/*` | **[PARCIAL/NÃO CONCLUSIVO]** | rotas existem; realtime ops = domínio ainda não oficialmente entregue |
| `auth` | `/api/v1/auth/activity` | **[REAL]** | auth-activity |

> **Nota de divergência (Part 10):** a existência das páginas de operations/data-intelligence/atlas/
> cloud/dlq/llm/publication-center **não implica** que os sprints CONSOLE-SERVICE-OPS-A/INTELLIGENCE-A/
> DATA-A/etc. estejam concluídos. Elas são herança de sprints Console anteriores à re-sequência
> ARCHITECTURE-A. A maturidade real deve ser lida na Part 8.

---

## PART 4 — Decisões Arquiteturais

### Explícitas (ADRs referenciados no código)
1. **ADR-0002 — Gramática de capability `domain.resource.action`** (capabilities.ts). *Por quê:*
   discovery descritivo uniforme. *Onde:* CapabilityRegistry. *Resolve:* nomenclatura consistente e
   evidence-backed. *Limitação:* exige META com evidence por id (sem evidence ⇒ não é capability).
2. **Capability ≠ Authorization** (SECURITY-A0). *Por quê:* registry não pode conceder direito.
   *Onde:* authorization.ts (fail-closed). *Resolve:* separação de "existe?" vs "pode?". *Limitação:*
   toda mutação precisa de permission declarada senão é `denied_no_policy`.
3. **ADR-0005 — Audit spine canônico superset do `operator_audit_log`** (audit/model.ts). *Por quê:*
   um único registro administrativo federável. *Resolve:* WHO/WHAT/WHERE/OUTCOME/WHY/correlation.
4. **Operator identity bound at the mutation point** (operator-context.ts + actor.ts +
   assertNoClientActor). *Por quê:* impedir actor client-asserted. *Resolve:* atribuição confiável.
5. **Registries server-owned, sem topologia como constante de frontend** (FOUNDATION-A). *Onde:*
   registries/*. *Limitação:* mudanças de topologia exigem editar seeds server-side.
6. **Adapter tipado, não proxy genérico** (base.ts). *Por quê:* browser nunca escolhe host/path.
7. **Environment Registry federa dois gateways físicos numa fronteira lógica** (`robozao`+`google-cloud`).
8. **Boundary anti-legado imposto em CI** (check-boundaries.mjs).

### Implícitas (percebidas no código)
- **`identityId == operatorId` (hoje)** — simplificação explícita documentada em operator-context.ts;
  IDENTITY-A vai separar.
- **`authStrength`/`authenticatedAt` = null** — o contrato `/me` não expõe; modelado como null, não
  fabricado.
- **BFF pode tocar Postgres** — `pg` + `lib/db.ts` + handlers social console recebendo `*pgxpool.Pool`.
  Decisão implícita de performance/pragmatismo que tensiona a doutrina "BFF não é store".
- **Audit não-atômico entre serviços** — intent antes / outcome depois, `reconciliationNeeded` quando
  o store não é durável; nunca engole falha (writer.ts).
- **Delegation modelada mas inativa** — DelegationContext existe; `delegation: null` sempre neste
  estágio (operator-context.ts).

---

## PART 5 — Modelo de Capabilities

- **Gramática:** `domain.resource.action` (exatamente 3 segmentos; `parse()` rejeita o resto).
- **Nomenclatura:** domínios reais (`atlas, explorer, robozao, nexus, gateway, social, trust, audit`);
  actions read-set = `{read, list, get}` → classe `read`; o resto → `mutation`.
- **Hierarquia/estado:** DECLARED (config sabe que existe) → DISCOVERED (runtime confirma superfície)
  → AVAILABLE/DEGRADED/UNAVAILABLE (health) / UNSUPPORTED (serviço não implementa). READ resolve por
  health via `effectiveState()`; **MUTATION nunca é elevada pela fundação** (permanece DECLARED).
- **Risco/approval:** derivados: mutation ⇒ risk default `high` + `approvalRequired`; overrides em META
  (ex.: `social.user.ban` = `critical`; `trust.report.review` = `low`, sem approval).
- **Evidence obrigatória:** cada capability carrega uma rota/RPC real; **sem evidence ⇒ não é
  registrada** (nunca inventa por roadmap).
- **Responsabilidade:** o registry é **descritivo** (discovery); **autorização vive em
  authorization.ts** e, em profundidade real, no serviço (Gateway/Social). O BFF é defence-in-depth.
- **Onde é verificada:** (1) no BFF: `authorize(operator, capability, requiredPermission)` fail-closed;
  (2) no serviço: o Gateway re-checa a sessão do operador na chamada real.
- **Como chega ao frontend:** `/api/v1/platform/capabilities` (registry) + o operator carrega
  `permissions[]` de `/me`; o cliente usa `hasPermission()` só para afordância.
- **Como é consumida:** UI esconde/dim afordâncias; toda mutação re-valida no BFF e no serviço.

---

## PART 6 — Modelo de Auditoria

### Peças
- **Audit Spine (canônico):** `AdministrativeAuditEvent` (audit/model.ts) — superset compatível do
  `operator_audit_log` do Gateway (ADR-0005). Campos: eventId, occurredAt, correlationId, requestId,
  **actor** (operatorId/identityId/sessionId/roles/authStrength=null), **delegation**, **action**
  (capability+domain+resource+action), **target** (env/service/resourceType/resourceId),
  **authorization** (decision/reasonCode/policySource), **outcome** (status/errorCode/retryable),
  **context** (reason + metadata saneada).
- **Provenance:** `actor` sempre server-derivado (OperatorContext). `assertNoClientActor()` remove
  campos de ator vindos do body.
- **Correlation ids:** `correlationId` (encadeia a cadeia; default = requestId no root) distinto de
  `requestId` (por request) e distinto de `sessionId` (=sha256(token)).
- **Session:** `sessionId` = SHA-256 do token opaco de sessão (não é o segredo).
- **Operator identity:** OperatorContext (Part 2). identityId==operatorId hoje.
- **Canonical audit:** um único spine; o repo dedupe por `event_id` (append idempotente).
- **Intent/outcome:** `AdministrativeAudit.decision()` escreve AUTHORIZED|DENIED **antes** da mutação;
  `.outcome()` escreve STARTED|COMPLETED|FAILED|CANCELLED **depois**, correlacionado por correlationId.
- **Eventos:** status enum `REQUESTED/AUTHORIZED/DENIED/STARTED/COMPLETED/FAILED/CANCELLED`. Segredos
  proibidos por regex `FORBIDDEN` no `safeMetadata` (sem tokens/bodies).

### Fluxo completo de auditoria (mutação)
```
Rota BFF (socialCommand) → resolveOperatorContext(req)         [identidade server-owned]
   → authorize(op, capability, permission)                     [decisão fail-closed]
   → AdministrativeAudit.decision(op, decision)                [AUTHORIZED|DENIED — ANTES]
   → adapter social-enforcement chama Gateway (operator token) [mutação real]
   → Gateway re-checa sessão + escreve operator_audit_log      [autoridade + spine durável]
   → AdministrativeAudit.outcome(op, decision, COMPLETED|FAILED)[DEPOIS, correlacionado]
   → se append falha ou store não-durável ⇒ reconciliationNeeded=true + observeSecurity(...)
```
**Consistência honesta:** não há atomicidade distribuída; nunca engole falha.

---

## PART 7 — Fluxos Arquiteturais

### 7.1 Leitura Social (investigação)
```
Operador → Console page (social) → /api/v1/social/* (BFF, resolveOperatorContext)
 → SocialControlPlane adapter → Gateway /v1/console/social/* → Social console_social*.go (pgxpool)
 → InvestigationService/TimelineService compõe painéis (allSettled, partial honesto)
 → resposta com source attribution → UI
```
### 7.2 Enforcement Social (mutação com dual-control)
Ver Part 6 (fluxo de auditoria). Capabilities `critical/high` carregam approvalRequired; a decisão
final de execução é do serviço.
### 7.3 Platform snapshot (observe)
```
Operador → dashboard/operations → /api/v1/platform/snapshot
 → PlatformSnapshotService → adapters.readHealth (por serviço observable)
 → CapabilityRegistry.effectiveState(health) → snapshot com SourceStatus por fonte → UI
```
### 7.4 Auth de operador
```
/login → /api/auth/login → Gateway /v1/operator/auth/login (cookie de sessão)
middleware exige SESSION_COOKIE; currentOperator() → Gateway /v1/operator/auth/me (verificação)
```
### 7.5 Auditoria (read)
```
audit page → /api/v1/audit/events → Gateway /v1/console/audit/events → operator_audit_log
```

---

## PART 8 — Estado Real dos Domínios

| Domínio | Existe? | Maturidade | Evidência / ressalva |
|---|---|---|---|
| **Social** | SIM | **Madura** (read + enforcement) | SOCIAL-A/A1/A2/B; Gateway `/v1/console/social/*`; Social `console_social*.go`; capabilities read+mutation com META/evidence |
| **Identity** | Parcial (implícito) | **Imatura** | operator==identity hoje (operator-context.ts); split é o objetivo de IDENTITY-A; **Ninja/delegação não ativa** (delegation=null) |
| **Agents** | Parcial | **Média** | leitura via social console (`social.agent.read`) + enforcement (`agent.deactivate/reactivate`); runtime de agente é do Nexus/Social, não do Console |
| **Services (Platform Ops)** | SIM | **Média** | registries + snapshot + `/v1/console/platform/health`; SSE live / incidents com store real = pendente (SERVICE-OPS-A) — **NÃO CONCLUSIVO** se já há SSE |
| **Explorer** | Parcial | **Baixa-Média** | adapter explorer + capabilities read (missions/datasets); páginas data-intelligence existem; profundidade NÃO CONCLUSIVO |
| **Atlas** | SIM (read, FROZEN) | **Média (só leitura)** | adapter atlas; capabilities `atlas.*.read`; **congelado** — nunca alterar lógica/threshold |
| **Nexus** | Parcial | **Baixa-Média** | adapter nexus + `nexus.publications.read`; publication-center/analytics herdados de Publication-Control; NÃO CONCLUSIVO em detalhe |
| **Intelligence** | Parcial | **Baixa** | atlas/explorer read atrás do boundary; mission start/cancel + approvals = INTELLIGENCE-A pendente |
| **Operations (governança)** | Parcial | **Baixa** | não há Operation Service durável verificado; IOC-Executor pendente; páginas operations = observação, não execução governada |
| **Support** | Não (como domínio próprio) | **Ausente** | SUPPORT-A depende de social+identity+agents; hoje só investigação social composta |
| **Security (hardening)** | Parcial | **Média (A0 feito)** | A0 (identidade+audit) implementado; dual-control/break-glass/CSRF/rate-limit/replay completos = SECURITY-A pendente |
| **Data** | Parcial | **Baixa** | explorer/atlas datasets + DLQ page; DLQ replay durável/auditado + Anvil control = DATA-A pendente; **NÃO CONCLUSIVO** |

---

## PART 9 — Dependências das Próximas Sprints (baseado no código atual)

> Ordem recomendada = a re-sequência ARCHITECTURE-A **ajustada ao que já existe**. As leituras Social
> e a fundação já estão prontas, então as próximas sprints se apoiam nelas.

1. **CONSOLE-IDENTITY-A** — *objetivo:* separar identity de operator; modelo user/official-identity/
   agent/ownership; **delegação explícita (Ninja), nunca impersonation silenciosa**. *Pré-req (prontos):*
   OperatorContext, audit spine, `assertNoClientActor`, DelegationContext (já modelado, inativo).
   *Contratos necessários:* Gateway precisa expor identity separada de operator em `/me`/novos
   endpoints; ADR-0007. *Riscos:* mudar `identityId==operatorId` sem quebrar atribuição de auditoria.
   *Dependência oculta:* o audit `actor.identityId` já existe — ativar sem migração de eventos antigos.
2. **CONSOLE-AGENTS-A** — depende de IDENTITY (ownership de agente). Leitura+deactivate já existem;
   falta activation/publication-state/execution-history com Nexus/Explorer.
3. **CONSOLE-SERVICE-OPS-A** — SSE live + incidents com store real. Pré-req: registries (prontos).
   Risco: não fabricar incidentes; failure isolation por superfície.
4. **CONSOLE-INTELLIGENCE-A** — reads Atlas/Explorer (já parciais) + mission start/cancel **atrás de
   approvals** → depende do Operation Service (governança).
5. **CONSOLE-DATA-A** — DLQ replay auditado + Anvil. Depende de SERVICE-OPS + INTELLIGENCE.
6. **CONSOLE-REALTIME-A** — views de matches/streams/consumers/lag. Depende de SERVICE-OPS (SSE).
7. **CONSOLE-OPERATIONS-A / Operation Service durável** — pré-req do executor; approvals/break-glass.
8. **IOC-EXECUTOR-A** — executa operações aprovadas (idempotente/retry/rollback). Depende do
   Operation Service.
9. **CONSOLE-SUPPORT-A** — agrega social+identity+agents (depende de IDENTITY/AGENTS).
10. **CONSOLE-SECURITY-A** — hardening completo (dual-control/break-glass/CSRF/rate-limit/replay).
11. **CONSOLE-UX-FREEZE-A** — congelar IA capability-driven; remover clusters duplicados/órfãos.

**Ordem recomendada:** IDENTITY-A → AGENTS-A → SERVICE-OPS-A → INTELLIGENCE-A → (Operation Service) →
DATA-A ∥ REALTIME-A → IOC-EXECUTOR-A → SUPPORT-A → SECURITY-A → UX-FREEZE-A. Racional: identity destrava
attribution/ownership de tudo; governança (Operation Service) precede execução; hardening depois que as
superfícies existem.

---

## PART 10 — Divergências (planejado × implementado)

| # | Planejado (ARCHITECTURE-A) | Implementado (código) | Boa? | Dívida |
|---|---|---|---|---|
| 1 | Sprints sequenciais; páginas surgem por sprint | **Muitas páginas já existem** (operations/data-intel/atlas/cloud/dlq/llm/publication-center/analytics) herdadas de sprints Console pré-re-sequência | Neutra | **Sim** — "maturidade aparente"; UI à frente de contratos |
| 2 | BFF não é store; sem DB direto | **BFF/handlers acessam Postgres** (`pg`, `lib/db.ts`, `console_social*.go` com pgxpool) | Pragmática | **Sim** — acoplamento de dados vs doutrina V1 |
| 3 | Identity separada de operator | **operator==identity** (documentado, temporário) | Aceitável | **Sim** — IDENTITY-A precisa desfazer |
| 4 | Delegação explícita ativa | **DelegationContext modelado, sempre null** | Boa (prep) | Baixa |
| 5 | Audit atômico | **Intent/outcome não-atômico + reconciliation flag** | Boa (honesta) | Baixa (documentada) |
| 6 | Cloud health real | **Stubs conhecidos quando cloud down** (memória do projeto) | Neutra | **Sim** — NÃO reverificado linha a linha |

---

## PART 11 — Riscos Arquiteturais (sem soluções)

1. **Acoplamento de dados no BFF/Gateway console handlers** — acesso direto a Postgres (`pg`,
   `lib/db.ts`, `console_social*.go` recebendo `*pgxpool.Pool`) contorna a fronteira "serviço é dono
   do store".
2. **UI à frente dos contratos** — páginas de domínios ainda não oficialmente entregues (operations/
   data-intel/atlas/cloud/dlq/llm) podem sugerir capacidade que o backend não sustenta; risco de
   regressão de confiança.
3. **`identityId == operatorId`** — qualquer código que já leia `actor.identityId` assume a igualdade;
   IDENTITY-A muda isso sob eventos de auditoria já gravados.
4. **Auditoria não-atômica** — janela entre intent e outcome; `reconciliationNeeded` exige processo
   operacional (não há reconciliador automático verificado).
5. **Delegação inativa mas modelada** — superfícies que assumam delegação futura podem ossificar um
   contrato antes de existir.
6. **Duplicação potencial de superfícies** (moderation vs social/enforcement; operations vs dashboard/
   console) — UX-FREEZE-A existe justamente para isso; hoje há sobreposição.
7. **Stubs de cloud** — estado "down = stub" pode mascarar indisponibilidade real.
8. **Dependência de convenção para o boundary server-only** — `SERVER-ONLY` é comentário + disciplina;
   `check-boundaries.mjs` só cobre legados, não o vazamento control-plane→client.

---

## PART 12 — Roadmap Reconstruído (a partir do código)

Ordem = Part 9. **Por que nesta ordem (evidência):**
- **IDENTITY-A primeiro** porque o audit já referencia `identityId` e o ownership de agentes/suporte
  depende de identity separada — é o desbloqueio de maior alcance.
- **AGENTS-A** logo após identity (ownership de agente).
- **SERVICE-OPS-A** (SSE/incidents) apoia-se em registries já prontos; destrava REALTIME/DATA.
- **INTELLIGENCE-A** precisa de approvals → **Operation Service** (governança) precede execução.
- **IOC-EXECUTOR-A** só depois do Operation Service durável.
- **SUPPORT-A** agrega domínios que só existem após IDENTITY/AGENTS.
- **SECURITY-A** (hardening) depois que as superfícies mutantes existem, para endurecer o conjunto.
- **UX-FREEZE-A** por último, para congelar a IA capability-driven e remover duplicações (risco #6).

---

## PART 13 — Contexto que DEVE ser Preservado (convenções obrigatórias)

1. **Capability = descrição, nunca autorização.** Registry descreve; `authorize()` decide (fail-closed:
   SuperAdmin OU permission; senão deny). Registry presence é só pré-condição.
2. **Gramática `domain.resource.action` com evidence obrigatória.** Sem rota/RPC real ⇒ não registrar.
   READ resolve por health; MUTATION nunca elevada pela fundação.
3. **Operator identity é server-owned e vinculada no ponto da mutação.** Nunca aceitar actor do body
   (`assertNoClientActor`). identityId==operatorId é temporário e documentado — não construir sobre a
   igualdade sem consciência.
4. **Audit spine canônico único** (superset do `operator_audit_log`), intent **antes** / outcome
   **depois**, correlacionado; `safeMetadata` (sem tokens/bodies); nunca engolir falha
   (`reconciliationNeeded`). Toda nova mutação usa `AdministrativeAudit.decision/outcome`.
5. **Adapters tipados, nunca proxy genérico.** Todo upstream é fixo, resolvido por config/registry;
   browser nunca escolhe host/path; token de operador nunca serializado ao cliente; timeout+normalize+
   source attribution via `base.ts`.
6. **Registries server-owned; topologia nunca como constante de frontend.** Novos serviços/ambientes/
   capabilities entram nos seeds server-side com `evidence`.
7. **Boundary server-only.** `lib/control-plane/*` nunca importado pelo browser; `middleware.ts` exige
   sessão; `check-boundaries.mjs` em CI. Manter os cabeçalhos `SERVER-ONLY`.
8. **BFF é defence-in-depth, não a autoridade.** O serviço (Gateway/Social) re-valida e é dono do
   store, da sessão, dos roles/permissions e do spine durável.
9. **Estados honestos.** Partial/empty/degraded reais (allSettled, source attribution); **nunca
   fabricar** dados ausentes. Novas superfícies seguem `InvestigationService` (failure-isolated).
10. **Atlas é FROZEN.** Só leitura atrás do boundary; nenhuma lógica/threshold/detector muda pelo
    Console.
11. **Dois ambientes federados** (`robozao`, `google-cloud`) numa fronteira lógica única via
    EnvironmentRegistry — nunca hardcodar host de ambiente na UI.
12. **Padrão de rota canônico** (`socialRead`/`socialCommand`): resolveOperatorContext → authorize →
    (audit) → adapter → normalize error. Toda nova rota administrativa segue esse esqueleto.

---

### Anexo — Evidência lida (arquivos-fonte)
`lib/control-plane/{index,config,types}.ts`, `registries/{environments,services,capabilities}.ts`,
`adapters/base.ts` (+ lista de adapters), `snapshot.ts`, `services/investigation.ts`,
`security/{authorization,operator-context}.ts`, `security/audit/{model,writer}.ts`, `social-command.ts`,
`lib/{permissions,session,api-guard,admin-api,db}.ts` (parcial), `types/auth.ts`, `middleware.ts`,
`scripts/check-boundaries.mjs`, `docs/console-architecture-a/{CONSOLE_V1_DEFINITION,ROADMAP}.md`;
Gateway `cmd/gateway/main.go` (rotas `/v1/{operator,console,admin}/*`); Social
`internal/interfaces/httpapi/console_social*.go`.
**Não lidos integralmente (NÃO CONCLUSIVO onde citado):** páginas e BFF de data-intelligence, atlas,
cloud, dlq, llm, publication-center, analytics, live, explorer; adapters nexus/robozao/anvil em
profundidade; testes.
