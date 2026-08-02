import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/env.dart';
import '../core/feature_gate.dart';
import '../models/live.dart';
import '../models/match_context_response.dart';
import '../services/services_providers.dart';

/// Active filter for the Live screen.
final liveFilterProvider = StateProvider<LiveFilter>(
  (_) => const LiveFilter(),
);

/// Live match list driven by the current filter.
final liveMatchesProvider = FutureProvider.autoDispose<List<LiveMatch>>((ref) {
  // Orphan route (/v1/live/matches) — gated off until the Gateway
  // serves it, so a production build never fires a 404.
  if (!InsightEnv.flag(InsightEnv.flagLiveV1)) {
    throw const FeatureUnavailable('live');
  }
  final filter = ref.watch(liveFilterProvider);
  return ref.watch(liveServiceProvider).listLive(filter);
});

/// Per-match detail — keyed by matchId.
final matchDetailProvider =
    FutureProvider.autoDispose.family<MatchDetail, String>((ref, id) {
  if (!InsightEnv.flag(InsightEnv.flagLiveV1)) {
    throw const FeatureUnavailable('live');
  }
  return ref.watch(liveServiceProvider).getDetail(id);
});

/// Per-match descriptive context from Atlas — keyed by matchId.
/// Sprint 6.2 Part 4. Distinct from `matchDetailProvider` because:
///   * context arrives from a different upstream (Atlas vs Hub-via-Gateway);
///   * it can be empty or fail independently and the detail tab still works;
///   * the operator may refresh just the context tab without re-fetching
///     the rest of the match.
final matchContextProvider =
    FutureProvider.autoDispose.family<MatchContextResponse, String>((ref, id) {
  if (!InsightEnv.flag(InsightEnv.flagLiveV1)) {
    throw const FeatureUnavailable('live');
  }
  return ref.watch(liveServiceProvider).getContext(id);
});
