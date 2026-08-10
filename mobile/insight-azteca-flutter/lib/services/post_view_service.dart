import 'dart:async';

import 'package:dio/dio.dart';

import 'gateway_client.dart';

/// Records that posts were seen, so "em alta" can be measured.
///
/// The platform's definition of trending is "quantidade de acesso ao post,
/// curtidas, interações por segundos, comentários". The last three are already
/// recorded as a side effect of the actions themselves. The first is not: a
/// post being SEEN produces no request, so unless the client says so, the
/// leading signal of the ranking is permanently zero and Explorar ranks on
/// three quarters of its definition.
///
/// BATCHED, NEVER PER POST. A view happens every time a post scrolls into
/// view; one request each would make scrolling the heaviest thing the app
/// does. Impressions accumulate here and leave in one call.
///
/// BEST EFFORT, ALWAYS. A view is a metric, not something the user is waiting
/// on. Every failure path here drops the batch silently: losing a few
/// impressions is invisible, and an error surfaced over the feed is not.
class PostViewService {
  PostViewService(this._dio, {Duration? flushInterval})
      : _flushInterval = flushInterval ?? const Duration(seconds: 20);

  final Dio _dio;
  final Duration _flushInterval;

  /// post_id -> how many times it entered the viewport since the last flush.
  final Map<String, int> _pending = <String, int>{};
  Timer? _timer;
  bool _sending = false;

  /// Social's per-call cap. Flushing early keeps a long scroll from building a
  /// batch the server would reject wholesale.
  static const _maxBatch = 200;

  /// Called when a post becomes visible. Cheap by design — it must be safe on
  /// the build path of a list item.
  void seen(String postId) {
    if (postId.isEmpty) return;
    _pending.update(postId, (n) => n + 1, ifAbsent: () => 1);
    if (_pending.length >= _maxBatch) {
      unawaited(flush());
      return;
    }
    _timer ??= Timer(_flushInterval, () => unawaited(flush()));
  }

  /// Sends what has accumulated. Safe to call at any time; the app should call
  /// it when the feed is left or the app is backgrounded, so a session's last
  /// impressions are not lost with the process.
  Future<void> flush() async {
    _timer?.cancel();
    _timer = null;
    if (_pending.isEmpty || _sending) return;

    // Drained before the await so impressions arriving during the request are
    // counted for the next batch instead of being lost when this map is
    // cleared, or double-sent if it were cleared afterwards.
    final batch = Map<String, int>.from(_pending);
    _pending.clear();
    _sending = true;

    try {
      await _dio.postJson('/v1/explore/views', body: {
        'items': batch.entries
            .map((e) => {
                  'post_id': e.key,
                  'views': e.value,
                  // One device, one person: however many times a post was
                  // scrolled past, it was seen by one viewer. Sending the
                  // impression count here instead would make a single user
                  // scrolling back and forth look like a crowd.
                  'viewers': 1,
                })
            .toList(growable: false),
      });
    } catch (_) {
      // Deliberately swallowed, and deliberately NOT retried: a failed batch
      // is a handful of impressions. Re-queuing them would grow unboundedly
      // while the network is down and then flood the server when it returns.
    } finally {
      _sending = false;
    }
  }

  void dispose() {
    _timer?.cancel();
    _timer = null;
  }
}
