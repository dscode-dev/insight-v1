import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api_mode.dart';
import '../mock/feed_mock.dart';
import '../services/gateway_client.dart';
import '../services/auth_service.dart';
import '../services/feed_service.dart';

/// Compile-time API mode (`mock` or `gateway`). Exposed as a provider so
/// tests can override.
final apiModeProvider = Provider<ApiMode>((ref) => ApiMode.current);

/// AuthService — picks the right implementation based on api mode.
final authServiceProvider = Provider<AuthService>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayAuthService(ref.watch(gatewayDioProvider));
  }
  return MockAuthService();
});

/// FeedService — picks the right implementation based on api mode.
final feedServiceProvider = Provider<FeedService>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayFeedService(ref.watch(gatewayDioProvider));
  }
  return MockFeedService();
});
