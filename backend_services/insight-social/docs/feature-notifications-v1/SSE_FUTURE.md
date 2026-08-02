# FEATURE-NOTIFICATIONS-V1 — Realtime (SSE) Future (design-only, NOT implemented)

Registro de como a arquitetura atual liga-se ao SSE existente quando chegar a sprint de Realtime. Nada aqui é
implementado na V1 — o objetivo é evitar re-discussão.

## Pipeline alvo
```
Domain event (community join / reply / mention / reaction)
        │
        ▼
NotificationPublisher            ← JÁ EXISTE (Stage 1: interface + DirectPublisher)
        │  (troca a impl, producers não mudam)
        ▼
Outbox (notifications_outbox)    ← FUTURO: escreve na mesma transação do evento (entrega garantida)
        │
        ▼
Dispatcher (worker)              ← FUTURO: lê o outbox, publica no stream (idempotente por dedup_key)
        │
        ▼
SSE stream /v1/events/stream     ← JÁ EXISTE (fundação: canal autenticado + heartbeat, sem eventos ainda)
        │  event: notification  { id, type, unread_count, ... }
        ▼
Gateway (notificationbff)        ← JÁ EXISTE: contrato público + DTO + unread cache
        │  (invalida/atualiza o unread cache ao receber o push)
        ▼
Flutter                          ← consome o mesmo contrato; badge/lista atualizam sem polling
```

## Por que a base atual já suporta isso sem retrabalho
- **Publisher como seam**: producers dependem de `notification.Publisher`, não do repo. Trocar
  `DirectPublisher` por um `OutboxPublisher` (escrita transacional no outbox) não toca nenhum producer.
- **dedup_key determinística**: o Dispatcher pode reprocessar o outbox com segurança (entrega ≥1) — o
  `ON CONFLICT DO NOTHING` garante idempotência (1 evento = 1 notificação).
- **read_at única fonte de verdade + status derivado**: o push de realtime só precisa carregar o id/tipo e o
  novo unread_count; o estado read continua consistente.
- **Gateway já dono do unread cache**: ao receber um push, o Gateway invalida/atualiza o cache do usuário — o
  badge fica consistente sem o cliente inferir nada.
- **SSE stream já autenticado**: `/v1/events/stream` foi desenhado para carregar `event: notification` sem
  mudar a conexão do cliente.

## O que a V1 entrega (refresh controlado)
- `GET /v1/notifications` (embute unread_count) no abrir do Center + pull-to-refresh.
- `GET /v1/notifications/unread-count` (cache poucos segundos) para o badge.
- Mutações retornam unread_count (badge consistente sem 2ª chamada).
Nenhum polling agressivo; a migração para push é aditiva.

## Passos futuros (fora do escopo)
1. Migration `notifications_outbox` (aditiva).
2. `OutboxPublisher` implementando `notification.Publisher` (escrita transacional).
3. Worker Dispatcher (outbox → SSE), idempotente por dedup_key.
4. Emitir `event: notification` no stream; Gateway atualiza o unread cache; Flutter escuta.
