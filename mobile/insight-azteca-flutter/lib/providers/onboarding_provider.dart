// Onboarding state — Sprint 6.2 Part 3.
//
// Tracks whether the operator has finished the first-launch onboarding.
// Persisted via flutter_secure_storage (already a project dep) under
// `onboarding_completed_v1`. The `_v1` suffix lets us re-trigger
// onboarding on future schema changes without colliding with old keys.
//
// Public surface:
//   onboardingStatusProvider  — AsyncValue<bool> (true == completed)
//   markOnboardingDone()      — persists + flips the provider
//
// The router uses onboardingStatusProvider to decide whether to redirect
// freshly-authenticated users to /onboarding/welcome.

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

const String _kKey = 'onboarding_completed_v1';
const FlutterSecureStorage _storage = FlutterSecureStorage();

/// Future provider that hydrates the persisted flag on first read. Returns
/// `true` when onboarding has been completed; `false` otherwise.
final onboardingStatusProvider = FutureProvider<bool>((ref) async {
  final value = await _storage.read(key: _kKey);
  return value == 'true';
});

/// Imperative helper used by the Finish button. Writes through to storage,
/// then invalidates the provider so the router redirect re-evaluates and
/// the operator lands on Home.
Future<void> markOnboardingDone(WidgetRef ref) async {
  await _storage.write(key: _kKey, value: 'true');
  ref.invalidate(onboardingStatusProvider);
}

/// Test-only / development reset.
Future<void> resetOnboarding(WidgetRef ref) async {
  await _storage.delete(key: _kKey);
  ref.invalidate(onboardingStatusProvider);
}
