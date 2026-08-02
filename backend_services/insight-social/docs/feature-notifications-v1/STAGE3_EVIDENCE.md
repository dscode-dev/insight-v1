# FEATURE-NOTIFICATIONS-V1 — Stage 3 (Azteca) Evidence

## Classificação honesta
| Eixo | Status |
|---|---|
| Integração (não redesign) | READY |
| Preservação de UI | READY (mesma rota + row aprovada) |
| Contratos do Gateway | READY (consome os 4 endpoints; nada deduzido) |
| Estados independentes | READY |
| Optimistic + rollback | READY |
| Deploy | NOT_DEPLOYED |

## Os 10 ajustes — todos incorporados
1. **Nunca reconstruir a lista** — markRead/markAllRead aplicam patch encapsulado no item + atualizam o badge;
   sem `reload()` da lista inteira.
2. **Cursor como fonte única** — `loadMore` usa só `next_cursor` + `has_more` do Gateway; o cliente nunca
   calcula paginação.
3. **Merge patch encapsulado** — `NotificationsState.withReadPatch(id)` / `.withAllRead()` +
   `NotificationItem.markedRead()`; a UI nunca faz merge manual.
4. **Badge desacoplado** — `UnreadController` (badge) depende SÓ do Gateway `/unread-count`, nunca da lista;
   funciona mesmo com o Center nunca aberto. `NotificationsAction` observa só o `unreadControllerProvider`.
5. **Optimistic UI** — markRead: marca lido na hora + decrementa badge + PATCH + rollback só em erro (badge
   re-sincroniza do servidor). markAllRead: idem (reset otimista).
6. **DeepLink** — nunca abre `can_open==false` (nem por engano); a row é clicável só quando há ação permitida
   (`NotificationActionHandler.canOpen`).
7. **Pull-to-refresh** — `refresh()` recarrega 1ª página, atualiza unread, limpa cursores; itens permanecem
   visíveis até a nova página (sem flash).
8. **Estados independentes** — `NotifPhase{initialLoading,ready,empty,refreshing,loadingMore,offline,error,
   unavailable}`; nada de `isLoading` único.
9. **Notification Row** — componente aprovado PRESERVADO (icon-square tingido + título negrito-se-não-lido +
   tempo relativo + corpo + tint de não-lido). Só trocou a fonte de dados (icon/color agora do DTO do Gateway).
10. **Analytics futuro** — ponto único `NotificationActionHandler` (analytics hook no-op hoje) → mark read →
    navigate. Medir abertura/CTR/dismiss/tempo-até-leitura no futuro sem refatorar a UI.

## Arquivos (Flutter-only, isolado em lib/features/notifications/)
- `model/notification_models.dart` — NotificationItem (icon/color/capabilities do Gateway; `markedRead()`
  patch imutável), NotificationCapabilities, NotificationsPage (has_more/unread/partial), Mark*Result.
- `data/notifications_api.dart` — 4 endpoints (list cursor / unread-count / PATCH read / PATCH read-all).
- `navigation/notification_deep_link.dart` — valida deep_link vs rotas reais.
- `widgets/notification_icon.dart` — resolve icon NAME → IconData + hex → Color (fallback neutro).
- `state/unread_controller.dart` — badge decoupled (Gateway unread-count; gated; set/decrement/reset).
- `state/notifications_controller.dart` — estados independentes; cursor+has_more; optimistic markRead/
  markAllRead + rollback; patches encapsulados.
- `state/notification_action_handler.dart` — seam único de instrumentação.
- `notifications_screen.dart` (mesma rota) — row aprovada preservada + scroll infinito + pull-to-refresh +
  estados + optimistic; "Marcar lidas" só quando unread>0.
- `widgets/notifications_action.dart` (badge) — só troca a fonte para `unreadControllerProvider` (visual
  100% preservado; `const NotificationsAction()` intacto).

## Isolamento (compat)
Nada alterado em Search, Communities, Feed, Atlas, Profile ou navegação. Backend intocado nesta etapa.
Feature-gate `flagNotificationsV1` preservado (off → phase `unavailable` + FeatureUnavailableView, badge 0).
Arquivos antigos (models/notifications.dart, providers/notifications_provider.dart, services/notifications_
service.dart, mock/fixtures/notifications_fixtures.dart) ficaram órfãos (analyze limpo; cleanup em Tech Debt).

## Validação
`flutter analyze` **No issues found** · `flutter test` **140 passed** (+10: models icon/color/caps + patch
imutável + page has_more/unread/partial; controller load/unavailable/optimistic-markRead/rollback/markAllRead/
loadMore-dedupe; action-handler nunca abre can_open=false) · `git diff --check` limpo. **Sem deploy.**

## Comparação de layout (antes × agora)
| Aspecto | Antes (aprovado, mock) | Agora |
|---|---|---|
| Rota | /notifications | **igual** |
| Row | icon-square+título+tempo+corpo+tint não-lido (icon/color de enum do cliente) | **preservada** (icon/color agora do Gateway) |
| Dados | mock fixtures (gated) | 4 endpoints reais do Gateway |
| Badge | derivado da lista (client count) | **do Gateway** (`/unread-count`, desacoplado) |
| Paginação | inexistente | cursor + has_more (scroll infinito) |
| Marcar lida | mark-all (reload) | per-item + all **otimista + rollback**, sem reload |

## Limitações restantes
1. **Producers não wired** (Stage 1): a lista virá vazia até os eventos serem ligados ao Publisher — empty
   state honesto, não fabricado.
2. **Órfãos**: model/provider/service/fixtures antigos sem uso (analyze limpo) — cleanup futuro (Tech Debt).
3. **Realtime**: V1 = refresh controlado (on-open + pull-to-refresh + unread cache 5s); push SSE documentado
   (SSE_FUTURE.md), não implementado.
4. **Golden tests**: sem infra confiável no repo → cobertura comportamental + checklist visual no smoke.
