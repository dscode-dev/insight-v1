// FEATURE-SEARCH-V1 Stage 3 — SearchController (one per active category tab).
//
// Owns: debounce (300ms), cancellation of the superseded request at the HTTP
// client, out-of-order protection (epoch), per-category cursor pagination with
// dedupe, and the mapping of transport errors to explicit phases. Widgets read
// this notifier's state; they never touch the service.

import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/errors.dart';
import '../data/search_service.dart';
import '../model/search_models.dart';
import 'search_state.dart';

const _debounce = Duration(milliseconds: 300);
const _minQueryLen = 2;

class SearchController extends StateNotifier<SearchState> {
  SearchController(this._service, this.category) : super(SearchState.initial);

  final SearchService _service;
  final SearchCategory category;

  Timer? _timer;
  CancelToken? _inflight;

  /// Called on each keystroke. Debounced; empty/short → discovery (no request).
  void onQueryChanged(String raw) {
    final q = raw.trim();
    _timer?.cancel();
    if (q.length < _minQueryLen) {
      _cancelInflight();
      // New epoch so any late response for a previous query is ignored.
      state = SearchState.initial.copyWith(epoch: state.epoch + 1, query: q);
      return;
    }
    state = state.copyWith(phase: SearchPhase.debouncing, query: q);
    _timer = Timer(_debounce, () => _run(q));
  }

  /// Run a query immediately (e.g. selecting a history entry).
  void submit(String raw) {
    final q = raw.trim();
    _timer?.cancel();
    if (q.length < _minQueryLen) return;
    _run(q);
  }

  Future<void> _run(String q) async {
    _cancelInflight();
    final epoch = state.epoch + 1;
    final token = CancelToken();
    _inflight = token;
    state = state.copyWith(
      phase: SearchPhase.loading, query: q, epoch: epoch,
      results: const [], cursors: const {}, failedCategories: const [], hasMore: false,
    );
    try {
      if (category == SearchCategory.all) {
        final res = await _service.all(q, cancel: token);
        if (!_isCurrent(epoch)) return; // a newer query started — drop this
        final phase = res.items.isEmpty
            ? (res.partial ? SearchPhase.partial : SearchPhase.empty)
            : (res.partial ? SearchPhase.partial : SearchPhase.success);
        state = state.copyWith(
          phase: phase, results: res.items, cursors: res.cursors,
          failedCategories: res.failedCategories, hasMore: false, // All: no infinite page here
        );
      } else {
        final page = await _service.category(category, q, cancel: token);
        if (!_isCurrent(epoch)) return;
        state = state.copyWith(
          phase: page.items.isEmpty ? SearchPhase.empty : SearchPhase.success,
          results: page.items,
          cursors: {category.wire: page.nextCursor},
          hasMore: page.hasMore,
        );
      }
    } on SearchCancelled {
      // superseded — ignore
    } catch (e) {
      if (!_isCurrent(epoch)) return; // stale error must not clobber a newer query
      state = state.copyWith(phase: _phaseFor(e)); // query + any results preserved
    }
  }

  /// Infinite scroll for a SPECIFIC category tab (All paginates per category via
  /// its own tab). Uses the category's own cursor; dedupes; a page failure
  /// preserves the already-loaded items.
  Future<void> loadMore() async {
    if (category == SearchCategory.all) return; // All is not infinitely paged here
    final cur = state.cursors[category.wire] ?? '';
    if (!state.hasMore || cur.isEmpty || state.phase == SearchPhase.loadingMore) return;

    final epoch = state.epoch; // same query
    final token = CancelToken();
    _inflight = token;
    state = state.copyWith(phase: SearchPhase.loadingMore);
    try {
      final page = await _service.category(category, state.query, cursor: cur, cancel: token);
      if (!_isCurrent(epoch)) return;
      state = state.appendDeduped(
        page.items,
        cursors: {category.wire: page.nextCursor},
        hasMore: page.hasMore,
        phase: SearchPhase.success,
      );
    } on SearchCancelled {
      // ignore
    } catch (_) {
      if (!_isCurrent(epoch)) return;
      // Preserve loaded items; surface pagination failure via a benign revert to
      // success (a discreet "tap to retry" footer is shown by the UI on !hasMore
      // errors). We keep hasMore so the user can retry.
      state = state.copyWith(phase: SearchPhase.success);
    }
  }

  bool _isCurrent(int epoch) => epoch == state.epoch;

  SearchPhase _phaseFor(Object e) {
    if (e is GatewayException) {
      if (e.isUnauthorized) return SearchPhase.unauthorized;
      if (e.statusCode == 503) return SearchPhase.unavailable;
      if (e.statusCode == 504) return SearchPhase.timeout;
      return SearchPhase.error;
    }
    if (e is TimeoutException) return SearchPhase.timeout;
    if (e is NetworkException) return SearchPhase.offline;
    return SearchPhase.error;
  }

  void _cancelInflight() {
    _inflight?.cancel('superseded');
    _inflight = null;
  }

  @override
  void dispose() {
    _timer?.cancel();
    _cancelInflight();
    super.dispose();
  }
}

/// One controller per category tab (family keyed by category).
final searchControllerProvider = StateNotifierProvider.autoDispose
    .family<SearchController, SearchState, SearchCategory>((ref, category) {
  final c = SearchController(ref.watch(searchServiceProvider), category);
  ref.keepAlive(); // survive brief tab rebuilds; disposed when the hub leaves
  return c;
});
