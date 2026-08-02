# FEATURE-COMMUNITIES-V1 — Technical Debt (V2 backlog)

Lista única e centralizada das pendências deliberadamente adiadas. Nenhuma bloqueia a V1.

| # | Dívida | Contexto / Decisão | Escopo futuro |
|---|---|---|---|
| 1 | **Transferência de ownership** | Capability AUSENTE por design na V1 (owner protegido contra saída via ErrOwnerCannotLeave; ErrTransferUnsupported). | Endpoint + fluxo de transferência (owner→novo owner atômico) + UI |
| 2 | **Endpoints administrativos (mutações)** | Domínio tem invariantes de authz (CanChangeRole etc.) mas NÃO há RPC/rota de promover/rebaixar/remover/configurar. Aba Administração é overview real, sem botões-fantasma. | RPCs Social (SetRole/RemoveMember-by-admin/UpdateSettings) + rotas Gateway + UI de gestão |
| 3 | **Avatar / banner de comunidade** | Não existem no domínio; expostos como vazio honesto. | Coluna + storage (MinIO) + upload + render |
| 4 | **Enriquecimento de autor na discussão** | Feed de discussões traz só author_id (sem nome/avatar). | Gateway enriquece autor (JOIN users) no DTO de discussão |
| 5 | **Cleanup de órfãos** | `hub.dart CommunityDetail` + `hub_service.communityDetail` + `hub_provider.communityDetailProvider` ficaram sem uso (analyze limpo). Handler Gateway `social.GetCommunityDetail` + `CommunityDetailResponse` órfãos (rota reapontada). | Remover código morto |
| 6 | **Remoção futura de `is_moderator`** | Mantido por compat (derivado de role). Parar de ler como verdade após Social+Gateway+Azteca migrarem 100% para `role`. | DROP COLUMN em migration futura + limpar mapeamentos |
| 7 | **ADR de unificação editorial** | ADR-0001 fixou Posts×Discussions separados na V1. Avaliar Post único com escopo (GLOBAL\|COMMUNITY)+community_id. | ADR V2 (só decisão; sem implementação na V1) |
| 8 | **StatsCache → Redis** | Cache in-memory single-instance; interface já isolada. | Impl Redis quando Gateway escalar horizontalmente |
| 9 | **discussion_count materializado** | Hoje COUNT(*) por comunidade em GetStats. | Contador materializado se volume crescer |
| 10 | **Atribuição de owner a OWNER_UNASSIGNED** | Comunidades legadas/competição sem owner determinístico. | Script operacional de atribuição (nunca "primeiro membro") |

Nenhum item acima é bloqueador de release. Todos documentados para não carregar dívida "invisível".
