# FEATURE-COMMUNITIES-V1 — UX Regression Checklist

Mesmo rigor do pós-SEARCH. Confirmação explícita de que nenhuma UX aprovada regrediu.

| Item | Status | Evidência |
|---|---|---|
| **Explore (Search)** não foi alterada | ✅ INALTERADA | esta vertical não tocou `lib/features/search/**` além do já existente; testes de search (models/controller/ux-restore) seguem verdes |
| **Feed Global** não foi alterado | ✅ INALTERADO | nenhum arquivo de `features/home`/feed alterado; ADR-0001 mantém Posts fora do domínio de comunidade |
| **Perfil** não foi alterado | ✅ INALTERADO | nenhum arquivo de `features/profile` alterado |
| **Atlas** não foi alterado | ✅ INALTERADO (congelado) | nenhuma alteração em Atlas em nenhuma stage |
| **Navegação global / bottom nav** | ✅ INALTERADA | rota `/hub/community/:id` idêntica; router não modificado |
| **Community Detail — identidade visual** | ✅ PRESERVADA | header card aprovado mantido (accent+nome+@slug+presença+descrição); mesma paleta/espaçamentos |
| **Nenhuma tela existente substituída** | ✅ CONFIRMADO | CommunityDetailScreen EVOLUÍDA no mesmo arquivo/rota; HubScreen intacto; nenhuma segunda tela concorrente |
| Discussions com componente próprio (não card de Post) | ✅ | `discussion_card.dart` novo, não reusa timeline |
| UI por capabilities (sem `if(role==...)`) | ✅ | owner sem botão Sair; aba Administração só com can_view_admin_panel |

## Superfície de mudança (Flutter)
- MODIFICADO: `lib/features/hub/community_detail_screen.dart` (evoluído, mesma rota).
- NOVO (isolado): `lib/features/hub/community/**` (models/data/state/navigation/widgets).
- INALTERADO: search, feed/home, profile, radar, live, notifications, routing/router.dart, models/hub.dart,
  todo o resto.

## Validação automatizada
`flutter analyze` limpo · `flutter test` **130 passed** (120 pré-existentes + 10 novos; nenhum regrediu) ·
`git diff --check` limpo. Sem infra de golden no repo → checklist visual manual no SMOKE.

## Conclusão
Nenhuma regressão de UX. A lição da Search (integração, nunca substituição) foi aplicada e verificada.
