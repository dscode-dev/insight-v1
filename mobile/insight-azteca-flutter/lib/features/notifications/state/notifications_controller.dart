// FEATURE-NOTIFICATIONS-V1 Stage 3 — Notification Center controller.
//
// INDEPENDENT states (never a single isLoading): initialLoading, ready, empty,
// refreshing, loadingMore, offline, error, unavailable. Pagination uses ONLY
// the Gateway's next_cursor + has_more — the client never computes it. Read
// mutations are OPTIMISTIC with rollback and go through an ENCAPSULATED merge
// patch (NotificationsState.withReadPatch / withAllRead) so no widget merges by
// hand. The list is NEVER rebuilt wholesale on a mutation — only the changed
// item (and the badge) update.

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/env.dart';
import '../../../core/errors.dart';
import '../data/notifications_api.dart';
import '../model/notification_models.dart';
import 'unread_controller.dart';

enum NotifPhase {
  initialLoading,
  ready,
  empty,
  refreshing,
  loadingMore,
  offline,
  error,
  unavailable,
}

class NotificationsState {
  const NotificationsState({
    required this.phase,
    this.items = const [],
    this.cursor = '',
    this.hasMore = false,
    this.partial = false,
    this.error,
  });

  final NotifPhase phase;
  final List<NotificationItem> items;
  final String cursor;
  final bool hasMore;
  final bool partial;
  final Object? error;

  bool get isBusyTop => phase == NotifPhase.initialLoading || phase == NotifPhase.refreshing;

  NotificationsState copyWith({
    NotifPhase? phase,
    List<NotificationItem>? items,
    String? cursor,
    bool? hasMore,
    bool? partial,
    Object? error,
  }) =>
      NotificationsState(
        phase: phase ?? this.phase,
        items: items ?? this.items,
        cursor: cursor ?? this.cursor,
        hasMore: hasMore ?? this.hasMore,
        partial: partial ?? this.partial,
        error: error,
      );

  // ---- encapsulated merge patches (UI never merges by hand) ----

  /// Returns a new state with ONE item marked read (immutable patch).
  NotificationsState withReadPatch(String id) => copyWith(
        items: [for (final n in items) n.id == id ? n.markedRead() : n],
      );

  /// Returns a new state with all items marked read.
  NotificationsState withAllRead() => copyWith(
        items: [for (final n in items) n.read ? n : n.markedRead()],
      );

  static const initial = NotificationsState(phase: NotifPhase.initialLoading);
}

class NotificationsController extends StateNotifier<NotificationsState> {
  NotificationsController(this._api, this._unread, this._enabled) : super(NotificationsState.initial) {
    load();
  }
  final NotificationsApi _api;
  final UnreadController _unread;
  final bool _enabled;

  NotifPhase _errorPhase(Object e) {
    if (e is NetworkException) return NotifPhase.offline;
    if (e is TimeoutException) return NotifPhase.offline;
    return NotifPhase.error;
  }

  Future<void> load() async {
    if (!_enabled) {
      state = const NotificationsState(phase: NotifPhase.unavailable);
      return;
    }
    state = const NotificationsState(phase: NotifPhase.initialLoading);
    try {
      final page = await _api.list();
      _unread.set(page.unreadCount);
      state = NotificationsState(
        phase: page.items.isEmpty ? NotifPhase.empty : NotifPhase.ready,
        items: page.items,
        cursor: page.nextCursor,
        hasMore: page.hasMore,
        partial: page.partial,
      );
    } catch (e) {
      state = NotificationsState(phase: _errorPhase(e), error: e);
    }
  }

  /// Pull-to-refresh: reload the FIRST page, drop old cursors, refresh unread,
  /// keeping the current items visible until the new page arrives (no flash).
  Future<void> refresh() async {
    if (!_enabled) return;
    state = state.copyWith(phase: NotifPhase.refreshing);
    try {
      final page = await _api.list(); // cursor cleared: first page
      _unread.set(page.unreadCount);
      state = NotificationsState(
        phase: page.items.isEmpty ? NotifPhase.empty : NotifPhase.ready,
        items: page.items,
        cursor: page.nextCursor,
        hasMore: page.hasMore,
        partial: page.partial,
      );
    } catch (e) {
      // Refresh failure keeps the existing list; surface the transient error.
      state = state.copyWith(phase: NotifPhase.ready, error: e);
    }
  }

  /// Infinite scroll — cursor + has_more come from the Gateway only.
  Future<void> loadMore() async {
    if (!state.hasMore || state.cursor.isEmpty || state.phase == NotifPhase.loadingMore) return;
    state = state.copyWith(phase: NotifPhase.loadingMore);
    try {
      final page = await _api.list(cursor: state.cursor);
      final seen = {for (final n in state.items) n.id};
      final merged = [...state.items, ...page.items.where((n) => !seen.contains(n.id))];
      state = state.copyWith(
        phase: NotifPhase.ready, items: merged, cursor: page.nextCursor, hasMore: page.hasMore,
      );
    } catch (_) {
      // Preserve loaded items; allow retry (keep hasMore).
      state = state.copyWith(phase: NotifPhase.ready);
    }
  }

  /// Optimistic single mark-read: patch the item + decrement badge immediately,
  /// then confirm with the server; roll back only on error.
  Future<void> markRead(String id) async {
    final item = _find(id);
    if (item == null || item.read) return;
    final snapshot = state;
    state = state.withReadPatch(id); // encapsulated patch — no manual merge
    _unread.decrement();
    try {
      final res = await _api.markRead(id);
      _unread.set(res.unreadCount); // authoritative
    } catch (_) {
      state = snapshot; // rollback the item
      unawaited(_unread.refresh()); // re-sync the badge from the server
    }
  }

  /// Optimistic mark-all-read.
  Future<void> markAllRead() async {
    if (state.items.every((n) => n.read)) return;
    final snapshot = state;
    state = state.withAllRead();
    _unread.reset();
    try {
      final res = await _api.markAllRead();
      _unread.set(res.unreadCount);
    } catch (_) {
      state = snapshot;
      unawaited(_unread.refresh());
    }
  }

  NotificationItem? _find(String id) {
    for (final n in state.items) {
      if (n.id == id) return n;
    }
    return null;
  }
}

final notificationsControllerProvider =
    StateNotifierProvider<NotificationsController, NotificationsState>((ref) {
  final enabled = InsightEnv.flag(InsightEnv.flagNotificationsV1);
  return NotificationsController(
    ref.watch(notificationsApiProvider),
    ref.watch(unreadControllerProvider.notifier),
    enabled,
  );
});
