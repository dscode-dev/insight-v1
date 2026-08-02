import 'package:dio/dio.dart';

import '../mock/fixtures/profile_fixtures.dart';
import '../models/profile.dart';
import 'gateway_client.dart';

abstract class ProfileService {
  Future<ProfileBundle> bundle();
}

/// Gateway-backed Profile service.
///
/// Endpoint: `GET /v1/profile/me/bundle` → ProfileBundle
///
/// Stubbed on the Gateway side until the Plaza reputation/stats +
/// ClickHouse activity projections are wired in.
class GatewayProfileService implements ProfileService {
  GatewayProfileService(this._dio);
  final Dio _dio;

  @override
  Future<ProfileBundle> bundle() async {
    final body = await _dio.getJson('/v1/profile/me/bundle');
    return ProfileBundle.fromJson(body);
  }
}

class MockProfileService implements ProfileService {
  @override
  Future<ProfileBundle> bundle() async {
    await Future<void>.delayed(const Duration(milliseconds: 200));
    return kProfileBundle();
  }
}
