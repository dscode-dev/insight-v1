# FEATURE-COMMUNITIES-V1 — Migration Safety Report (00011_community_roles.sql)

Aditiva e segura por construção. Ainda NÃO aplicada em nenhum ambiente.

## Objetos criados (todos IF NOT EXISTS)
| Objeto | Definição |
|---|---|
| `communities.owner_user_id` | `UUID NULL REFERENCES users(id) ON DELETE SET NULL` |
| `community_members.role` | `VARCHAR(16) NOT NULL DEFAULT 'member' CHECK (role IN ('owner','admin','moderator','member'))` |
| backfill | `UPDATE community_members SET role='moderator' WHERE is_moderator=TRUE AND role='member'` |
| `ux_community_members_one_owner` | UNIQUE parcial `(community_id) WHERE role='owner'` |
| `ix_community_members_listing` | `(community_id, joined_at, user_id)` |
| `ix_communities_owner_user_id` | `(owner_user_id) WHERE owner_user_id IS NOT NULL` |

## Cenários validados (por análise — execução requer Postgres do ambiente)
### Banco VAZIO
Adiciona colunas + índices em tabelas sem linhas. Backfill não afeta nada. **Seguro.** Novas comunidades já
nascem com owner (repo InsertOwned, fora da migration).

### Banco POPULADO (comunidades/membros legados)
- `owner_user_id` entra NULL para TODAS as comunidades existentes → classificadas **OWNER_UNASSIGNED**
  (nenhum owner fabricado — decisão deliberada, ver §OWNER_UNASSIGNED).
- `role` DEFAULT 'member' preenche todas as linhas; backfill promove `is_moderator=TRUE` → 'moderator'.
- **`ux_community_members_one_owner`**: como o backfill NÃO cria nenhum 'owner', não há risco de duplicidade
  → o índice único parcial é criado sem conflito mesmo com dados preexistentes. **Seguro.**
- `is_moderator` preservado (compat). Nenhuma linha perdida, nenhum default destrutivo.

### Idempotência
Todo DDL usa `IF NOT EXISTS`. O backfill é idempotente: após a 1ª execução as linhas já são 'moderator', e o
guard `AND role='member'` impede reprocessá-las. Reexecutar a migration é seguro (no-op efetivo).

### Rollback (goose Down presente)
`DROP INDEX` (x3) + `DROP COLUMN role` + `DROP COLUMN owner_user_id`. Efeito: a busca por papéis/owner deixa
de existir; **nenhum outro dado é perdido** (is_moderator permanece). Recomendação: se rollback for apenas do
App/Gateway, MANTER 00011 aplicada (imagens antigas ignoram coluna/tabela novas).

### OWNER_UNASSIGNED (comportamento esperado)
Comunidades legadas e de competição ficam com `owner_user_id = NULL`. A UI expõe `owner_assigned=false`
honestamente; nenhuma capability de dono é concedida a ninguém indevidamente. Atribuição de owner a essas
comunidades = **tarefa operacional futura** (script dedicado; nunca escolher "primeiro membro"). Documentado
em Tech Debt V2.

## Índices — impacto
3 índices novos (2 B-tree pequenos + 1 unique parcial). Em tabelas de communities/community_members de porte
V1 (baixo volume), criação é sub-segundo. Sem `CONCURRENTLY` (tabelas pequenas; janela de manutenção do
deploy manual). Se o volume crescer muito no futuro, considerar `CREATE INDEX CONCURRENTLY`.

## Tempo estimado
Volume V1 atual (comunidades/membros na casa de dezenas–centenas): **< 1s** total (ALTERs + backfill +
índices). Confirmar no ambiente antes de janela de produção.

## Pré-condições
Role `insight` com permissão de ALTER nas tabelas (owner do schema). Sem extensões novas (diferente da 00010,
que exigia pg_trgm). Nenhuma dependência externa.
