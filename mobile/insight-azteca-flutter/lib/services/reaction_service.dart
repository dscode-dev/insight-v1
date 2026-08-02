// Sprint B — Reaction service.
//
// Endpoints:
//   POST   /v1/reactions/discussion/{id}   → 201 (idempotent — server
//                                                returns existing row
//                                                if already liked)
//   DELETE /v1/reactions/discussion/{id}   → 204 (no-op if absent)
//
// All targets in Sprint B are Discussions. Signal/Message reactions
// land later (no UI surface yet).
import 'package:dio/dio.dart';

abstract class ReactionService {
  Future<void> likeDiscussion(String discussionId);
  Future<void> unlikeDiscussion(String discussionId);
}

class GatewayReactionService implements ReactionService {
  GatewayReactionService(this._dio);
  final Dio _dio;

  @override
  Future<void> likeDiscussion(String discussionId) async {
    await _dio.post<dynamic>('/v1/reactions/discussion/$discussionId');
  }

  @override
  Future<void> unlikeDiscussion(String discussionId) async {
    await _dio.delete<dynamic>('/v1/reactions/discussion/$discussionId');
  }
}

/// Local-only mock — no persistence across cold starts. Sufficient
/// for `--dart-define=insight.api=mock` UI work.
class MockReactionService implements ReactionService {
  @override
  Future<void> likeDiscussion(String discussionId) async {
    await Future<void>.delayed(const Duration(milliseconds: 80));
  }

  @override
  Future<void> unlikeDiscussion(String discussionId) async {
    await Future<void>.delayed(const Duration(milliseconds: 80));
  }
}
