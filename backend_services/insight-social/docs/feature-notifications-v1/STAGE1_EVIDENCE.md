# FEATURE-NOTIFICATIONS-V1 — Stage 1 (Social) Evidence

## Classificação honesta
| Eixo | Status |
|---|---|
| Proto/Contrato | READY (aditivo; buf breaking PASS) |
| Domínio | READY (imutável; invariantes puras testadas) |
| Persistência | CODE READY / SQL needs-pg (repo dedup/keyset/count sem Postgres) |
| Testes | READY (domínio+serviço: 8 casos verdes) |
| Deploy | NOT_DEPLOYED (migration 00012 NÃO aplicada) |

## Refinamentos do usuário — todos incorporados
1. **Notification imutável** — só `read_at` muta. Aggregate sem mutadores além do estado de leitura;
   type/priority/title/body/target/payload são fixos após `New(...)`. (archived_at/deleted_at fora da V1.)
2. **Payload desacoplado** — coluna `payload JSONB` (+ target_type/target_id/deeplink); sem colunas por tipo →
   novas variantes NÃO exigem migration.
3. **Dedup determinístico** — `DedupKey(...)` content-addressed (ex.: `reaction:discussion:842:user:18`);
   NUNCA timestamp. UNIQUE (user_id, dedup_key) + ON CONFLICT DO NOTHING.
4. **NotificationPublisher** — SEM espalhar `Create(...)`: interface única `Publisher` +
   `DirectPublisher` (V1 escrita direta). Producers dependem da interface → migrar p/ outbox/Kafka/SSE sem
   tocar producers. (Producers NÃO wired no Stage 1 — o seam é o entregável.)
5. **Target + deeplink persistido** — target_type/target_id E `deeplink` gravados na criação (UI navega ao
   estado que existia quando a notificação nasceu; robusto a mudanças futuras de estratégia de deep link).
6. **Unread count indexado** — COUNT sobre índice PARCIAL `ix_notifications_unread` (WHERE read_at IS NULL);
   **documentado como ponto de evolução** (materializar/cachear em alto volume) no código e em PERFORMANCE.
7. **Mark all read filtrado** — `WHERE user_id=? AND read_at IS NULL` (nunca UPDATE sem filtro); retorna
   `marked` (linhas alteradas) + unread refrescado.
8. **Status derivado** — `NotificationStatus` derivado de `read_at` (fonte única); NÃO é coluna → sem drift.
9. **Contador nunca inconsistente** — MarkRead/MarkAllRead retornam o unread-count refrescado no mesmo round.
10. **Sem cascata** — dedup determinístico garante 1 ação → no máx. 1 notificação por destinatário
    (documentado no publisher).

## Arquivos (Social + proto; NENHUM outro domínio tocado)
- proto `social/v1/notification.proto` (NOVO, aditivo): enums Type/Priority/Status, message Notification
  (+ payload_json, deeplink, target), RPCs List/UnreadCount/MarkRead/MarkAllRead. buf breaking PASS.
- migration `00012_notifications.sql` (NOVA, aditiva, NÃO aplicada): tabela notifications (imutável +
  read_at), UNIQUE(user_id,dedup_key), índice keyset (user_id,created_at DESC,id DESC), índice parcial unread.
- domain `internal/domain/notification/`: notification.go (imutável, Status derivado), type.go, dedup.go
  (determinístico), cursor.go (keyset), repository.go (interface), publisher.go (Publisher + DirectPublisher),
  errors.go.
- repo `postgres/notificationrepo/`: Insert (ON CONFLICT dedup → inserted bool), List (keyset limit+1),
  UnreadCount (partial index), MarkRead (WHERE id+user+unread → changed), MarkAllRead (filtrado → count).
- service `application/notification/`: List (clamp), UnreadCount, MarkRead/MarkAllRead (retornam unread
  refrescado).
- gRPC `interfaces/grpc/notification.go`: 4 handlers + translators + error map. Wired em cmd/social/main.go
  (RegisterNotificationServiceServer).

## Invariantes cobertas (8 testes verdes)
New valida (user/type/title/dedup) + defaults (priority→normal, payload→{}); imutabilidade + status derivado
de read_at; dedup determinístico (mesmo evento=mesma chave, partes vazias descartadas, Ref); cursor
round-trip + malformado; **DirectPublisher dedup/no-cascade** (2ª publicação suprimida, 1 linha persiste);
service clamp de limite + forward de filtros; MarkRead/MarkAllRead retornam unread refrescado.

## Riscos residuais
1. **SQL needs-pg**: dedup (ON CONFLICT), keyset, partial-index count, mark filtrado precisam de Postgres para
   prova de execução (padrão do repo). Cobertos por lógica pura + serviço com fakes.
2. **UnreadCount = COUNT**: aceitável na V1; evolução p/ contador materializado/cache documentada.
3. **Producers não wired**: nenhum evento cria notificações ainda (o seam Publisher existe). Wiring
   (community join/discussion reply/mention/reaction) = integração futura, fora do escopo aprovado do Stage 1.
4. **Invitation/Community Accepted**: ausentes por design (BLOCKED_BY_DOMAIN), não fabricados.

## Validação executada
Social: `go build ./...` OK · `go vet ./...` OK · `go test ./...` sem falhas (notification: 8 casos) ·
`git diff --check` limpo. Protos: `buf breaking` PASS · diff limpo (só notification.proto; stubs gitignored).
Gateway: `go build ./...` OK (stubs novos). **NENHUM deploy, NENHUMA migration aplicada.**

## Próximo (Stage 2 — Gateway, aguardando aprovação)
Notification Orchestrator: DTOs próprios; `GET /v1/notifications` (cursor), `GET /v1/notifications/unread-count`,
`PATCH /v1/notifications/{id}/read`, `PATCH /v1/notifications/read-all`; capabilities (can_mark_all_read/
can_open/can_delete=false/can_archive=false...); deep links validados (nunca inválidos ao Flutter); partial
honesto; cache só onde fizer sentido; contador consistente (retornar unread nas mutações).
