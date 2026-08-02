// FEATURE-NOTIFICATIONS-V1 Stage 3 — the unread badge source.
//
// The badge depends EXCLUSIVELY on this controller — NEVER on the list. It
// works even when the Notification Center has never been opened (it fetches its
// own count from the Gateway). The notifications controller pushes the
// authoritative count here after every mutation, so the badge stays consistent
// without reading the list.
//
// Gated: while the feature flag is off, the count is a constant 0 and NO
// network call is made (no 404 in production).

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/env.dart';
import '../data/notifications_api.dart';

class UnreadController extends StateNotifier<int> {
  UnreadController(this._api, this._enabled) : super(0) {
    if (_enabled) {
      refresh();
    }
  }
  final NotificationsApi _api;
  final bool _enabled;

  /// Fetch the authoritative unread count from the Gateway. Silent on failure —
  /// the badge simply keeps its last known value (never crashes the AppBar).
  Future<void> refresh() async {
    if (!_enabled) return;
    try {
      state = await _api.unreadCount();
    } catch (_) {
      // keep last value
    }
  }

  /// Set the authoritative count (called by the notifications controller after
  /// a mark-read / mark-all-read, using the Gateway's returned unread_count).
  void set(int value) => state = value < 0 ? 0 : value;

  /// Optimistic local decrement (before the server confirms a single read).
  void decrement() => state = state > 0 ? state - 1 : 0;

  /// Optimistic local reset (before the server confirms mark-all).
  void reset() => state = 0;
}

final unreadControllerProvider = StateNotifierProvider<UnreadController, int>((ref) {
  final enabled = InsightEnv.flag(InsightEnv.flagNotificationsV1);
  return UnreadController(ref.watch(notificationsApiProvider), enabled);
});
