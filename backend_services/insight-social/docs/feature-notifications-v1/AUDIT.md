# FEATURE-NOTIFICATIONS-V1 — Stage 0 AUDIT (read-only, no code)

Método oficial (SEARCH-V1 / COMMUNITIES-V1): AUDIT → UX PRESERVATION → SOCIAL → GATEWAY → AZTECA →
CERTIFICATION. Parar ao fim de cada Stage para aprovação.

## Perguntas obrigatórias — respostas

**Como notificações existem hoje?**
Só no cliente, como MOCK gated-off. Não há backend algum.
- **Social**: ABSENTE — sem domínio, proto, repo, service, gRPC, migration ou tabela `notifications`.
- **Gateway**: NENHUMA rota `/v1/notifications*`. Existe apenas a FUNDAÇÃO SSE `/v1/events/stream`
  (`internal/interfaces/http/events/stream.go`) — canal autenticado + heartbeat, deliberadamente SEM eventos
  de negócio ainda; projetado para futuramente carregar feed/notifications/signals.
- **Azteca**: feature completa porém MOCK, **desligada em produção** via `feature_gate` (`flagNotificationsV1`):
  tela `features/notifications/notifications_screen.dart`, badge `widgets/notifications_action.dart`, model
  `models/notifications.dart`, provider `providers/notifications_provider.dart`, service
  `services/notifications_service.dart`, fixtures `mock/fixtures/notifications_fixtures.dart`.

**Existem mocks?** SIM — `kNotifications()` (fixtures fabricados) + `MockNotificationsService`.

**Existem endpoints?** No Gateway, NÃO. O cliente REFERENCIA `GET /v1/notifications` e
`POST /v1/notifications/mark-all-read`, mas essas rotas **não existem** no Gateway → seriam 404 → por isso o
provider é gated (evita 404 em prod). São contratos ÓRFÃOS (nunca servidos).

**Existem protos?** NÃO. Nenhum `notification.proto`.

**Existem modelos duplicados?** Um só: `AppNotification` (freezed) + enum `NotificationKind`. Sem duplicação,
mas o enum atual (matchEvent/signalReply/communityMention/agentInsight/systemUpdate) **não corresponde** aos
tipos pedidos na V1 (Community Join, Discussion Reply, Mention, Reaction, Invitation, System) → reconciliar.

**Existem contratos quebrados?** Sim, no sentido de órfãos: o service Flutter aponta para rotas inexistentes.
Como estão gated (nunca chamadas em prod), não há 404 real hoje — mas o contrato é fictício até o backend
existir. Também: `mark-all-read` como POST diverge do padrão PATCH pedido na V1.

**Existe dívida técnica?** Sim: notificações fabricadas; unread derivado no cliente; badge simulado; enum
desalinhado; sem paginação; sem deep links; sem capabilities; sem per-item read; sem unread-count real.

**Existem notificações fabricadas?** SIM — `mock/fixtures/notifications_fixtures.dart`.

**Existem badges simulados?** SIM — `unreadCountProvider` **deriva no cliente**:
`list.where((n)=>!n.read).length` (viola a decisão #3: unread/badge devem vir do Gateway).

**Existe polling?** Não agressivo. `notificationsProvider` é FutureProvider com cache (não autoDispose) para o
badge não piscar entre navegações. Refresh manual (invalidate) em "Marcar lidas".

**Existe realtime?** Fundação SIM (SSE `/v1/events/stream` + `realtime_provider`/`realtime_event`), mas **sem
eventos de notificação** ainda. V1 pode operar com refresh controlado, mantendo a arquitetura pronta para
plugar o SSE depois (sem trocar a conexão do cliente).

**Quais componentes poderão ser reaproveitados?**
- `notifications_screen.dart` (UX aprovada: AppBar "Notificações" + "Marcar lidas" + lista de `_NotificationRow`
  com ícone por tipo + título + corpo + tempo relativo + estado read; empty/error/feature-unavailable).
- `notifications_action.dart` (badge de sino, cap "9+", cor confidenceLow).
- `AppNotification` (evoluir: adicionar read/unread do servidor, deep_link, priority; reconciliar kind).
- `feature_gate` (`flagNotificationsV1`) — ligar quando o backend for real.
- Fundação SSE/realtime (integração futura).

## Conclusão do Stage 0
NOTIFICATIONS-V1 é **greenfield no backend** (Social + Gateway) com uma **UI aprovada mock-only** a ser
promovida a real. O trabalho: criar o domínio Notification no Social (autoridade), o Notification Orchestrator
no Gateway (DTOs próprios + unread-count + per-item read + capabilities + deep links), e evoluir a tela/badge
do Azteca para consumir o contrato real — sem redesign, com unread/badge vindos do Gateway (fim da dedução no
cliente), sem fabricar dados.
