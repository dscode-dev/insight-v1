/// Startup configuration validation + diagnostics — V1.1 closure
/// (Sprint X: "remove hidden deployment traps").
///
/// Runs once at boot, BEFORE the widget tree:
///   * validates the resolved configuration for the build environment
///     (production must never ship mocks, demo mode, http://, or
///     localhost);
///   * prints one structured diagnostic line so any build's effective
///     config is visible in `flutter logs` / device logs / CI output.
///
/// Violations THROW in production builds — a misconfigured release
/// crashes at boot in CI/smoke instead of shipping empty feeds to
/// users. Dev/staging log the violation and keep running.
library;

import 'package:flutter/foundation.dart';

import 'api_mode.dart';
import 'env.dart';

/// Tripwire: the production social stack is the Social Foundation
/// (feed/posts/comments/likes/follow over the Gateway). This stays
/// `false`; flipping it to re-enable the legacy discussion/reaction
/// flow trips StartupDiagnostics in a production build.
bool kLegacySocialStackActive = false;

/// Indirection so the dead-code analyzer can't const-fold the tripwire
/// check away — it is a real runtime guard.
bool _legacyStackActive() => kLegacySocialStackActive;

class StartupConfigError extends Error {
  StartupConfigError(this.violations);

  final List<String> violations;

  @override
  String toString() =>
      'StartupConfigError: invalid production configuration:\n'
      '  - ${violations.join('\n  - ')}';
}

class StartupDiagnostics {
  const StartupDiagnostics._();

  /// Returns the violation list (empty = valid). Pure — testable
  /// without bindings.
  static List<String> validate() {
    final violations = <String>[];
    if (!InsightEnv.isProduction) return violations;

    if (ApiMode.current.isMock) {
      violations.add('API_MODE=mock resolved in a production build');
    }
    if (InsightEnv.enableDemoMode) {
      violations.add('ENABLE_DEMO_MODE=true in a production build');
    }
    final url = Uri.tryParse(InsightEnv.apiBaseUrl);
    if (url == null || url.scheme != 'https') {
      violations.add(
        'API_BASE_URL must be https in production '
        '(got: ${InsightEnv.apiBaseUrl})',
      );
    }
    if (url != null &&
        (url.host == 'localhost' || url.host.startsWith('127.'))) {
      violations.add(
        'API_BASE_URL points at localhost in production '
        '(got: ${InsightEnv.apiBaseUrl})',
      );
    }
    if (!InsightEnv.flag(InsightEnv.flagSocialV1)) {
      violations.add(
        'social_v1 disabled in production — the app requires the real '
        'Social Foundation client (no empty/demo fallback in prod)',
      );
    }
    // The production social stack MUST be the Social Foundation. This
    // tripwire is the single switch a future change would have to flip
    // to re-introduce the legacy feed/discussion/reaction flow — and if
    // someone does, this fails the production build at boot.
    if (_legacyStackActive()) {
      violations.add(
        'legacy social stack active in production — feed/discussion/'
        'reaction endpoints must not be in the production flow',
      );
    }
    // STAGING-INTEGRATION-B: the official Gateway is the single host
    // `insight-api.konohalabs.com.br` with no region prefix (`/v1` lives in the
    // path layer). The app must point at that host in production.
    if (url != null && url.host != 'insight-api.konohalabs.com.br') {
      violations.add(
        'API_BASE_URL must be the official Gateway '
        'https://insight-api.konohalabs.com.br — got: ${InsightEnv.apiBaseUrl}',
      );
    }
    return violations;
  }

  /// One-line effective-config summary (no secrets exist in the app
  /// by design, so the whole config is loggable).
  static String summary() {
    return 'insight_startup '
        'env=${InsightEnv.environment.name} '
        'api_mode=${ApiMode.current.name} '
        'base_url=${InsightEnv.apiBaseUrl} '
        'flags=${InsightEnv.featureFlags.join('+')} '
        'demo=${InsightEnv.enableDemoMode} '
        'analytics=${InsightEnv.enableAnalytics}';
  }

  /// Boot hook: log the summary, enforce production validity.
  static void run() {
    debugPrint(summary());
    final violations = validate();
    if (violations.isEmpty) return;
    if (InsightEnv.isProduction) {
      throw StartupConfigError(violations);
    }
    for (final v in violations) {
      debugPrint('insight_startup_warning: $v');
    }
  }
}
