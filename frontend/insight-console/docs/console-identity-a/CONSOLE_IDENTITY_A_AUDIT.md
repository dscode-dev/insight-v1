# CONSOLE-IDENTITY-A — Stage 0 (Audit) + Stage 0.5 (Architecture Validation)

> **Fonte da verdade: o código.** A baseline (CONSOLE_ARCHITECTURE_BASELINE.md) e os ADRs 0006/0007 são
> auxiliares; onde divergirem do código, o código prevalece. **Nenhum código foi escrito neste stage.**
> Escopo: separar *operador autenticado · identidade operacional · autoria · delegação · provenance*
> sem tocar em autenticação, authorization, capabilities, SECURITY-A0, SOCIAL-B, Atlas, Investigation
> Plane ou o Audit Spine.

---

## 1. Mapa dos conceitos (onde vivem no código)

| Conceito | Onde | Estado atual |
|---|---|---|
| **OperatorContext** | `lib/control-plane/security/operator-context.ts` | server-owned; `identityId = operatorId`; `delegation = null`; `authStrength/authenticatedAt = null` |
| **Operator (identidade durável)** | Gateway `migrations/00006_operator_identity.sql` (`operators`, `operator_sessions`) | autoridade única: credenciais/sessões/roles |
| **Identity (operacional)** | — | **NÃO existe como entidade própria**; hoje é alias de operator |
| **Delegation** | `lib/control-plane/security/delegation.ts` (`DelegationContext`, `resolveDelegation()→null`) | **SHAPE pronta, inativa**; invariante "operador preservado" já codificada |
| **Audit (spine canônico)** | `security/audit/{model,writer,factory,repository,gateway-sink}.ts` + Gateway `operator_audit_log` (00006/00007) | durável; intent→outcome; superset compatível |
| **Author / Actor** | `lib/control-plane/actor.ts` (`ActorContext.publicActor: null`, ADR-0007) | seam pronto; `publicActor` sempre null |
| **Agent** | Social `agent_profiles` + `agent.proto` (Ninja/Pulse/Oracle/Sentinel/Echo = platform agents) | é um domínio Social, **não** um identity domain |
| **Service** | `control-plane/registries/services.ts` | descriptors; nenhum é "identity" |
| **Session** | Gateway `operator_sessions` (`token_hash = sha256(token)`) | autoridade Gateway; `sessionId` no context = sha256 do cookie |
| **Correlation** | header `x-correlation-id` (default = `x-request-id`) | distinto de requestId e de sessionId |
| **Permission / Capability** | `types/auth.ts` (Permission), `registries/capabilities.ts`, `authorization.ts` | **fora do escopo — não alterar** |

## 2. Perguntas obrigatórias (respostas explícitas)

**Quem define `identityId` hoje?**
`operator-context.ts` → `build()`: `identityId: operator.id`. É literalmente atribuído como igual ao
`operatorId`, com comentário explícito de que IDENTITY-A vai separá-los.

**Onde ele nasce?**
Em `build()` (chamado por `buildOperatorContext` / `operatorContextFromOperator` /
`resolveOperatorContext`), a partir do `ConsoleOperator` retornado por `currentOperator()` →
Gateway `/v1/operator/auth/me`. O `ConsoleOperator` (`types/auth.ts`) **não tem campo de identity** —
só `id/displayName/username/email/phone/role/permissions`. Logo `identityId` nasce **derivado**, não
carregado do Gateway.

**Quem o consome?**
- `security/audit/model.ts` → `buildAuditEvent()` → `actor.identityId` no evento canônico.
- Qualquer rota que resolve `OperatorContext` (socialCommand, socialRead, audit routes).

**Quem o persiste?**
Hoje, **ninguém como identity distinta.** O evento de auditoria é persistido pelo `GatewayAuditRepository`
via `POST /v1/console/audit/events`, mas o **ingest body NÃO inclui identity** (`toIngestBody` envia
correlation/request/capability/status/target/authorization/reason/metadata/idempotency_key — sem actor).
O Gateway deriva `operator_id` da sessão. O schema `operator_audit_log` (00006+00007) tem `operator_id`
mas **não tem `identity_id` nem colunas de delegação**. Na leitura, `projectEvent()` faz
`identityId = operator_id` (linha 154). → **`identityId == operatorId` é físico no spine, não só no
context.**

**Quem o utiliza?**
O Console (audit read/investigation) exibe o actor; a UI trata operator e identity como a mesma coisa
hoje. Nenhum consumidor depende de identity ≠ operator (porque nunca diferem).

## 3. Stage 0.5 — o que já existe (NÃO duplicar)

