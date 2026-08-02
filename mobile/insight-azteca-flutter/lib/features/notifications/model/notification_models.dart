// FEATURE-NOTIFICATIONS-V1 Stage 3 — typed models mirroring the GATEWAY public
// contract (notificationbff DTOs). The client knows ONLY this contract; it
// never infers icon/color (Gateway-owned), read state, capabilities, or
// pagination — all come from the Gateway.
//
// ignore_for_file: sort_constructors_first
import 'package:flutter/foundation.dart';

@immutable
class NotificationCapabilities {
  const NotificationCapabilities({
    required this.canOpen,
    required this.canMarkRead,
    required this.canDelete,
    required this.canArchive,
    required this.canShare,
  });

  final bool canOpen, canMarkRead, canDelete, canArchive, canShare;

  static const none = NotificationCapabilities(
    canOpen: false, canMarkRead: false, canDelete: false, canArchive: false, canShare: false,
  );

  factory NotificationCapabilities.fromJson(Map<String, dynamic>? j) {
    j ??= const {};
    bool b(String k) => j![k] == true;
    return NotificationCapabilities(
      canOpen: b('can_open'),
      canMarkRead: b('can_mark_read'),
      canDelete: b('can_delete'),
      canArchive: b('can_archive'),
      canShare: b('can_share'),
    );
  }
}

/// One notification row. `icon`/`color` are presentation hints OWNED by the
/// Gateway; the client resolves the icon name to an IconData but never decides
/// which icon/color a type gets. `read` and `capabilities` are authoritative.
@immutable
class NotificationItem {
  const NotificationItem({
    required this.id,
    required this.type,
    required this.priority,
    required this.title,
    required this.body,
    required this.icon,
    required this.color,
    required this.deepLink,
    required this.createdAt,
    required this.read,
    required this.capabilities,
  });

  final String id, type, priority, title, body, icon, color, deepLink;
  final DateTime createdAt;
  final bool read;
  final NotificationCapabilities capabilities;

  String get key => id;

  factory NotificationItem.fromJson(Map<String, dynamic> j) => NotificationItem(
        id: '${j['id'] ?? ''}',
        type: j['type'] as String? ?? 'system',
        priority: j['priority'] as String? ?? 'normal',
        title: '${j['title'] ?? ''}',
        body: '${j['body'] ?? ''}',
        icon: j['icon'] as String? ?? 'notifications',
        color: j['color'] as String? ?? '#5BA8FF',
        deepLink: j['deep_link'] as String? ?? '',
        createdAt: DateTime.tryParse('${j['created_at'] ?? ''}')?.toLocal() ?? DateTime.now(),
        read: j['read'] == true,
        capabilities: NotificationCapabilities.fromJson(j['capabilities'] as Map<String, dynamic>?),
      );

  /// Immutable copy with read flipped (used by the encapsulated merge patch).
  NotificationItem markedRead() => NotificationItem(
        id: id, type: type, priority: priority, title: title, body: body, icon: icon,
        color: color, deepLink: deepLink, createdAt: createdAt, read: true,
        capabilities: NotificationCapabilities(
          canOpen: capabilities.canOpen, canMarkRead: false, canDelete: capabilities.canDelete,
          canArchive: capabilities.canArchive, canShare: capabilities.canShare,
        ),
      );
}

/// A page of the Notification Center. next_cursor + has_more come from the
/// Gateway — the client NEVER computes pagination.
@immutable
class NotificationsPage {
  const NotificationsPage({
    required this.items,
    required this.nextCursor,
    required this.hasMore,
    required this.unreadCount,
    required this.partial,
    required this.failedSections,
  });

  final List<NotificationItem> items;
  final String nextCursor;
  final bool hasMore;
  final int unreadCount;
  final bool partial;
  final List<String> failedSections;

  factory NotificationsPage.fromJson(Map<String, dynamic> j) => NotificationsPage(
        items: ((j['items'] as List?) ?? const [])
            .map((e) => NotificationItem.fromJson(e as Map<String, dynamic>))
            .toList(growable: false),
        nextCursor: j['next_cursor'] as String? ?? '',
        hasMore: j['has_more'] == true,
        unreadCount: (j['unread_count'] as num?)?.toInt() ?? 0,
        partial: j['partial'] == true,
        failedSections: ((j['failed_sections'] as List?) ?? const []).map((e) => '$e').toList(growable: false),
      );
}

@immutable
class MarkReadResult {
  const MarkReadResult({required this.changed, required this.unreadCount});
  final bool changed;
  final int unreadCount;

  factory MarkReadResult.fromJson(Map<String, dynamic> j) => MarkReadResult(
        changed: j['changed'] == true,
        unreadCount: (j['unread_count'] as num?)?.toInt() ?? 0,
      );
}

@immutable
class MarkAllReadResult {
  const MarkAllReadResult({required this.marked, required this.unreadCount});
  final int marked, unreadCount;

  factory MarkAllReadResult.fromJson(Map<String, dynamic> j) => MarkAllReadResult(
        marked: (j['marked'] as num?)?.toInt() ?? 0,
        unreadCount: (j['unread_count'] as num?)?.toInt() ?? 0,
      );
}
