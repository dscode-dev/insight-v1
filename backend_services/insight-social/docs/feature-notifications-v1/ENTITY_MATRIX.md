# FEATURE-NOTIFICATIONS-V1 — ENTITY MATRIX

| Entidade / Conceito | Existe? | Onde | Observações |
|---|---|---|---|
| Notification (domínio) | ❌ | — | greenfield; criar no Social |
| notifications (tabela) | ❌ | — | criar migration |
| notification.proto | ❌ | — | criar (aditivo) |
| NotificationType | ⚠️ parcial (só cliente) | AppNotification.NotificationKind | enum cliente ≠ tipos V1; definir canônico no Social |
| NotificationStatus (read/unread) | ⚠️ parcial | AppNotification.read (bool, mock) | tornar real; per-item + all |
| NotificationPriority | ❌ | — | definir no domínio |
| NotificationTarget (deep link) | ❌ | — | Gateway constrói deep_link |
| UnreadCount | ⚠️ derivado no cliente | unreadCountProvider | mover para Gateway (autoridade) |
| ListNotifications (cursor) | ❌ | — | keyset, sem offset/N+1 |
| MarkRead (per-item) | ❌ | — | novo |
| MarkAllRead | ⚠️ órfão | Flutter POST /v1/notifications/mark-all-read | rota inexistente; padronizar PATCH /read-all |
| Dedup | ❌ | — | implementar (chave de idempotência por evento) |
| Deep links | ❌ | — | Gateway-built (padrão SEARCH/COMMUNITIES) |
| Capabilities | ❌ | — | Gateway retorna (ex.: can_mark_read) |
| Badge global | ⚠️ simulado | notifications_action + unreadCountProvider | badge do Gateway (unread-count) |
| SSE/Realtime | ⚠️ fundação | /v1/events/stream + realtime_provider | sem eventos de notificação; V1 = refresh controlado |
| Tela Notifications | ✅ (mock) | features/notifications/notifications_screen.dart | UX aprovada; evoluir, não substituir |
| Fixtures mock | ✅ | mock/fixtures/notifications_fixtures.dart | remover uso real (não fabricar) |

## Tipos de evento V1 (a definir no Social — fonte de verdade)
Pedidos: **Community Join, Discussion Reply, Mention, Reaction, Invitation (se existir), System**.
- Community Join, Discussion Reply, Mention, Reaction, System → derivam de domínios REAIS (community_members,
  discussions, comments/reactions) → viáveis.
- **Invitation** → NÃO existe domínio de convites (Communities V1 é join aberto, sem invitation) →
  **DOCUMENTAR como ausente** (BLOCKED_BY_DOMAIN); não fabricar.
- Community Accepted → depende de fluxo de aprovação inexistente → ausente na V1.

## Legenda de decisão
- **BUILD (real)**: domínio Notification, migration, proto aditivo, orchestrator Gateway, unread-count real,
  per-item read, cursor, dedup, deep links, capabilities, badge do Gateway.
- **REUSE/EVOLVE**: notifications_screen, notifications_action badge, AppNotification (reconciliar), SSE
  foundation (futuro), feature_gate (ligar).
- **DOCUMENT-AS-ABSENT (nunca fabricar)**: Invitation, Community Accepted, realtime push de notificação.
