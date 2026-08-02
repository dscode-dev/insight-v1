import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import '../core/env.dart';
import '../core/logger.dart';
import '../models/realtime_event.dart';

final class SseAuthException implements Exception {
  const SseAuthException(this.code);
  final String code;

  @override
  String toString() => 'SseAuthException($code)';
}

/// Realtime stream contract — yields `RealtimeEvent`s for as long as the
/// caller keeps listening. Calling `disconnect()` tears down the active
/// connection (the next `subscribe` rebuilds it).
abstract class RealtimeService {
  /// Returns a single broadcast stream the caller can listen to multiple
  /// times. Internally, the implementation may multiplex a single
  /// underlying SSE connection.
  Stream<RealtimeEvent> subscribe({
    required String accessToken,
    List<String> matchIds = const [],
    List<String> eventTypes = const [],
  });

  Future<void> disconnect();
}

/// Gateway SSE-backed implementation.
///
/// Connects to `GET /v1/realtime/sse?access_token=...` so the JWT
/// travels in the URL. This uses `dart:io` instead of the EventSource
/// plugin because the plugin retries internally with stale credentials
/// and prints transport errors before the auth layer can refresh.
class GatewayRealtimeService implements RealtimeService {
  GatewayRealtimeService({String? baseUrl})
      : _baseUrl = baseUrl ?? InsightEnv.apiBaseUrl;

  final String _baseUrl;
  StreamController<RealtimeEvent>? _controller;
  StreamSubscription<String>? _lineSub;
  HttpClient? _client;
  int _generation = 0;

  @override
  Stream<RealtimeEvent> subscribe({
    required String accessToken,
    List<String> matchIds = const [],
    List<String> eventTypes = const [],
  }) {
    _generation += 1;
    final generation = _generation;

    // Reset any previous connection — subscribers of the OLD controller
    // get a `done` event, the new controller starts fresh.
    _stopTransport();
    unawaited(_controller?.close());

    final controller = StreamController<RealtimeEvent>.broadcast();
    _controller = controller;

    final qp = <String, String>{
      'access_token': accessToken,
      if (matchIds.isNotEmpty) 'match_ids': matchIds.join(','),
      if (eventTypes.isNotEmpty) 'event_types': eventTypes.join(','),
    };
    final uri =
        Uri.parse('$_baseUrl/v1/realtime/sse').replace(queryParameters: qp);

    L.i('realtime', 'sse.connect.started');
    unawaited(_connect(generation, controller, uri));

    return controller.stream;
  }

  Future<void> _connect(
    int generation,
    StreamController<RealtimeEvent> controller,
    Uri uri,
  ) async {
    final client = HttpClient();
    _client = client;
    try {
      final req = await client.getUrl(uri);
      req.headers.set(HttpHeaders.acceptHeader, 'text/event-stream');
      req.headers.set(HttpHeaders.cacheControlHeader, 'no-cache');

      final res = await req.close();
      if (!_isCurrent(generation, controller)) {
        client.close(force: true);
        return;
      }

      if (res.statusCode == HttpStatus.unauthorized) {
        final body = await utf8.decoder.bind(res).join();
        final code = _authCodeFromBody(body);
        L.w('realtime', 'sse.connect.failed', data: {'reason': code});
        controller.addError(SseAuthException(code), StackTrace.current);
        _stopTransport();
        return;
      }

      if (res.statusCode != HttpStatus.ok) {
        final body = await utf8.decoder.bind(res).join();
        final err = StateError('sse_http_${res.statusCode}');
        L.w('realtime', 'sse.connect.failed',
            data: {'status': res.statusCode, 'reason': body});
        controller.addError(err, StackTrace.current);
        _stopTransport();
        return;
      }

      L.i('realtime', 'sse.connect.success');
      final dataLines = <String>[];
      _lineSub =
          res.transform(utf8.decoder).transform(const LineSplitter()).listen(
        (line) {
          if (!_isCurrent(generation, controller)) return;
          _consumeLine(controller, dataLines, line);
        },
        onError: (Object e, StackTrace st) {
          if (!_isCurrent(generation, controller)) return;
          L.e('realtime', 'sse.connect.failed', error: e, stackTrace: st);
          controller.addError(e, st);
        },
        onDone: () {
          if (!_isCurrent(generation, controller)) return;
          unawaited(controller.close());
        },
        cancelOnError: true,
      );
    } catch (e, st) {
      if (!_isCurrent(generation, controller)) return;
      L.e('realtime', 'sse.connect.failed', error: e, stackTrace: st);
      controller.addError(e, st);
      _stopTransport();
    }
  }

