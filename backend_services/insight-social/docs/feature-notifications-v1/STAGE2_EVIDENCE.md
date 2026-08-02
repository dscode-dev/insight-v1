# FEATURE-NOTIFICATIONS-V1 — Stage 2 (Gateway Orchestrator) Evidence

## Classificação honesta
| Eixo | Status |
|---|---|
| Contrato público | READY (DTOs Gateway-owned; icon/color/capabilities) |
| Orquestração | READY (list=List+UnreadCount, partial, timeout, unread cache) |
| Deep link validation | READY (inválido → ação removida, notificação mantida) |
| Testes | READY (notificationbff 7 casos) |
| Deploy | NOT_DEPLOYED |

## Os 10 ajustes — todos incorporados
1. **NotificationDTO ≠ proto** — `dto.go` Gateway-owned (id/type/priority/title/body/icon/color/deeplink/
   created_at/read/payload/capabilities); mapeamento proto→DTO só em `client.go`.
2. **Icon + color no contrato** — `typePresentation` (Gateway-owned): community_join→person_add/#56C596,
   discussion_reply→reply/#5BA8FF, mention→alternate_email/#FFC857, reaction→favorite/#FF6B9D,
   system→campaign/#B388EB. Mudar o visual de um tipo = 1 linha no Gateway; o Flutter só renderiza.
3. **Deep link validation** — `deeplink.go` valida contra rotas reais (/users/,/hub/community/,/discussion/,
   /post/). Vazio/malformado/rota inexistente → deeplink "" + `can_open=false` (ação removida), **notificação
   mantida**; a lista nunca quebra.
4. **Capabilities por item** — can_open/can_mark_read reais; can_delete/can_archive/can_share=false na V1.
5. **Partial honesto** — se UnreadCount falha e List funciona → `partial=true` + `failed_sections:
   ["unread_count"]`; nunca oculto. Core (list) falho = erro.
6. **Cache só do unread** — `UnreadCache` (TTL 5s, invalidação em mutação). **Lista NÃO cacheada** (muda
   demais).
7. **Mark read enriquecido** — retorna `changed` + `unread_count` + patch da notificação (read=true) →
   sem 2ª chamada. Atualiza o cache com o count autoritativo.
8. **Mark all read** — retorna `marked` + `unread_count` (0). Atualiza o cache.
9. **List com next_cursor + has_more** — explícitos; o cliente nunca infere.
10. **SSE Future** — documentado em SSE_FUTURE.md (Publisher→Outbox→Dispatcher→SSE→Gateway→Flutter), sem
    implementar.

## Matriz de endpoints (ver COMMUNITIES_API para o padrão)
| Método | Rota | Retorno |
|---|---|---|
| GET | /v1/notifications | ListResponse {items,next_cursor,has_more,unread_count,partial,failed_sections} |
| GET | /v1/notifications/unread-count | UnreadCountResponse {unread_count} (cache 5s) |
| PATCH | /v1/notifications/{id}/read | MarkReadResponse {changed,notification,unread_count} |
| PATCH | /v1/notifications/read-all | MarkAllReadResponse {marked,unread_count} |
Todas requireAuth; viewer = sessão verificada (authmw), nunca do corpo.

## Arquivos (Gateway)
`internal/interfaces/http/notificationbff/`: dto.go, deeplink.go, client.go (SocialGateway + adapter +
proto→DTO + icon/color + caps + payload), aggregator.go (List+UnreadCount partial), cache.go (unread only),
metrics.go (5 Prom), handlers.go (4 endpoints + error map). socialclient.Client += Notification client. Rotas
em main.go (Native, requireAuth). 5 métricas Prometheus no registry compartilhado.

## Riscos residuais
1. **MarkRead patch parcial**: Social.MarkRead retorna changed+count (não a notificação inteira). O Gateway
   devolve um patch {id,read:true,caps} para o cliente mesclar (sem 2ª chamada). Echo da notificação COMPLETA
   exigiria um GetById no Social (deferido; não necessário — o cliente já tem a linha).
2. **Unread cache 5s**: pode servir contagem levemente defasada entre atualizações; mutações invalidam na
   hora. Aceitável; evolução p/ push (SSE) documentada.
3. **Producers ainda não wired** (Stage 1): sem eventos reais criando notificações; a lista virá vazia até o
   wiring — comportamento honesto (empty state), não fabricado.

## Validação
Gateway: `go build ./...` OK · `go vet ./...` OK · `go test ./...` sem falhas (notificationbff **7 casos**:
DTO icon/color/caps, deep-link inválido mantém notificação, has_more+unread embutidos, partial, cache
short-circuit, core-failure=erro, cache TTL+invalidate) · `git diff --check` limpo. Protos/Social diff limpo.
**NENHUM deploy, NENHUMA migration aplicada.**

## Próximo (Stage 3 — Azteca, aguardando aprovação)
Evoluir notifications_screen + badge in-place: consumir os 4 endpoints; **badge/unread do Gateway** (fim da
dedução no cliente); scroll infinito (cursor+has_more) + pull-to-refresh; ícone/cor/ação por item vindos do
DTO; capabilities decidem ações; deep links validados; estados loading/empty/partial/error/offline.
