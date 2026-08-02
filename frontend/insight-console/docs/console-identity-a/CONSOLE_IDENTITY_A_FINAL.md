# CONSOLE-IDENTITY-A — Final Validation Report (Stages 1→6)

**Status:** CODE READY / NOT_DEPLOYED. No deploy, no Docker publish, no GCloud/Robozão commands, no
migration applied, no commit — code + docs delivered for review.

## 1. O que foi implementado (aditivo, retrocompatível)

### Stage 5 — Gateway (autoridade oficial de Operational Identity + Delegation)
- **migration `00008_operational_identity_delegation.sql`** (aditiva, NÃO aplicada): colunas NULLable em
  `operator_audit_log` (`identity_id, delegation_id, delegation_subject, delegation_subject_type,
  public_actor`) + tabelas `operational_identities` (registro de subjects delegáveis) e `delegation_grants`
  (store autoritativo). Down reversível. Nenhum rename, nenhum rewrite.
- **`internal/interfaces/http/console/identity.go`**: `resolveIdentity` (autoritativa — grant
  desconhecido/estrangeiro/revogado/expirado ⇒ identity=operator, forja impossível), `IdentityResolve`
  (GET), `DelegationGrant` (POST), `DelegationRevoke` (DELETE, dono-apenas), `DelegationList` (GET).
- **`audit_ingest.go`**: aceita apenas `delegation_id` (REFERÊNCIA); resolve identity/subject/public_actor
  server-side; persiste nas colunas novas; a leitura projeta identity/delegation/public_actor com fallback
  `identity_id NULL → operator_id`. `executed_by` sempre presente.
- **rotas** em `cmd/gateway/main.go` sob `/v1/console/identity/*` (service-token + sessão de operador).

### Stages 1–2 — Console (OperatorContext + resolução server-side)
- `operator-context.ts`: `identityId` deixou de ser alias estrutural — agora é a SAÍDA da resolução
  (default self: identity==operator, kind="operator"); novos campos `identityKind` + `publicActor`;
  `delegation` real. `withResolvedIdentity()` troca a identidade pelo subject delegado **preservando o
  operador** (rejeita delegação cujo operador ≠ autenticado). `assertNoClientActor()` passa a descartar
  `identity_id/identityId/delegation/delegation_id/public_actor/subject_id` (browser nunca forja).

### Stage 3 — Console (delegation adapter)
- `adapters/identity.ts`: `resolveOperationalIdentity / grantDelegation / revokeDelegation /
  listDelegations` sobre o Gateway (autoridade), reusando os tipos + `assertOperatorPreserved` de
  `delegation.ts` (sem modelo paralelo).

### Stage 4 — Console (Audit Spine aditivo, único)
- `audit/model.ts`: `AuditActor.publicActor`; `buildAuditEvent` popula operator+identity+publicActor+
  delegation. `gateway-sink.ts`: `toIngestBody` envia só `delegation_id`; `projectEvent` lê identity/
  delegation/public_actor com fallback NULL→operator. `repository.ts` idem. **Pipeline intacto**
  (intent→outcome), sem auditoria paralela.

### Stage 6 — Console (visualização, sem redesign)
- BFF `app/api/v1/identity/{resolve, delegations, delegations/[id]}` (server-owned, operator-authed).
- `components/identity/ProvenanceChain.tsx` (Operator→Identity→Delegation→Public Actor, executed_by
  sempre visível) + `app/(console)/administration/identity/page.tsx` (read-first). Investigation Plane e
  Social Enforcement **inalterados**.

## 2. Contratos (aditivos; nada removido)
| Rota nova (Gateway) | Método | Retorno |
|---|---|---|
| /v1/console/identity/resolve | GET | executed_by, operator_id, identity_id, identity_kind, public_actor, delegation |
| /v1/console/identity/delegations | GET/POST | grants do operador / cria grant |
| /v1/console/identity/delegations/{id} | DELETE | revoga (dono-apenas) |
Audit ingest/read: **superset aditivo** — campos antigos inalterados; novos NULLable.

## 3. Garantias preservadas (verificadas)
- SECURITY-A0, Authorization (`authorization.ts`), Capability Registry, Investigation Plane, Social
  Enforcement: **nenhuma alteração**. Autenticação/sessão/JWT: **inalterados**.
- Audit Spine **único** e íntegro; intent→outcome; `executed_by` sempre = operador real.
- Delegação **explícita, revogável, auditável, NÃO transitiva** (subject terminal; sem impersonation/
  acting-as/session-switch/nested/automática).
- Browser **não forja** identity/delegation/public_actor (strip no Console + autoridade no Gateway).
- **Retrocompat**: eventos antigos (identity_id NULL) leem identity==operator.

## 4. Testes
- **Console: 100 passed** (90 existentes + 10 novos IDENTITY-A: default self, resolveDelegation null,
  withResolvedIdentity+operator preserved, foreign-operator rejeitado, assertOperatorPreserved,
  rejectSelfDelegation, strip de campos do browser, audit carrega operator+identity+publicActor+delegation,
  self==operator, ingest só delegation_id). `tsc --noEmit` limpo; `check:boundaries` OK.
- **Gateway: build/vet/test OK** (+3 testes: identityJSON self backward-compat, delegado preserva operador,
  deref/ts nil-safe). `git diff --check` limpo (ambos os repos).
- SQL de resolução/grant/revoke exige Postgres para prova de execução (padrão do repo) → coberto por
  lógica pura + projeção; migration NÃO aplicada.

## 5. Critérios de aceite — atendidos
✓ identityId não é mais alias estrutural (saída de resolução). ✓ Resolução exclusivamente server-side.
✓ Gateway = autoridade única de Delegation + Operational Identity + grant store. ✓ Audit persiste
executed_by/identity/delegation/public_actor sem quebrar registros antigos. ✓ Delegação explícita/
revogável/auditável/não-transitiva. ✓ Browser não forja identidade. ✓ SECURITY-A0/Authorization/Capability/
Investigation/Enforcement inalterados. ✓ Suíte existente verde + novos testes.

## 6. Limitações remanescentes
- `operational_identities` é um registro fino (nomes de subjects); a existência real de subjects
  (official identity / agent) é AGENTS-A / official-identity — fora de escopo.
- `public_actor` modelado e auditável, mas nenhuma superfície pública o renderiza ainda (capability
  `social.official_identity.publish` NÃO ativada — sprint futura).
- Resolução delegada faz um round-trip ao Gateway; o caminho self é local (sem custo).
- Migration 00008 pendente de aplicação (operador) — reexecuta idempotente.

## 7. Impacto nas próximas sprints
- **CONSOLE-AGENTS-A:** `subjectType=agent` já é genérico; ownership de agente pluga sobre delegação sem
  alterar o modelo.
- **CONSOLE-SERVICE-OPS-A / IOC-EXECUTOR-A:** o evento de auditoria já carrega `executed_by`/identity/
  delegation — provenance pronta para o executor, sem acoplamento.
- Preparado **sem bloquear**: nenhum novo registry/adapter/authz/pipeline; tudo aditivo.

## 8. Deploy (operado pelo usuário — NÃO executado)
Ordem: migration 00008 (Gateway DB) → Gateway → Console (build). Aditivo; rollback via goose down
(preserva dados; audit volta a ler identity==operator).