| Artefato | Já existe? | Reutilizar |
|---|---|---|
| `OperatorContext` | SIM | **estender** (adicionar identity resolvida + delegation real), sem novo context |
| `DelegationContext` + resolver + guards | SIM (inativo) | **ativar** — não recriar shape |
| `ActorContext.publicActor` (ADR-0007) | SIM (null) | preencher via delegação autorizada |
| Audit model (`actor.identityId`, `delegation` block) | SIM | já carrega os campos — precisa **persistir** de verdade |
| Audit spine (Gateway `operator_audit_log`) | SIM | **migration aditiva** (padrão 00007) p/ `identity_id` + delegação; nunca renomear |
| Ingest body (`toIngestBody`) + `projectEvent` | SIM | estender aditivamente (identity + delegation) |
| Gateway `operators`/`operator_sessions` | SIM | autoridade de operator — **não** tocar auth |
| Registries / adapters / authorization / capabilities | SIM | **não duplicar, não alterar** |
| Modelo de "official identity" / ownership | **NÃO** | criar mínimo necessário (grant de delegação), sem ownership de conteúdo |
| Tabela de grants de delegação | **NÃO** | precisa de um store durável (decisão no ADR) |
| Proto/DTO de identity | **NÃO** | definir contrato mínimo (ADR) — aditivo |

**Conclusão de não-duplicação:** IDENTITY-A é **evolução da fundação existente**, não arquitetura nova.
Estender OperatorContext + ativar DelegationContext + tornar identity/delegation **persistíveis** no
spine (aditivo) + preencher `publicActor`. Nenhum novo registry, adapter, context ou modelo de authz.

## 4. Quem é o dono do domínio Identity? (o que o código permite concluir)

- **Operator identity durável → Gateway** (00006 header: "Gateway is the single authority for operator
  credentials, sessions, roles/permissions and audit. Console must consume this surface only").
- **Official identity (Ninja) → hoje é um AGENT do Social** (`agent_profiles`), **não** um identity
  domain. Não há ownership user↔agent↔operator em código (ADR-0007 confirma: "no user↔agent↔operator
  relationship in code").
- **Identity RESOLUTION (compor operator+delegation em identity efetiva) → Control Plane (Console
  server-side)** — é onde o OperatorContext já é construído.
- **NÃO CONCLUSIVO pelo código:** onde reside o *store durável de grants de delegação*. Não existe. O
  ADR precisa **decidir** (candidato natural: Gateway, coerente com "Gateway é autoridade de operator +
  audit"; alternativa: store Console-owned como o audit já admite). Documentado como decisão do ADR,
  não assumido.

## 5. Invariantes (a preservar / a introduzir)

**Preservar (já no código):**
- I1. Operador autenticado **nunca desaparece** (`delegation.ts` `assertOperatorPreserved`; ADR-0007).
- I2. Actor **nunca** vem do browser (`assertNoClientActor`, `rejectClientAssertedActor`,
  `rejectSelfDelegation`).
- I3. Authorization é fail-closed e **não muda** (SuperAdmin OU permission; capability = descrição).
- I4. Audit spine é **único** e aditivo; intent→outcome; sem auditoria paralela.
- I5. Autenticação/sessão/JWT **inalterados** (Gateway continua autoridade).

**Introduzir (IDENTITY-A):**
- I6. `identityId` deixa de ser alias: resolvido server-side (operator → identity efetiva), default =
  identity do próprio operador (retrocompatível: sem delegação, identityEffective == operator).
- I7. Delegação, quando ativa, é **aditiva** (public/subject) e **auditável** (persistida no spine).
- I8. Toda mutação resolve `Operador → Identity → Delegation → Audit` no servidor, sem valor do browser.

## 6. Dependências

- **Gateway (Stage 5):** migration aditiva em `operator_audit_log` (`identity_id`, `delegation_*`,
  `public_actor`), + ingest body + read projection — padrão exato de 00007. Sem novo endpoint proxy.
- **Delegação durável:** store de grants (decisão do ADR).
- **Social:** apenas como *subject* de delegação (agent Ninja) — **sem** alterar SOCIAL-B/Investigation.
- **Compatibilidade retroativa:** eventos antigos têm só `operator_id`; leitura deve continuar
  projetando `identityId = operator_id` quando `identity_id` for NULL.

## 7. Riscos

1. **Retrocompat de auditoria:** mudar `identityId==operatorId` sob eventos já gravados (identity_id
   NULL) — mitigado por default-para-operator na leitura.
2. **Store de grants inexistente:** decisão de ownership em aberto (Gateway vs Console) — risco de
   acoplamento se escolhido errado; ADR deve fixar sem bloquear AGENTS-A/SERVICE-OPS-A/IOC-EXECUTOR-A.
3. **Escopo:** delegação é a capability de maior abuso (ADR-0007) — V1 só grant explícito/revogável,
   **sem** impersonation/acting-as/session-switching (fora de escopo declarado).
4. **Contrato `/me`:** não expõe identity; resolver identity no Console evita mudar auth, mas mantém a
   autoridade durável fragmentada — documentar como decisão consciente.
5. **Preparar sem acoplar** AGENTS-A (ownership de agente), SERVICE-OPS-A, IOC-EXECUTOR-A: o modelo de
   identity/delegation deve ser genérico (subject = official_identity|agent) sem embutir ownership.

## 8. Decisão de método
Implementação **somente após aprovação** desta auditoria + do ADR. Sequência conservadora: estender
OperatorContext → resolução server-side → delegação (grant explícito/revogável) → Console (visualização
provenance) → Gateway (contrato aditivo) → auditoria (persistir identity+delegation). Tudo aditivo e
retrocompatível; suíte existente não pode regredir.
