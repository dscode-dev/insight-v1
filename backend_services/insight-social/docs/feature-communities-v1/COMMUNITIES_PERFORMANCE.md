# FEATURE-COMMUNITIES-V1 — Performance Checklist (qualitativo)

Sem benchmark formal (requer pg + carga). Análise de referência para otimização futura.

## Community Detail (GET /v1/hub/communities/{id})
- **Chamadas upstream (fan-out máximo): 3, em PARALELO** — `GetCommunity` (crítico) + `GetStats` +
  `GetMembership`. WaitGroup join; timeout de 4s compartilhado; cancelamento propaga a todas.
- **Com cache de stats quente: 2 chamadas** (pula `GetStats`).
- **Cacheado**: StatsCache por `community_id` (projeção user-independent), TTL 30s, invalidado em join/leave.
- **NÃO cacheado**: community core (barato, 1 row PK) e viewer membership (por-usuário, precisa ser fresco).
- **N+1**: nenhum. Cada seção é 1 query. Membros = 1 JOIN (não N+1). Stats = 2 queries fixas (GROUP BY role +
  scalars com subquery COUNT discussions).
- Header renderizável do agregado, **sem chamadas extras** do cliente.

## Members (GET .../members)
- **Keyset pagination** (role-priority, joined_at, user_id), `limit+1` para has-more, SEM offset.
- 1 query com **JOIN users** (perfil público) → sem N+1.
- Filtro por role = **projeção na MESMA query** (nunca 3 chamadas paralelas owner/admin/mod).
- Cliente: scroll infinito incremental + dedupe por user_id + página-falha preserva itens.

## Discussions (GET .../discussions)
- Keyset via Social `Discussion.ListForCommunity` (cursor). Consumo incremental no cliente (mesmo padrão).

## Join / Leave
- 1 mutação + 1 `GetStats` de refresh (para devolver member_count/capabilities atualizados). Cache de stats
  invalidado. Cliente é **otimista** (não espera round-trip para refletir na UI).

## Pontos de atenção / otimização futura
- StatsCache é in-memory single-instance; migrar para Redis quando o Gateway escalar horizontalmente
  (interface já isolada). Documentado em Tech Debt V2.
- `GetStats` faz `COUNT(*)` de discussions por comunidade; se o volume crescer muito, considerar contador
  materializado (como member_count já é).
- Rate limit por usuário: 60 leituras/10s (protege upstream de loops de UI).
