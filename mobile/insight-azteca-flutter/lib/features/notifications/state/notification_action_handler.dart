// FEATURE-NOTIFICATIONS-V1 Stage 3 — the SINGLE instrumentation point for
// notification interactions.
//
// Every open/dismiss flows through here, so future analytics (open, CTR,
// dismiss, time-to-read) can be added at ONE place without touching the UI.
// Today the analytics hook is a no-op; the handler already owns the correct
// behaviour: it marks read (optimistically, via the controller) and navigates
// ONLY when the Gateway granted can_open AND the deep link is a real route.

import '../model/notification_models.dart';
import '../navigation/notification_deep_link.dart';

/// Analytics sink — a no-op today. Swap for a real implementation later; the UI
/// never changes.
typedef NotificationAnalytics = void Function(String event, NotificationItem item);

void _noopAnalytics(String event, NotificationItem item) {}

class NotificationActionHandler {
  const NotificationActionHandler({
    required this.onNavigate,
    required this.onMarkRead,
    this.analytics = _noopAnalytics,
  });

  final void Function(String deepLink) onNavigate;
  final void Function(String id) onMarkRead;
  final NotificationAnalytics analytics;

  /// Handle a tap on a notification. Marks read (optimistic) and opens the
  /// destination only when permitted. Never attempts to open a can_open==false
  /// item, even by accident.
  void handleOpen(NotificationItem item) {
    analytics('notification_open', item);
    if (item.capabilities.canMarkRead) {
      onMarkRead(item.id);
    }
    if (item.capabilities.canOpen && notificationDeepLinkIsNavigable(item.deepLink)) {
      onNavigate(item.deepLink);
    }
  }

  /// True when the row should be tappable at all (an open action exists).
  bool canOpen(NotificationItem item) =>
      item.capabilities.canOpen && notificationDeepLinkIsNavigable(item.deepLink);
}
