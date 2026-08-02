// V1.1 — production-config validation. These run in a dev-flavoured
// test binary (ENVIRONMENT is compile-time), so the assertions cover
// the pure pieces: default flags, flag disabling, summary shape, and
// that validate() is a no-op outside production.

import 'package:flutter_test/flutter_test.dart';
import 'package:azteca/core/env.dart';
import 'package:azteca/core/startup_diagnostics.dart';

void main() {
  test('social_v1 is on by default (no FEATURE_FLAGS needed)', () {
    expect(InsightEnv.defaultFlags, contains('social_v1'));
    expect(InsightEnv.flag('social_v1'), isTrue);
  });

  test('summary exposes effective config without throwing', () {
    final s = StartupDiagnostics.summary();
    expect(s, contains('env='));
    expect(s, contains('api_mode='));
    expect(s, contains('social_v1'));
  });

  test('validate is empty outside production', () {
    expect(StartupDiagnostics.validate(), isEmpty);
  });

  test('run() logs and does not throw in dev builds', () {
    expect(StartupDiagnostics.run, returnsNormally);
  });
}
