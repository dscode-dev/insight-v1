import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/env.dart';
import '../core/feature_gate.dart';
import '../models/notifications.dart';
import '../services/services_providers.dart';

/// Cached notifications list. Not autoDispose — we want the cache to
/// survive tab switches and short navigations so the unread badge in
/// the Home AppBar doesn't flicker.
final notificationsProvider = FutureProvider<List<AppNotification>>((ref) {
  // Orphan route (/v1/notifications) — gated off until served. The
  // bell badge reads valueOrNull and shows 0 while disabled.
  if (!InsightEnv.flag(InsightEnv.flagNotificationsV1)) {
    throw const FeatureUnavailable('notifications');
  }
  return ref.watch(notificationsServiceProvider).list();
});

/// Convenience: number of unread items. Used by the bell badge.
final unreadCountProvider = Provider<int>((ref) {
  final list = ref.watch(notificationsProvider).valueOrNull ?? const [];
  return list.where((n) => !n.read).length;
});
