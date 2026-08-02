// FEATURE-SEARCH-V1 Stage 3 — capabilities + history providers.
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/search_service.dart';
import '../model/search_models.dart';

/// Backend capabilities drive the visible tabs. Falls back to a minimal safe set
/// (never a hardcoded full list) if the contract can't be read.
final searchCapabilitiesProvider = FutureProvider<SearchCapabilities>((ref) async {
  try {
    return await ref.watch(searchServiceProvider).capabilities();
  } catch (_) {
    return SearchCapabilities.fallback;
  }
});

/// Recent searches — the Gateway is the single source of truth (no competing
/// local persistence). Refreshable after a new first-page search.
final searchHistoryProvider =
    FutureProvider.autoDispose<List<SearchHistoryItem>>((ref) async {
  return ref.watch(searchServiceProvider).history();
});

final searchHistoryActionsProvider = Provider<SearchHistoryActions>((ref) {
  return SearchHistoryActions(ref);
});

class SearchHistoryActions {
  SearchHistoryActions(this._ref);
  final Ref _ref;
  Future<void> clear() async {
    await _ref.read(searchServiceProvider).clearHistory();
    _ref.invalidate(searchHistoryProvider);
  }
  void refresh() => _ref.invalidate(searchHistoryProvider);
}
