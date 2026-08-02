# FEATURE-COMMUNITIES-V1 — Stage 2 (Gateway Orchestrator) Evidence

## Classificação honesta
| Eixo | Status |
|---|---|
| Contrato público | READY (DTOs Gateway-owned, sem reuso de proto) |
| Orquestração | READY (fan-out paralelo + partial + timeout + correlation + cache + rate limit + métricas) |
| Capabilities | READY (motor explícito; owner-can't-leave respeitado) |
| Social read support | CODE READY / SQL needs-pg (GetStats/GetMembership) |
| Testes | READY (Gateway 12 casos communitybff; Social 19 mantidos) |
| Deploy | NOT_DEPLOYED (sem migration aplicada, sem deploy) |

## O Gateway é Orchestrator, não espelho
- **Detail = agregado**: fan-out paralelo para Social `GetCommunity` (crítico) + `GetStats` (não-crítico) +
  `GetMembership` (por-viewer, NotFound = not_member normal). WaitGroup join (sem goroutines órfãs); contexto
  de entrada propaga a MESMA correlation id; timeout/disconnect cancela todas as chamadas.
- **Sem arrays no detalhe**: membros/admins/moderadores só via `/members` paginado. Bug latente (Flutter
  exigia `members`) resolvido pelo contrato: o detalhe traz **contadores + role_counts + capabilities +
  viewer_role + membership_status**, header renderizável sem chamadas extras.
- **DTOs canônicos** (`dto.go`): Gateway-owned; mapeamento proto→DTO isolado em `client.go`. Social pode
  evoluir sem quebrar o contrato público.
- **Capabilities** (`capabilities.go`): can_join/can_leave/can_create_discussion/can_delete_discussion/
  can_manage_members/can_invite_members/can_manage_settings/can_view_admin_panel. Cliente só renderiza;
  enforcement final no domínio Social. **owner → can_leave=false**.

## Social (aditivo, read-only, SEM migration nova)
proto: `GetMembership`, `GetStats` (+ `CommunityStats`, `RoleCounts`). repo: GetMembership (ErrNotMember) +
GetStats (2 queries: GROUP BY role + scalars active_now/discussion_count; discussion_count = COUNT em
Discussions — nunca Posts). service+gRPC+fake. `buf breaking` PASS.

## Endpoints (ver COMMUNITIES_API.md)
GET detail · GET members (cursor + `?role=` projeção, SEM endpoints duplicados) · GET discussions (feed =
Discussions apenas) · POST join · DELETE membership (leave; owner→409).

## Owner via X-User-Id
Join/Leave/CreateTopic derivam o user da **sessão verificada** (authmw), nunca do corpo. Regra de
autorização no Gateway; validação final permanece no domínio Social (invariantes Stage 1).

## Cache / Partial / Timeout / Correlation / Rate limit / Métricas
StatsCache por community_id (user-independent; viewer_role/capabilities nunca cacheados; invalidado em
join/leave). Partial honesto (failed_sections; core falho = erro). Timeout 4s → 504. Correlation reusada no
fan-out. Rate limit 60/10s/user → 429. 6 métricas Prometheus no registry compartilhado.

## Validação executada
Gateway: `go build ./...` OK · `go vet ./...` OK · `go test ./...` sem falhas (communitybff **12 casos**) ·
`git diff --check` limpo. Social: build/vet/test OK (community **19 casos**) · diff limpo. Protos: diff limpo
(só community.proto; stubs gitignored via path-replace). **NENHUM deploy, NENHUMA migration aplicada.**

## Pendências explícitas para o Stage 3 (Azteca)
1. Consumir o Detail agregado no CommunityDetailScreen — abas **Sobre · Discussões · Membros · Estatísticas ·
   Administração** (evoluir a tela aprovada, sem substituí-la; preservar header card + accent).
2. Corrigir o modelo Flutter `CommunityDetail` (remover `members` obrigatório) → consumir contadores +
   capabilities; aba Membros consome `/members` paginado.
3. Componentes visuais PRÓPRIOS para Discussions (respostas/participantes/atividade/status) — NÃO reusar
   cards de Post.
4. Join/Leave via novas rotas (otimista + rollback); renderização por **capabilities** (nunca deduzir de
   role); owner sem botão Leave.
5. Deep links validados contra rotas reais (padrão SEARCH-V1); Estatísticas a partir de role_counts/contadores
   reais; Administração gated por can_view_admin_panel.
6. Integração: abrir Community Detail a partir do Search; perfil lista comunidades reais.

## Riscos residuais
- SQL de GetStats/GetMembership precisa de pg para prova de execução (padrão do repo).
- avatar/banner/privacy: comunidades não têm mídia nem privacidade no domínio → expostos como vazio/"public"
  honestos (documentado, não fabricado); evolução futura.
- Handler antigo `social.GetCommunityDetail` ficou órfão (rota reapontada ao orchestrator); remoção/cleanup
  opcional futura (não afeta build).
