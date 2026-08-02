import 'package:dio/dio.dart';

import 'gateway_client.dart';

/// Report reasons — mirror the Gateway's vocabulary (Store-A). `api` is the
/// wire value; `label` is the pt-BR copy shown in the reason picker.
enum ReportReason {
  inappropriate('inappropriate', 'Conteúdo inadequado / pornografia'),
  hate('hate', 'Discurso de ódio / assédio'),
  spam('spam', 'Spam / golpe'),
  violence('violence', 'Violência / ameaça'),
  other('other', 'Outro');

  const ReportReason(this.api, this.label);
  final String api;
  final String label;
}

/// Report target types (post | comment | user).
enum ReportTarget {
  post('post'),
  comment('comment'),
  user('user');

  const ReportTarget(this.api);
  final String api;
}

/// UGC-safety actions (Store-A): report content + block/unblock users.
abstract class ModerationApi {
  Future<void> report({
    required ReportTarget target,
    required String targetId,
    required ReportReason reason,
    String? description,
  });
  Future<void> blockUser(String userId);
  Future<void> unblockUser(String userId);
}

class GatewayModerationService implements ModerationApi {
  GatewayModerationService(this._dio);
  final Dio _dio;

  @override
  Future<void> report({
    required ReportTarget target,
    required String targetId,
    required ReportReason reason,
    String? description,
  }) async {
    await _dio.postJson('/v1/reports', body: {
      'target_type': target.api,
      'target_id': targetId,
      'reason': reason.api,
      if (description != null && description.trim().isNotEmpty)
        'description': description.trim(),
    });
  }

  @override
  Future<void> blockUser(String userId) =>
      _dio.postJson('/v1/users/$userId/block');

  @override
  Future<void> unblockUser(String userId) =>
      _dio.delete<void>('/v1/users/$userId/block');
}

/// Offline/demo no-op implementation (mock mode).
class NoopModerationService implements ModerationApi {
  @override
  Future<void> report({
    required ReportTarget target,
    required String targetId,
    required ReportReason reason,
    String? description,
  }) async {}
  @override
  Future<void> blockUser(String userId) async {}
  @override
  Future<void> unblockUser(String userId) async {}
}
