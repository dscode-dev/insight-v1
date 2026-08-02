import 'package:dio/dio.dart';

import '../mock/fixtures/live_fixtures.dart';
import '../models/live.dart';
import '../models/match.dart';
import '../models/match_context_response.dart';
import 'gateway_client.dart';

abstract class LiveService {
  Future<List<LiveMatch>> listLive(LiveFilter filter);
  Future<MatchDetail> getDetail(String matchId);
  /// Sprint 6.2 Part 4 — descriptive match context from Atlas via
  /// `GET /v1/context/match/{matchId}`. Returns an empty response (not
  /// null, not an exception) when Atlas has no inference for the match
  /// so the UI can render an EmptyState without branching on null.
  Future<MatchContextResponse> getContext(String matchId);
}

/// Gateway-backed Live service.
///
/// Endpoints consumed:
///   * `GET  /v1/live/matches?status=<all|live|today|upcoming>`
///   * `GET  /v1/live/matches/{match_id}`
///
/// Both endpoints land in `gateway/api/routes/bff.py` (Sprint 1.5). The
/// wire shapes mirror this side's Freezed models 1:1 via snake_case;
/// the build.yaml `field_rename: snake` config handles the conversion.
class GatewayLiveService implements LiveService {
  GatewayLiveService(this._dio);
  final Dio _dio;

  @override
  Future<List<LiveMatch>> listLive(LiveFilter filter) async {
    final body = await _dio.getJson(
      '/v1/live/matches',
      query: {
        'status': filter.status.name,
        if (filter.competitionId != null)
          'competition_id': filter.competitionId,
      },
    );
    final items = (body['items'] as List? ?? const [])
        .cast<Map<String, dynamic>>()
        .map(LiveMatch.fromJson)
        .toList(growable: false);
    return items;
  }

  @override
  Future<MatchDetail> getDetail(String matchId) async {
    final body = await _dio.getJson('/v1/live/matches/$matchId');
    return MatchDetail.fromJson(body);
  }

  @override
  Future<MatchContextResponse> getContext(String matchId) async {
    // Gateway → Atlas. 404 / 503 from Atlas surfaces here as a Dio
    // exception; the caller wraps it in an AsyncError so the UI
    // shows ErrorState with a Retry, never a blank tab.
    final body = await _dio.getJson('/v1/context/match/$matchId');
    return MatchContextResponse.fromJson(body);
  }
}

class MockLiveService implements LiveService {
  static const _latency = Duration(milliseconds: 220);

  @override
  Future<List<LiveMatch>> listLive(LiveFilter filter) async {
    await Future<void>.delayed(_latency);
    final all = kLiveMatches();
    return all.where((m) {
      switch (filter.status) {
        case LiveStatusFilter.all:
          return true;
        case LiveStatusFilter.live:
          return m.summary.status.state.isLive;
        case LiveStatusFilter.today:
          // V1: anything scheduled within the next 24h or live counts.
          if (m.summary.status.state.isLive) return true;
          final delta = m.summary.status.kickoff.difference(DateTime.now());
          return delta.inHours < 24 && delta.inHours >= 0;
        case LiveStatusFilter.upcoming:
          return m.summary.status.state == MatchState.scheduled;
      }
    }).toList();
  }

  @override
  Future<MatchDetail> getDetail(String matchId) async {
    await Future<void>.delayed(_latency);
    return kMatchDetail(matchId);
  }

  @override
  Future<MatchContextResponse> getContext(String matchId) async {
    await Future<void>.delayed(_latency);
    // Dev mode: empty context exercises the EmptyState branch in
    // MatchDetail without inventing fake signals.
    return const MatchContextResponse();
  }
}
