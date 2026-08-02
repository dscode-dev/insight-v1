# FEATURE-COMMUNITIES-V1 — Stage 3 (Azteca) Evidence

## Classificação honesta
| Eixo | Status |
|---|---|
| Integração (não redesign) | READY |
| Preservação de UI | READY (header card aprovado mantido; mesma rota) |
| Capabilities-driven UI | READY (nenhum `if(role==...)`) |
| Estados (loading/empty/error/partial) | READY |
| Paginação (membros/discussões) | READY (cursor + dedupe + página-falha preserva itens) |
| Join/Leave otimista + rollback | READY |
| Deep links | READY (validados vs rotas reais; Gateway constrói) |
| Isolamento (Atlas/Feed/Search/Perfil/Nav) | READY (nada alterado) |
| Deploy | NOT_DEPLOYED |

## Integração (sprint de integração, não redesign)
`CommunityDetailScreen` foi **evoluída, não substituída** — mesma rota `/hub/community/:id`, mesmo header card
aprovado (quadrado accent + nome + @slug + presença + descrição). O corpo ganhou seções por abas
compartilhando o MESMO contexto agregado: **Sobre · Discussões · Membros · Estatísticas · Administração**
(a última só quando `can_view_admin_panel`). Sem segunda tela concorrente.

## Arquivos (Flutter-only, isolado sob lib/features/hub/community/)
- `model/community_models.dart` — DTOs do contrato público; **CommunityDetail SEM `members`** (bug eliminado);
  capabilities default all-false (nunca expõe admin por acidente).
- `data/community_service.dart` — GET detail/members/discussions + POST join + DELETE membership (CancelToken).
- `navigation/community_deep_link.dart` — valida deep_link do Gateway vs rotas reais (padrão SEARCH-V1).
- `state/community_providers.dart` — 3 controllers autoDispose.family+keepAlive: detail (carrega 1x; join/leave
  **otimista + rollback**; capabilities do servidor), members (cursor + filtro role no MESMO endpoint), discussions (cursor).
- `widgets/discussion_card.dart` — componente PRÓPRIO de Discussion (título + respostas + reações + atividade);
  **não reusa card de Post**.
- `widgets/member_row.dart` — linha de membro (badge de role = display).
- `community_detail_screen.dart` (mesmo path) — header preservado + abas capability-driven; troca de aba
  preserva estado (AutomaticKeepAliveClientMixin; header não recarrega).

## Capabilities (autorização exclusiva do Gateway)
Botão Entrar/Sair, aba Administração, linhas de gerência — TODOS por capabilities. **Owner não vê botão
Sair** (canLeave=false). Zero `if(role==OWNER)`. Role só aparece como badge/label.

## Estados / Performance / Isolamento
Cada seção tem loading/empty/error e falha independente (uma seção fora não derruba a tela); partial banner no
header. Membros/Discussões com scroll infinito, dedupe, retry; página-falha preserva itens carregados. Troca
de aba preserva estado; header carregado 1x. Nenhuma mudança em Atlas, Feed Global, Search, Perfil ou
navegação — feature isolada em `features/hub/community/` + reescrita do screen (mesma rota).

## Validação
`flutter analyze` **No issues found** · `flutter test` **130 passed** (+10 Stage 3: aggregate sem members,
capabilities default-false, partial honesto, deep-link validator, join otimista+rollback, paginação+dedupe,
filtro role no mesmo endpoint) · `git diff --check` limpo. Backend intocado nesta etapa. **Sem deploy.**

## Comparação de layout (antes × agora)
| Aspecto | Antes (aprovado) | Agora |
|---|---|---|
| Rota | /hub/community/:id | **igual** |
| Header card | accent+nome+handle+"X ativos"+descrição | **preservado** (+ contadores reais + ação por capability) |
| Abas | Discussões/Sinais/Membros (Sinais=placeholder; Membros=mock) | **Sobre/Discussões/Membros/Estatísticas/Administração** (todas dados reais) |
| Membros | lista embutida (mock, quebrava em live) | endpoint `/members` paginado real |
| Discussões | DiscussionRow (bundle) | card próprio sobre `/discussions` real |
| Join/Leave | inexistente | otimista + rollback via `/join`,`/membership` |

## Limitações restantes
1. **Mutações administrativas** (promover/remover/configurar) não têm endpoint na V1 — a aba Administração é um
   OVERVIEW real (permissões + composição), sem botões-fantasma. Ações = trabalho futuro (novos endpoints).
2. **avatar/banner** de comunidade não existem no domínio → não renderizados (honesto).
3. **Discussão: autor** não vem enriquecido no feed do Gateway (só author_id) → card foca na conversa; enriquecer autor = evolução futura.
4. **Órfãos**: `hub.dart CommunityDetail` + `hub_service.communityDetail` + `hub_provider.communityDetailProvider` ficaram sem uso (a tela nova usa o novo provider). Analyze limpo; cleanup opcional futuro.
5. **Golden tests**: não há infra golden confiável no repo (mesma situação do SEARCH-V1) → cobertura comportamental + checklist visual no smoke.

## Pendências para certificação (pós-checkpoint)
Deploy operado pelo usuário (migration 00011 → Social → Gateway → app) + smoke; certificação READY só após isso.
