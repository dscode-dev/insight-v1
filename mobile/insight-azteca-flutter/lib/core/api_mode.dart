import 'env.dart';

/// Selects between mock providers and live Gateway HTTP transport.
///
/// Production safety (Sprint 2, Part 12): mock is a DEMO-ONLY path —
/// it requires ENABLE_DEMO_MODE=true and is never honored in
/// production builds. Anything unrecognized resolves to gateway, so
/// a typo can never ship fixtures to users.
enum ApiMode {
  mock,
  gateway;

  static ApiMode get current {
    final wantsMock = InsightEnv.apiModeRaw.toLowerCase() == 'mock';
    if (wantsMock && InsightEnv.enableDemoMode && !InsightEnv.isProduction) {
      return ApiMode.mock;
    }
    return ApiMode.gateway;
  }

  bool get isLive => this == ApiMode.gateway;
  bool get isMock => this == ApiMode.mock;
}
