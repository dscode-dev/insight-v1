// FEATURE-SEARCH-V1 Stage 3 — explicit search state.
//
// Phases are modeled explicitly (never "partial == success"). An epoch counter
// guards against out-of-order responses: every query bumps the epoch; a response
// tagged with a stale epoch is dropped. Cursors are per category and reset on a
// new query. Dedupe is by entity_type:entity_id.

import 'package:flutter/foundation.dart';

import '../model/search_models.dart';

enum SearchPhase {
  discovery, // empty query — recent history + guidance
  debouncing,
  loading,
  loadingMore,
  success,
  empty,
  partial, // some categories unavailable (All only)
  unavailable, // every category failed / capability off
  offline,
  timeout,
  unauthorized,
  error,
}

@immutable
class SearchState {
  const SearchState({
    required this.phase,
    required this.query,
    required this.results,
    required this.cursors,
    required this.failedCategories,
    required this.hasMore,
    required this.epoch,
  });

  final SearchPhase phase;
  final String query;
  final List<SearchCard> results;

  /// Per-category continuation cursors. For a specific tab only its own key is
  /// used; for All the full map (per category) comes from the Gateway.
  final Map<String, String> cursors;
  final List<String> failedCategories;
  final bool hasMore;
  final int epoch;

  static const initial = SearchState(
    phase: SearchPhase.discovery, query: '', results: [],
    cursors: {}, failedCategories: [], hasMore: false, epoch: 0,
  );

  bool get isPartial => phase == SearchPhase.partial;

  SearchState copyWith({
    SearchPhase? phase,
    String? query,
    List<SearchCard>? results,
    Map<String, String>? cursors,
    List<String>? failedCategories,
    bool? hasMore,
    int? epoch,
  }) =>
      SearchState(
        phase: phase ?? this.phase,
        query: query ?? this.query,
        results: results ?? this.results,
        cursors: cursors ?? this.cursors,
        failedCategories: failedCategories ?? this.failedCategories,
        hasMore: hasMore ?? this.hasMore,
        epoch: epoch ?? this.epoch,
      );

  /// Append a page with dedupe by card key (pagination never duplicates rows).
  SearchState appendDeduped(List<SearchCard> more, {
    required Map<String, String> cursors,
    required bool hasMore,
    SearchPhase? phase,
  }) {
    final seen = {for (final c in results) c.key};
    final merged = [...results];
    for (final c in more) {
      if (seen.add(c.key)) merged.add(c);
    }
    return copyWith(
      results: merged, cursors: cursors, hasMore: hasMore,
      phase: phase ?? (merged.isEmpty ? SearchPhase.empty : this.phase),
    );
  }
}
