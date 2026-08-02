import 'package:dio/dio.dart';

import '../models/competition.dart';
import 'gateway_client.dart';

/// Featured Competitions Rail data source (AZTECA-HOME-A).
///
/// Gateway-backed and backend-authoritative: the only endpoint is
/// `GET /v1/competitions/highlights`, which the Gateway proxies from
/// insight-social. There is NO local/mock fallback — the rail shows whatever
/// the backend returns (or its empty state when the list is empty). The client
/// preserves the backend's ordering exactly.
class GatewayCompetitionService {
  GatewayCompetitionService(this._dio);
  final Dio _dio;

  Future<List<Competition>> highlights() async {
    final body = await _dio.getJson('/v1/competitions/highlights');
    final raw = body['competitions'];
    if (raw is! List) return const <Competition>[];
    return raw
        .whereType<Map<String, dynamic>>()
        .map(Competition.fromJson)
        .where((c) => c.active)
        .toList(growable: false);
  }
}
