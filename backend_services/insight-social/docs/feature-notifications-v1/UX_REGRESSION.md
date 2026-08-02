# FEATURE-NOTIFICATIONS-V1 — UX Regression Checklist

Mesmo rigor de Search/Communities. Confirmação explícita de não-regressão.

| Item | Status | Evidência |
|---|---|---|
| **Notification Center — identidade** | ✅ PRESERVADA | mesma rota /notifications; `_NotificationRow` aprovada (icon-square+título+tempo+corpo+tint) mantida; só a fonte de dados mudou |
| Nenhuma tela substituída | ✅ | tela evoluída no mesmo arquivo; badge no mesmo lugar do AppBar da Home |
| Badge — visual | ✅ PRESERVADO | `notifications_action.dart` só trocou o provider observado; layout/cor/"9+" idênticos; `const NotificationsAction()` intacto |
| **Search** | ✅ INALTERADA | nenhum arquivo de features/search tocado |
| **Communities** | ✅ INALTERADA | nenhum arquivo de features/hub/community tocado |
| **Feed Global** | ✅ INALTERADO | features/home intocado (exceto import já existente do badge) |
| **Profile** | ✅ INALTERADO | — |
| **Atlas** | ✅ INALTERADO (congelado) | — |
| **Navegação** | ✅ INALTERADA | routing/router.dart não modificado |

## Superfície de mudança (Flutter)
- MODIFICADO: `features/notifications/notifications_screen.dart` (evoluído, mesma rota),
  `widgets/notifications_action.dart` (só o provider do badge).
- NOVO (isolado): `features/notifications/{model,data,navigation,state,widgets}/**`.
- INALTERADO: search, communities, feed/home, profile, radar, live, routing. Backend intocado.
- ÓRFÃOS (sem uso, analyze limpo): models/notifications.dart, providers/notifications_provider.dart,
  services/notifications_service.dart, mock/fixtures/notifications_fixtures.dart.

## Validação automatizada
`flutter analyze` limpo · `flutter test` **140 passed** (130 pré + 10 novos; nenhum regrediu) ·
`git diff --check` limpo. Sem golden infra → checklist visual manual no SMOKE.

## Conclusão
Nenhuma regressão de UX. A regra (integração, nunca substituição) foi aplicada e verificada.
