# FEATURE-NOTIFICATIONS-V1 — CONTRACT MATRIX

Boundary: Flutter → **Gateway (contrato público, DTOs próprios)** → Social gRPC. Atlas fora. Nada de proto vaza.

## Rotas Gateway HOJE
| Método | Rota | Situação |
|---|---|---|
| GET | /v1/events/stream | SSE foundation (sem eventos de negócio) — permanece |
| /v1/notifications* | — | **INEXISTENTE** (o cliente referencia, mas nunca foi servido → gated) |

## Rotas Gateway A CRIAR (Stage 2)
| Método | Rota | Social RPC | Notas |
|---|---|---|---|
| GET | /v1/notifications | ListNotifications | keyset cursor; DTO público; deep_link + capabilities |
| GET | /v1/notifications/unread-count | UnreadCount | badge global (autoridade) |
| PATCH | /v1/notifications/{id}/read | MarkRead | idempotente |
| PATCH | /v1/notifications/read-all | MarkAllRead | idempotente; retorna novo unread-count |

## Contratos órfãos a reconciliar (não são contratos públicos vivos)
- Flutter `GET /v1/notifications` (list): existe no cliente, nunca no Gateway → ao servir de verdade, o shape
  passa a ser o DTO público novo (envelope com items + next_cursor + unread_count).
- Flutter `POST /v1/notifications/mark-all-read`: órfão → substituído por `PATCH /read-all`. Como nunca foi
  servido, NÃO é quebra de contrato público vivo (documentar mesmo assim).

## DTO público (Gateway-owned) — a definir no Stage 2
`NotificationDTO { id, type, priority, title, body, created_at, read, deep_link, actor?, target? }` +
envelope `{ items[], next_cursor, unread_count, capabilities }`. `type` = string canônica (community_join,
discussion_reply, mention, reaction, system). Deep link por tipo (Gateway constrói; cliente valida).

## Reconciliação de tipos (cliente evolui de forma tolerante)
Enum cliente atual (matchEvent/signalReply/communityMention/agentInsight/systemUpdate) → mapear para o
canônico do Social. Tipos desconhecidos no cliente → fallback "system"/genérico (nunca quebrar parse).

## Invariantes a preservar
- Identidade sempre server-derived (X-User-Id).
- unread/badge SEMPRE do Gateway (nunca derivado no cliente).
- Contador nunca inconsistente: mark-read/read-all retornam o unread-count atualizado.
- Evolução aditiva; nenhum contrato público vivo removido (o /notifications atual nunca existiu no Gateway).
- Deep links só do Gateway; cliente valida contra rotas reais (padrão SEARCH/COMMUNITIES).
