import 'package:dio/dio.dart';

import '../core/errors.dart';
import '../mock/fixtures/hub_fixtures.dart';
import '../models/hub.dart';
import 'gateway_client.dart';

abstract class HubService {
  Future<HubBundle> bundle({HubSegment segment = HubSegment.hot});

  /// Returns null when the id doesn't match a known community.
  Future<CommunityDetail?> communityDetail(String id);
}

/// Gateway-backed Hub service.
///
/// Endpoints:
///   * `GET /v1/hub/bundle?segment=mine|hot|fresh`           → HubBundle
///   * `GET /v1/hub/communities/{community_id}`              → CommunityDetail
///
/// Stubbed on the Gateway side until Plaza's `communities`, `tipsters`,
/// `discussions` projections are wired in.
class GatewayHubService implements HubService {
  GatewayHubService(this._dio);
  final Dio _dio;

  @override
  Future<HubBundle> bundle({HubSegment segment = HubSegment.hot}) async {
    final body = await _dio.getJson(
      '/v1/hub/bundle',
      query: {'segment': segment.name},
    );
    return HubBundle.fromJson(body);
  }

  @override
  Future<CommunityDetail?> communityDetail(String id) async {
    try {
      final body = await _dio.getJson('/v1/hub/communities/$id');
      return CommunityDetail.fromJson(body);
    } on GatewayException catch (e) {
      if (e.statusCode == 404) return null;
      rethrow;
    }
  }
}

class MockHubService implements HubService {
  @override
  Future<HubBundle> bundle({
    HubSegment segment = HubSegment.hot,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 220));
    final full = kHubBundle();
    switch (segment) {
      case HubSegment.hot:
        return full.copyWith(
          communities: [...full.communities]
            ..sort((a, b) => b.activeMembers.compareTo(a.activeMembers)),
          tipsters: [...full.tipsters]
            ..sort((a, b) => b.accuracy.compareTo(a.accuracy)),
          discussions: [...full.discussions]
            ..sort((a, b) => b.replies.compareTo(a.replies)),
        );
      case HubSegment.fresh:
        return full.copyWith(
          // For now, "novas" sorts discussions by recency. When a real
          // backend distinguishes "novas comunidades", swap this for that
          // signal.
          discussions: [...full.discussions]
            ..sort((a, b) => b.lastActivityTs.compareTo(a.lastActivityTs)),
        );
      case HubSegment.mine:
        // No membership data in the mock yet — show empty across the board
        // so the UI can render its "siga uma comunidade pra ver aqui" hint
        // without faking content.
        return const HubBundle(
          communities: [],
          tipsters: [],
          discussions: [],
        );
    }
  }

  @override
  Future<CommunityDetail?> communityDetail(String id) async {
    await Future<void>.delayed(const Duration(milliseconds: 180));
    return kCommunityDetail(id);
  }
}
