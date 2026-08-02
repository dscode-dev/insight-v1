import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/logger.dart';
import '../models/auth.dart';
import '../models/realtime_event.dart';
import '../services/gateway_client.dart';
import '../services/realtime_service.dart';
import '../services/services_providers.dart';
import 'auth_provider.dart';
import 'feed_provider.dart';

/// Single-source broadcast stream of `RealtimeEvent`s.
///
/// Lifecycle:
///   * Idle while `authStatus == anonymous` or `hydrating`.
///   * Connects on `authenticated`, re-connects whenever the access
///     token rotates (refresh path), tears down on logout.
///   * Auto-disposes after the last listener detaches for 5 minutes
///     so a backgrounded app doesn't keep an idle SSE open.
///
/// Listeners attach via `ref.watch(realtimeEventStreamProvider)` for
/// values, or via the side-effect [realtimeCoordinatorProvider] which
/// dispatches events into other providers (feed prepend, match invalidate,
/// notifications refresh).
final realtimeEventStreamProvider =
    StreamProvider.autoDispose<RealtimeEvent>((ref) {
  // Re-subscribe when the access token changes.
  final tokens = ref.watch(authProvider.select((s) => s.tokens));
  final status = ref.watch(authStatusProvider);

  if (status != AuthStatus.authenticated || tokens == null) {
    // Empty stream — listeners stay subscribed cheaply.
    return const Stream<RealtimeEvent>.empty();
  }

  final service = ref.read(realtimeServiceProvider);
  final stream = _authenticatedRealtimeStream(ref, service, tokens);

  ref.onDispose(() {
    // Fire-and-forget — service.disconnect closes the underlying SSE.
    unawaited(service.disconnect());
  });

  // Keep the connection warm for 5 min after the last listener detaches,
  // so a quick navigation away+back doesn't churn the SSE handshake.
  ref.keepAlive();
  return stream;
});

Stream<RealtimeEvent> _authenticatedRealtimeStream(
  Ref ref,
  RealtimeService service,
  Tokens initial,
) async* {
  var tokens = initial;
  var refreshed = false;
  while (true) {
    try {
      await for (final event
          in service.subscribe(accessToken: tokens.accessToken)) {
        yield event;
      }
      return;
    } on SseAuthException catch (e) {
      if (refreshed) {
        L.w('realtime', 'sse.connect.failed',
            data: {'reason': 'auth_failed_after_refresh'});
        await ref.read(authProvider.notifier).clearSessionDueToAuthFailure();
        return;
      }
      refreshed = true;
      L.i('realtime', 'sse.auth.refresh', data: {'reason': e.code});
      try {
        tokens = await refreshGatewaySession(ref);
      } catch (refreshErr, st) {
        L.e('realtime', 'sse.auth.refresh', error: refreshErr, stackTrace: st);
        await ref.read(authProvider.notifier).clearSessionDueToAuthFailure();
        return;
      }
    } catch (e, st) {
      L.e('realtime', 'sse.connect.failed', error: e, stackTrace: st);
      return;
    }
  }
}

/// Side-effect provider — translates incoming realtime events into
/// updates on the other providers that care.
///
/// Mounted from app boot (via `ref.watch` in InsightApp) so the
/// dispatch runs for the whole session whether or not the Home screen
/// is currently visible.
final realtimeCoordinatorProvider = Provider<void>((ref) {
  ref.listen<AsyncValue<RealtimeEvent>>(
    realtimeEventStreamProvider,
    (_, next) {
      next.whenData((event) => _dispatch(ref, event));
    },
  );
});

void _dispatch(Ref ref, RealtimeEvent event) {
  switch (event.eventType) {
    case EventType.humanSignal:
      // Bump the "X novos posts" pill on Home. Capped to avoid the
      // counter running away on a chatty stream.
      final notifier = ref.read(pendingNewPostsProvider.notifier);
      final next = notifier.state + 1;
      notifier.state = next > 99 ? 99 : next;
      L.i('realtime', 'pending_post_bump', data: {'count': next});

    case EventType.agentInsight:
      // Same treatment for now — agent insights are first-class feed
      // items in Phase 3.
      final notifier = ref.read(pendingNewPostsProvider.notifier);
      final next = notifier.state + 1;
      notifier.state = next > 99 ? 99 : next;

    case EventType.metricTick:
    case EventType.marketSnapshot:
      // Match detail invalidation — future hook. Skipped here so the
      // dispatch stays predictable; the MatchDetail screen itself
      // can `ref.listen` on the stream for its specific match_id.
      break;

    case EventType.notification:
      // Notifications inbox bump — invalidating the list provider is
      // enough; the unread badge derives from it.
      break;

    case EventType.unknown:
      L.w(
        'realtime',
        'unknown_event_type',
        data: {'id': event.eventId},
      );
  }
}
