# FEATURE-COMMUNITIES-V1 — Stage 0.5 UX PRESERVATION (obrigatório)

Aprendizado do AZTECA-SEARCH-UX-RESTORE: uma feature nova integra-se à experiência aprovada; nunca a
substitui/simplifica/apaga. Esta análise precede QUALQUER alteração de tela.

## Perguntas obrigatórias
**Quais telas serão modificadas?**
- `CommunityDetailScreen` (add Join/Leave + preencher Membros com dados reais + stats honestas).
- `HubScreen` — idealmente **nenhuma** mudança visual (segmentos/rails já reais). No máximo, garantir dados
  reais no segmento "mine".

**Quais widgets existentes serão reutilizados?**
community_tile, discussion_row, hub_segments, hub_skeleton, tipster_tile, InsightTabBar, `_Header`,
`_MembersTab`, `_DiscussionsTab`, InsightAvatar, EmptyState, ErrorState. Estados
offline/timeout/partial reaproveitam o padrão SEARCH-V1.

**Quais layouts já estão aprovados?**
- Hub: AppBar (back + título + SearchAction) → HubSegmentsBar → rails horizontais (Comunidades/Tipsters) +
  lista de Discussões, RefreshIndicator, skeleton, empty states por segmento.
- Community Detail: AppBar (nome) → header card (quadrado accent + nome + handle + "X ativos" + descrição) →
  **3 tabs: Discussões / Sinais / Membros** → TabBarView.

**Quais componentes NÃO podem ser removidos?**
As 3 tabs do detail, o header card, os rails do Hub, os segmentos, os empty/error states. A estrutura de
3 abas é a identidade da tela de comunidade.

**Existe risco de regressão visual?** SIM — alto. Adicionar Join/Membros/Stats tenta um "redesenho" da tela
de detalhe. É exatamente o erro do SEARCH-V1.

**Risco de substituir uma tela inteira?** SIM se criarmos uma "nova" CommunityScreen. PROIBIDO.

**Risco de simplificar UX?** SIM — tentação de remover a aba "Sinais" (hoje placeholder). Preservar.

**Risco de apagar identidade visual?** SIM — o header card e a paleta accent são a marca da tela.

→ Como respostas positivas existem, este documento é obrigatório e a implementação PARA aqui até aprovação.

## Impacto e alternativa menos destrutiva (plano de integração)
| Necessidade V1 | Alternativa destrutiva (PROIBIDA) | Integração aprovada |
|---|---|---|
| Join / Leave | Nova tela de membership / redesenhar detail | Botão de ação no **AppBar `actions`** (ou CTA dentro do `_Header` já existente), estado do viewer (is_member) vindo do detail enriquecido; otimista + rollback (padrão SEARCH-V1) |
| Ver membros (real) | Nova MembersScreen | Preencher o **`_MembersTab` existente** com dados reais + paginação; corrigir o bug do contrato `members` |
| Moderadores | Nova aba | Já derivável no `_MembersTab` via `roleLabel`/is_moderator (badge), sem nova aba |
| Admins | Inventar papel | **DOCUMENTAR ausência** — não renderizar "Admin" (não existe no domínio) |
| Stats | Novo painel pesado | Enriquecer o **header card** com contadores reais (member_count/active_now) já presentes |
| Sinais | Remover a aba | Manter a aba; ligar a sinais reais se houver contrato, senão empty honesto (não placeholder decorativo novo) |
| Posts da comunidade | Nova tela de feed | Só após DESIGN DECISION (posts.community_id). Se adiado, **não** adicionar aba falsa |

## Golden / evidência
Sem infra de golden confiável no repo (mesma situação do SEARCH-V1) → cobertura por testes comportamentais
de widget (detail mantém 3 abas; Hub mantém rails) + checklist visual no SMOKE. Antes de tocar código,
capturar baseline das telas aprovadas.

## Decisão
PROSSEGUIR para Stage 1 SOMENTE com o compromisso: CommunityDetail mantém as 3 abas e o header card; Join e
Membros reais são integrados nesses componentes; nenhuma tela nova substitui as aprovadas.

---
## ATUALIZAÇÃO — mudança de tabs AUTORIZADA pelo usuário
O usuário autorizou explicitamente reorganizar a tela de comunidade em **Sobre · Discussões · Membros ·
Estatísticas · Administração (quando aplicável)**, substituindo a estrutura aprovada anterior
(Discussões/Sinais/Membros). Justificativa (do usuário): a comunidade deve ter estrutura de navegação
própria e não parecer "um feed filtrado"; a aba Discussões é o feed oficial (domínio Discussions).

**Preservação ainda obrigatória**: header card + paleta accent + identidade visual do app; reusar
InsightTabBar, _Header, _MembersTab, EmptyState/ErrorState; Discussions ganham componente próprio (não os
cards de Post). NÃO criar telas novas que substituam CommunityDetailScreen — a evolução é DENTRO dela
(mais abas), preservando o header e a linguagem visual. A aba "Sinais" (placeholder) é removida por decisão
do usuário, não simplificação unilateral.

---
## STAGE 3 REALIZADO — evidência de preservação
CommunityDetailScreen EVOLUÍDA (mesma rota, mesmo header card aprovado), não substituída. Abas
Sobre/Discussões/Membros/Estatísticas/Administração compartilham o contexto agregado; troca de aba preserva
estado (header carregado 1x). Discussions com componente visual PRÓPRIO (não card de Post). UI por
capabilities (owner sem botão Sair). Isolado em features/hub/community/ — Atlas/Feed/Search/Perfil/Navegação
intocados. flutter analyze limpo, 130 testes, diff limpo. Ver STAGE3_EVIDENCE.md.