  bool _isCurrent(int generation, StreamController<RealtimeEvent> controller) =>
      generation == _generation && identical(controller, _controller);

  void _consumeLine(
    StreamController<RealtimeEvent> controller,
    List<String> dataLines,
    String line,
  ) {
    if (line.isEmpty) {
      if (dataLines.isEmpty) return;
      final raw = dataLines.join('\n').trim();
      dataLines.clear();
      if (raw.isEmpty) return;
      try {
        final json = jsonDecode(raw) as Map<String, dynamic>;
        controller.add(RealtimeEvent.fromJson(json));
      } catch (e, st) {
        L.e('realtime', 'sse_parse_failed', error: e, stackTrace: st);
      }
      return;
    }
    if (line.startsWith(':')) return;
    if (line.startsWith('data:')) {
      dataLines.add(line.substring(5).trimLeft());
    }
  }

  String _authCodeFromBody(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        final detail = decoded['detail'] ?? decoded['error'];
        if (detail is String && detail.isNotEmpty) return detail;
      }
    } catch (_) {
      // Fall through to substring checks.
    }
    if (body.contains('missing_access_token')) return 'missing_access_token';
    return 'invalid_access_token';
  }

  @override
  Future<void> disconnect() async {
    _generation += 1;
    _stopTransport();
    await _controller?.close();
    _controller = null;
  }

  void _stopTransport() {
    unawaited(_lineSub?.cancel());
    _lineSub = null;
    _client?.close(force: true);
    _client = null;
  }
}

/// Mock service for offline UI work. Emits a HUMAN_SIGNAL every 12s and
/// a METRIC_TICK every 6s on a deterministic-ish schedule so demos and
/// screenshots have something visibly moving.
class MockRealtimeService implements RealtimeService {
  MockRealtimeService();

  StreamController<RealtimeEvent>? _controller;
  Timer? _signalTimer;
  Timer? _tickTimer;
  int _counter = 0;

  @override
  Stream<RealtimeEvent> subscribe({
    required String accessToken,
    List<String> matchIds = const [],
    List<String> eventTypes = const [],
  }) {
    unawaited(disconnect());

    final controller = StreamController<RealtimeEvent>.broadcast();
    _controller = controller;

    // First HUMAN_SIGNAL after 8s, then every 18s — matches the home
    // demo cadence so the "X novos posts" pill appears within a session
    // without spamming.
    _signalTimer = Timer.periodic(const Duration(seconds: 18), (_) {
      _emit(controller, EventType.humanSignal);
    });
    Future.delayed(const Duration(seconds: 8), () {
      if (controller.isClosed) return;
      _emit(controller, EventType.humanSignal);
    });

    // METRIC_TICK every 6s — burns demo battery but proves the live
    // pressure timeline path. Use the first matchId from filters when
    // available so MatchDetail sees its own match.
    _tickTimer = Timer.periodic(const Duration(seconds: 6), (_) {
      _emit(
        controller,
        EventType.metricTick,
        matchId:
            matchIds.isNotEmpty ? matchIds.first : 'm_demo_${_counter % 4}',
      );
    });

    return controller.stream;
  }

  void _emit(
    StreamController<RealtimeEvent> ctl,
    EventType type, {
    String? matchId,
  }) {
    if (ctl.isClosed) return;
    _counter += 1;
    final value = (Random(_counter).nextDouble() * 0.6) + 0.2;
    ctl.add(
      RealtimeEvent(
        eventId: 'mock_${DateTime.now().microsecondsSinceEpoch}_$_counter',
        eventType: type,
        matchId: matchId,
        tsIngest: DateTime.now().toUtc().toIso8601String(),
        payload: {'value': value},
        stream: 'mock',
      ),
    );
  }

  @override
  Future<void> disconnect() async {
    _signalTimer?.cancel();
    _signalTimer = null;
    _tickTimer?.cancel();
    _tickTimer = null;
    await _controller?.close();
    _controller = null;
  }
}
