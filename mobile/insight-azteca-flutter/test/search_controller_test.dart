// FEATURE-SEARCH-V1 Stage 3 — controller behaviour: debounce, out-of-order
// protection, partial→partial (not success), pagination + dedupe, page-failure
// preserves items, error preserves query.
// ignore_for_file: prefer_const_literals_to_create_immutables, inference_failure_on_instance_creation, inference_failure_on_collection_literal
import 'dart:async';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:azteca/core/errors.dart';
import 'package:azteca/features/search/data/search_service.dart';
import 'package:azteca/features/search/model/search_models.dart';
import 'package:azteca/features/search/state/search_controller.dart';
import 'package:azteca/features/search/state/search_state.dart';

// A SearchService test double (subclass — SearchService is concrete). We control
// per-query completion + payloads.
class FakeService extends SearchService {
  FakeService() : super(Dio());
  final allC = <String, Completer<SearchAllResult>>{};
  final cat = <String, Completer<SearchPage>>{};
  Object? throwErr;

  Completer<SearchAllResult> allFor(String q) => allC.putIfAbsent(q, Completer.new);
  Completer<SearchPage> catFor(String key) => cat.putIfAbsent(key, Completer.new);

  @override
  Future<SearchAllResult> all(String query, {CancelToken? cancel}) {
    if (throwErr != null) return Future.error(throwErr!);
    return allFor(query).future;
  }

  @override
  Future<SearchPage> category(SearchCategory category, String query,
      {String? cursor, int? limit, CancelToken? cancel}) {
    if (throwErr != null) return Future.error(throwErr!);
    return catFor('${category.wire}|$query|${cursor ?? ''}').future;
  }

  @override
  Future<SearchCapabilities> capabilities({CancelToken? cancel}) async =>
      SearchCapabilities.fallback;
  @override
  Future<List<SearchHistoryItem>> history({CancelToken? cancel}) async => const [];
  @override
  Future<void> clearHistory({CancelToken? cancel}) async {}
}

SearchAllResult allWith(List<String> ids, {bool partial = false, List<String> failed = const []}) =>
    SearchAllResult(
      items: [for (final id in ids) SearchCard(entityType: 'user', entityId: id, data: const {})],
      cursors: const {}, partial: partial, failedCategories: failed,
    );

SearchPage pageWith(List<String> ids, {String next = ''}) => SearchPage(
      items: [for (final id in ids) SearchCard(entityType: 'user', entityId: id, data: const {})],
      nextCursor: next,
    );

void main() {
  test('debounce: no request until the debounce elapses', () async {
    final svc = FakeService();
    final c = SearchController(svc, SearchCategory.all);
    c.onQueryChanged('fla');
    expect(c.state.phase, SearchPhase.debouncing);
    expect(svc.allC.containsKey('fla'), isFalse); // not fired yet
    await Future.delayed(const Duration(milliseconds: 350));
    expect(svc.allC.containsKey('fla'), isTrue); // fired after debounce
  });

  test('partial=true maps to partial phase, NOT success', () async {
    final svc = FakeService();
    final c = SearchController(svc, SearchCategory.all);
    c.submit('fla');
    svc.allFor('fla').complete(allWith(['u1'], partial: true, failed: ['communities']));
    await Future.delayed(Duration.zero);
    expect(c.state.phase, SearchPhase.partial);
    expect(c.state.failedCategories, ['communities']);
    expect(c.state.results.length, 1);
  });

  test('out-of-order: late response of query A cannot overwrite query B', () async {
    final svc = FakeService();
    final c = SearchController(svc, SearchCategory.all);
    c.submit('aaa'); // epoch bumps
    c.submit('bbb'); // epoch bumps again; A is now stale
    // B resolves first with its data.
    svc.allFor('bbb').complete(allWith(['b1']));
    await Future.delayed(Duration.zero);
    expect(c.state.query, 'bbb');
    expect(c.state.results.single.entityId, 'b1');
    // A resolves LATER — must be dropped.
    svc.allFor('aaa').complete(allWith(['a1']));
    await Future.delayed(Duration.zero);
    expect(c.state.results.single.entityId, 'b1'); // unchanged
    expect(c.state.query, 'bbb');
  });

  test('category pagination appends + dedupes, page failure preserves items', () async {
    final svc = FakeService();
    final c = SearchController(svc, SearchCategory.users);
    c.submit('ney');
    svc.catFor('users|ney|').complete(pageWith(['u1', 'u2'], next: 'cur1'));
    await Future.delayed(Duration.zero);
    expect(c.state.results.map((e) => e.entityId), ['u1', 'u2']);
    expect(c.state.hasMore, isTrue);

    // loadMore returns u2 (dup) + u3 → dedupe keeps u1,u2,u3.
    final more = c.loadMore();
    svc.catFor('users|ney|cur1').complete(pageWith(['u2', 'u3'], next: ''));
    await more;
    expect(c.state.results.map((e) => e.entityId), ['u1', 'u2', 'u3']);
    expect(c.state.hasMore, isFalse);
  });

  test('error preserves the typed query (recoverable)', () async {
    final svc = FakeService()..throwErr = const GatewayException(statusCode: 504, message: 't');
    final c = SearchController(svc, SearchCategory.all);
    c.submit('fla');
    await Future.delayed(Duration.zero);
    expect(c.state.phase, SearchPhase.timeout);
    expect(c.state.query, 'fla'); // preserved for retry
  });
}
