import 'package:dio/dio.dart';

import '../mock/fixtures/radar_fixtures.dart';
import '../models/radar.dart';
import 'gateway_client.dart';

abstract class RadarService {
  Future<RadarBundle> bundle({RadarTimeframe timeframe = RadarTimeframe.today});
}

/// Gateway-backed Radar service.
///
/// Endpoint: `GET /v1/radar/bundle?timeframe=last_hour|today|last_7d`
/// → `RadarBundle` (snake_case on wire, camelCase via build.yaml).
///
/// Stubbed on the Gateway side until the upstream Anvil/ClickHouse
/// queries land — see bff.py for the data sources expected.
class GatewayRadarService implements RadarService {
  GatewayRadarService(this._dio);
  final Dio _dio;

  @override
  Future<RadarBundle> bundle({
    RadarTimeframe timeframe = RadarTimeframe.today,
  }) async {
    final body = await _dio.getJson(
      '/v1/radar/bundle',
      query: {'timeframe': _timeframeWire(timeframe)},
    );
    return RadarBundle.fromJson(body);
  }

  String _timeframeWire(RadarTimeframe t) {
    switch (t) {
      case RadarTimeframe.lastHour:
        return 'last_hour';
      case RadarTimeframe.today:
        return 'today';
      case RadarTimeframe.last7Days:
        return 'last_7d';
    }
  }
}

class MockRadarService implements RadarService {
  @override
  Future<RadarBundle> bundle({
    RadarTimeframe timeframe = RadarTimeframe.today,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 220));
    final full = kRadarBundle();
    final now = DateTime.now();
    final cutoff = now.subtract(timeframe.window);
    return full.copyWith(
      movements: full.movements.where((m) => m.ts.isAfter(cutoff)).toList(),
      signals: full.signals.where((s) => s.ts.isAfter(cutoff)).toList(),
      // Trending is "what's hot now" — keep as-is regardless of window.
    );
  }
}
