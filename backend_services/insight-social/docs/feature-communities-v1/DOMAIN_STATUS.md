# FEATURE-COMMUNITIES-V1 — DOMAIN STATUS

Classificação por capacidade do prompt (descobrir, detalhes, entrar, sair, membros, admins, moderadores,
posts, stats, navegação, deep links, capabilities, paginação, offline, partial).

| Capacidade | Status atual | Ação COMMUNITIES-V1 |
|---|---|---|
| Descobrir comunidades reais | PARTIAL (hub bundle; segmentos hot/fresh reais, mine real via ListForUser) | Manter Hub aprovado; garantir dados reais |
| Detalhes completos | PARTIAL (community + discussions) | Enriquecer detail (stats, membership do viewer) sem redesenho |
| Entrar (Join) | BACKEND_ONLY (gRPC, sem gateway) | Expor `POST /v1/hub/communities/{id}/join` |
| Sair (Leave) | BACKEND_ONLY | Expor `DELETE …/join` (ou /leave) |
| Ver membros | MOCK_ONLY (Flutter) + CONTRACT_MISSING | ListMembers RPC + projection + rota gateway |
| Ver admins | ABSENT (sem papel) | DOCUMENTAR ausência; não inventar |
| Ver moderadores | PARTIAL (is_moderator) | Derivar de members (flag), sem promoção nesta vertical |
| Ver posts da comunidade | ABSENT (posts sem community_id) | DESIGN DECISION (linkage) antes de implementar |
| Estatísticas reais | MINIMAL (member_count/active_now) | DTO de stats honesto sobre contadores reais |
| Navegar entre usuários | READY (deep links user) | Reusar cards/rotas existentes |
| Navegar para posts | READY (se houver feed) | Depende da decisão de feed |
| Deep links | READY (gateway-built no Search; hub route existe) | Gateway constrói; Flutter consome |
| Capabilities reais | ABSENT | Criar (enabled/absent honesto) |
| Paginação | PARTIAL (List NEWEST keyset; discussions cursor) | Estender p/ members/feed |
| Offline / partial | READY (padrão SEARCH-V1) | Reusar estados |

## Riscos
- Corrigir o bug de `members` sem quebrar mock.
- Não transformar CommunityDetail (3 tabs aprovadas) numa tela nova.
- Contadores active_now/member_count: confirmar quem atualiza (evitar stats mentirosas).
