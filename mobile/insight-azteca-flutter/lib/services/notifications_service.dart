import 'package:dio/dio.dart';

import '../mock/fixtures/notifications_fixtures.dart';
import '../models/notifications.dart';
import 'gateway_client.dart';

abstract class NotificationsService {
  Future<List<AppNotification>> list();
  Future<void> markAllRead();
}

/// Gateway-backed Notifications service.
///
/// Endpoints:
///   * `GET  /v1/notifications`               → list of AppNotification
///   * `POST /v1/notifications/mark-all-read` → 204
///
/// Stubbed on Gateway until the per-user notification fanout (Plaza
/// outbox + Gateway aggregator) is wired in.
class GatewayNotificationsService implements NotificationsService {
  GatewayNotificationsService(this._dio);
  final Dio _dio;

  @override
  Future<List<AppNotification>> list() async {
    final body = await _dio.getJson('/v1/notifications');
    return (body['items'] as List? ?? const [])
        .cast<Map<String, dynamic>>()
        .map(AppNotification.fromJson)
        .toList(growable: false);
  }

  @override
  Future<void> markAllRead() async {
    await _dio.postJson('/v1/notifications/mark-all-read');
  }
}

/// In-memory mock. Holds a single list across calls so "mark all read"
/// has a visible effect across navigations within the same session.
class MockNotificationsService implements NotificationsService {
  MockNotificationsService();
  List<AppNotification>? _cached;

  @override
  Future<List<AppNotification>> list() async {
    await Future<void>.delayed(const Duration(milliseconds: 180));
    _cached ??= kNotifications();
    return List.unmodifiable(_cached!);
  }

  @override
  Future<void> markAllRead() async {
    await Future<void>.delayed(const Duration(milliseconds: 80));
    final current = _cached ?? kNotifications();
    _cached = current.map((n) => n.copyWith(read: true)).toList();
  }
}
