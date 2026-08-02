# CONSOLE-IDENTITY-A — Security & Persistence Closeout

Corrige os DOIS bloqueadores da certificação, sem expandir escopo nem redesenhar arquitetura.

## Bloqueador 1 — resolução FAIL-CLOSED

### Antes × Depois
| Situação | ANTES (inseguro) | DEPOIS (fail-closed) |
|---|---|---|
| sem `delegation_id` | self | **self** (inalterado) |
| `delegation_id` válido/ativo | identidade delegada | **identidade delegada** (inalterado) |
| `delegation_id` inexistente | **silent self** | **DELEGATION_NOT_FOUND** (falha) |
| pertencente a outro operador | **silent self** | **DELEGATION_OPERATOR_MISMATCH** (falha) |
| revogado | **silent self** | **DELEGATION_REVOKED** (falha) |
| expirado | **silent self** | **DELEGATION_EXPIRED** (falha) |
| malformed / subject incompatível | **silent self** | **DELEGATION_INVALID** (falha) |

Regra: **delegação explicitamente solicitada nunca faz fallback silencioso para self.** Sem `delegation_id`
continua self. O fallback `identity_id NULL → operator_id` permanece **apenas na leitura de registros legados**
(nunca na escrita).

### Tabela de erros (Gateway → HTTP)
| Código interno | HTTP | `detail` público | Enumeração |
|---|---|---|---|
| DELEGATION_REVOKED | 409 | `delegation_revoked` | grant próprio — específico OK |
| DELEGATION_EXPIRED | 409 | `delegation_expired` | grant próprio — específico OK |
| DELEGATION_INVALID | 400 | `delegation_invalid` | malformed/subject — específico OK |
| DELEGATION_NOT_FOUND | 404 | `delegation_not_usable` | **indistinguível** de MISMATCH |
| DELEGATION_OPERATOR_MISMATCH | 404 | `delegation_not_usable` | **indistinguível** de NOT_FOUND |

NOT_FOUND e OPERATOR_MISMATCH retornam resposta byte-idêntica (impede enumerar grants de outros operadores);
o motivo real é preservado em log estruturado (`slog.Warn "delegation_not_usable" reason=...`) e na auditoria
interna. Mapeamento em `writeDelegationError` (Gateway); reusa `writeJSON` (padrão de erros existente).

### Audit ingest
`AuditIngest` agora: `Begin(tx)` → `resolveIdentityQ(tx, ..., forShare=true)` → INSERT → `Commit`. Grant
inválido → **rejeita o ingest** (tx rollback), nunca persiste como self. Grant válido → persiste
`identity_id/delegation_*/public_actor` com `operator_id` (executed_by) preservado.

## Bloqueador 2 — testes de integração PostgreSQL reais
`identity_integration_test.go` (`//go:build integration`), executado contra Postgres real (aplica as
migrations 00006/00007/00008 diretamente dos arquivos). **Todos verdes.** Cobertura dos 19 itens:

| # | Cenário | Subtest |
|---|---|---|
| 1/2/19 | migration up / down / sem resíduo | `migration_down_leaves_no_residue` |
| 3 | grant ativo | `resolve_self_and_delegated` |
| 4 | resolução self | idem |
| 5 | resolução delegada válida | idem |
| 11 | não-transitiva (subject terminal) | idem |
| 6 | grant inexistente → NOT_FOUND | `fail_closed` |
| 7 | grant estrangeiro → OPERATOR_MISMATCH | idem |
| 8 | revogado → REVOKED | idem |
| 9 | expirado → EXPIRED | idem |
| (malformed) → INVALID | idem |
| 10 | self-delegation rejeitada (CHECK subject_type) | `constraints_and_indexes` |
| 12 | revoke owner-only | `revoke_owner_only_and_idempotent` |
| 13 | revogação idempotente | idem |
| 14 | audit persiste operator+identity+delegation+public_actor | `audit_persist_and_reject` |
| 15 | audit rejeita grant inválido (nada persistido) | idem |
| 16 | leitura legado NULL → operator | `legacy_null_read` |
| 17 | concorrência resolve vs revoke (FOR SHARE bloqueia) | `resolve_vs_revoke_concurrency` |
| 18 | constraints + índices esperados | `constraints_and_indexes` |

Evidência (real PG): `--- PASS: TestIntegration_Identity (1.33s)` com 8 subtests PASS.
Execução: `GATEWAY_TEST_DATABASE_URL=... go test -tags=integration ./internal/interfaces/http/console/ -run TestIntegration_Identity -v`.
Sem framework novo — pgx + arquivos de migration reais + goose-lite parser no teste.

## Análise da janela de concorrência
- **Garantia local (Gateway):** a resolução + a persistência do audit ocorrem na **MESMA transação**, com
  `SELECT ... FOR SHARE` na linha do grant. Um `revoke` concorrente (UPDATE) **bloqueia** até o commit da
  transação de ingest — provado em `resolve_vs_revoke_concurrency`. Isso fecha a janela evitável: **um grant
  revogado não entra num registro de auditoria persistido**.
- **Resolução ⇄ ação de domínio:** NÃO estão na mesma transação — a ação real (ex.: hide) ocorre no **Social**,
  outro serviço. Não há transação distribuída (nem inventada).
- **Risco residual (documentado):** entre o *intent* (AUTHORIZED, escrito antes) e o *outcome* (COMPLETED,
  escrito depois), um grant pode ser revogado. Nesse caso o **outcome ingest é rejeitado** (fail-closed) →
  a auditoria fica com AUTHORIZED sem COMPLETED. O writer do Console marca `reconciliationNeeded=true` e emite
  `audit_reconciliation_needed` — representação honesta de não-atomicidade distribuída. Nenhuma persistência
  silenciosa como self.
- **Consistência garantida:** (a) escrita de auditoria com provenance delegada é atômica e consistente com o
  estado do grant no instante do commit; (b) revogações não podem "vencer" uma escrita já commitada nem
  contaminar uma escrita em andamento; (c) leituras legadas (NULL) continuam projetando identity==operator.

## Compatibilidade preservada
Autenticação, sessão, `authorization.ts`, capability semantics, Audit Spine intent/outcome, Social
Investigation, Social Enforcement, Atlas, adapters tipados, registries, server-only boundaries: **inalterados.**
Mudanças 100% aditivas; migration 00008 reversível sem resíduo (provado).

## Arquivos alterados
- Gateway: `internal/interfaces/http/console/identity.go` (fail-closed + typed errors + FOR SHARE querier +
  mapping), `audit_ingest.go` (transacional + reject), `identity_test.go` (+ mapping test),
  `identity_integration_test.go` (**novo**, 19 cenários). (migration 00008 já existente.)
- Console: nenhuma mudança de comportamento necessária — a garantia fail-closed vive na autoridade (Gateway);
  o adapter/rotas já propagam erro (throw) em vez de self silencioso.

## Readiness final
CODE READY / NOT_DEPLOYED. Bloqueadores 1 e 2 resolvidos e provados. Base segura para CONSOLE-AGENTS-A.
Ordem operacional: migration 00008 → Gateway → Console → smoke self → smoke grant válido → smoke revogado/
expirado → verificação do Audit Spine.
