// Sprint A — Discussion thread service.
//
// Three gateway BFF endpoints (all under /v1/discussions/{id}):
//   GET    /v1/discussions/{id}                → DiscussionDetail
//   GET    /v1/discussions/{id}/messages       → DiscussionMessagesPage
//   POST   /v1/discussions/{id}/messages       → DiscussionMessage
//
// Authorization is attached by gateway_client's _AuthInterceptor; no
// caller in this file needs to think about tokens.
//
// Mock impl uses an in-memory fixture so the screen renders in
// `--dart-define=insight.api=mock` mode for design/QA without a
// running gateway.
import 'package:dio/dio.dart';
import 'package:uuid/uuid.dart';

import '../core/errors.dart';
import '../models/discussion_thread.dart';
import 'gateway_client.dart';

abstract class DiscussionService {
  /// Returns null when the discussion id doesn't exist.
  Future<DiscussionDetail?> get(String id);

  Future<DiscussionMessagesPage> messages(String id, {String? cursor});

  Future<DiscussionMessage> postMessage(String discussionId, {required String body});
}

class GatewayDiscussionService implements DiscussionService {
  GatewayDiscussionService(this._dio);
  final Dio _dio;

  @override
  Future<DiscussionDetail?> get(String id) async {
    try {
      final body = await _dio.getJson('/v1/discussions/$id');
      return DiscussionDetail.fromJson(body);
    } on GatewayException catch (e) {
      if (e.statusCode == 404) return null;
      rethrow;
    }
  }

  @override
  Future<DiscussionMessagesPage> messages(String id, {String? cursor}) async {
    final body = await _dio.getJson(
      '/v1/discussions/$id/messages',
      query: cursor == null ? null : {'cursor': cursor},
    );
    return DiscussionMessagesPage.fromJson(body);
  }

  @override
  Future<DiscussionMessage> postMessage(String discussionId, {required String body}) async {
    final resp = await _dio.postJson(
      '/v1/discussions/$discussionId/messages',
      body: {'body': body},
    );
    return DiscussionMessage.fromJson(resp);
  }
}

class MockDiscussionService implements DiscussionService {
  // Session-scoped state so a reply posted in the screen sticks until
  // the app reloads. Per-discussion to keep different threads
  // independent.
  final Map<String, List<DiscussionMessage>> _messagesByThread = {};
  final _uuid = const Uuid();

  @override
  Future<DiscussionDetail?> get(String id) async {
    await Future<void>.delayed(const Duration(milliseconds: 180));
    return DiscussionDetail(
      id: id,
      title: 'Discussão de exemplo',
      body:
          'Esta é uma thread de exemplo renderizada pelo MockDiscussionService.\n'
          'Use o composer abaixo para responder.',
      communityId: 'mock-community',
      communityName: 'Comunidade de teste',
      communityHandle: '#mock',
      authorId: 'mock-author',
      authorDisplayName: 'Autor Original',
      authorInitials: 'AO',
      authorAccent: '#5BA8FF',
      replyCount: _messagesByThread[id]?.length ?? 0,
      reactionCount: 0,
      createdAt: DateTime.now().subtract(const Duration(hours: 3)),
      lastActivityTs: DateTime.now(),
    );
  }

  @override
  Future<DiscussionMessagesPage> messages(String id, {String? cursor}) async {
    await Future<void>.delayed(const Duration(milliseconds: 120));
    final list = _messagesByThread[id] ?? const [];
    return DiscussionMessagesPage(messages: list, nextCursor: null);
  }

  @override
  Future<DiscussionMessage> postMessage(String discussionId, {required String body}) async {
    await Future<void>.delayed(const Duration(milliseconds: 140));
    final m = DiscussionMessage(
      id: _uuid.v4(),
      authorId: 'me-mock',
      authorDisplayName: 'Você',
      authorInitials: 'EU',
      authorAccent: '#5BA8FF',
      body: body,
      ts: DateTime.now(),
    );
    _messagesByThread.update(discussionId, (l) => [...l, m], ifAbsent: () => [m]);
    return m;
  }
}
