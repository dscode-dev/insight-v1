import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/env.dart';
import '../core/feature_gate.dart';
import '../models/radar.dart';
import '../services/services_providers.dart';

/// Active timeframe for the radar. Default is "today" — broad enough to
/// show meaningful market movement without burying current activity.
final radarTimeframeProvider = StateProvider<RadarTimeframe>(
  (_) => RadarTimeframe.today,
);

final radarBundleProvider = FutureProvider.autoDispose<RadarBundle>((ref) {
  // Orphan route (/v1/radar/bundle) — gated off until served.
  if (!InsightEnv.flag(InsightEnv.flagRadarV1)) {
    throw const FeatureUnavailable('radar');
  }
  final tf = ref.watch(radarTimeframeProvider);
  return ref.watch(radarServiceProvider).bundle(timeframe: tf);
});
