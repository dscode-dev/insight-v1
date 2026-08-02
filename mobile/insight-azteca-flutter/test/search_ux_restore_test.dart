// AZTECA-SEARCH-UX-RESTORE — composição Explore+Search:
// query vazia→Discovery aprovado; query→Results reais; clear→Discovery;
// Tendências fabricadas NÃO reintroduzidas; capabilities→tabs preservado.
// ignore_for_file: prefer_const_literals_to_create_immutables, prefer_const_constructors
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:azteca/features/search/data/search_service.dart';
import 'package:azteca/features/search/model/search_models.dart';
import 'package:azteca/features/search/search_screen.dart';
import 'package:azteca/theme/theme.dart';

class _FakeService extends SearchService {
  _FakeService() : super(Dio());

  @override
  Future<SearchCapabilities> capabilities({CancelToken? cancel}) async =>
      SearchCapabilities.fromJson({
        'enabled': ['users', 'agents', 'communities', 'competitions', 'matches', 'posts'],
        'blocked': {'teams': 'BLOCKED_BY_DOMAIN', 'players': 'BLOCKED_BY_DOMAIN'},
        'trending': 'UNAVAILABLE',
      });

  @override
  Future<SearchAllResult> all(String query, {CancelToken? cancel}) async =>
      SearchAllResult(
        items: [
          SearchCard(entityType: 'user', entityId: 'u1', deepLink: '/users/u1',
              data: const {'id': 'u1', 'username': 'neymar', 'display_name': 'Ney',
                'initials': 'NE'}),
        ],
        cursors: const {}, partial: false, failedCategories: const [],
      );

  @override
  Future<SearchPage> category(SearchCategory category, String query,
          {String? cursor, int? limit, CancelToken? cancel}) async =>
      const SearchPage(items: [], nextCursor: '');

  @override
  Future<List<SearchHistoryItem>> history({CancelToken? cancel}) async =>
      const [SearchHistoryItem('flamengo', '2026-01-01T00:00:00Z')];

  @override
  Future<void> clearHistory({CancelToken? cancel}) async {}
}

Future<void> _pump(WidgetTester tester) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [searchServiceProvider.overrideWithValue(_FakeService())],
    child: MaterialApp(
      theme: insightTheme(Brightness.light),
      home: const SearchScreen(),
    ),
  ));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

void main() {
  testWidgets('query vazia renderiza o Discovery APROVADO (hero + grid)',
      (tester) async {
    await _pump(tester);
    // Identidade da Explore restaurada.
    expect(find.text('Explorar'), findsOneWidget);
    expect(find.text('Radar da rodada'), findsOneWidget); // hero
    expect(find.text('Descobrir'), findsOneWidget); // seção grid
    expect(find.text('Clubes'), findsOneWidget);
    expect(find.text('Agentes'), findsOneWidget);
    expect(find.text('Discussões'), findsOneWidget);
    expect(find.text('Sinais'), findsOneWidget);
    // Buscas recentes reais integradas como seção.
    expect(find.text('Buscas recentes'), findsOneWidget);
    expect(find.text('flamengo'), findsOneWidget);
  });

  testWidgets('Tendências FABRICADAS não foram reintroduzidas', (tester) async {
    await _pump(tester);
    expect(find.text('Tendências'), findsNothing);
    expect(find.text('Under 2.5'), findsNothing);
    expect(find.text('Tipsters em alta'), findsNothing);
    expect(find.textContaining('12 comunidades ativas'), findsNothing);
  });

  testWidgets('query não vazia troca para Results (tabs de capabilities); Teams/Players ocultos',
      (tester) async {
    await _pump(tester);
    await tester.enterText(find.byType(TextField), 'ney');
    await tester.pump(const Duration(milliseconds: 400)); // debounce 300ms
    await tester.pump();
    // Tabs derivadas do backend.
    expect(find.text('Tudo'), findsOneWidget);
    expect(find.text('Pessoas'), findsOneWidget);
    // Nunca teams/players.
    expect(find.text('Times'), findsNothing);
    expect(find.text('Jogadores'), findsNothing);
    // Discovery saiu de cena (sem hero).
    expect(find.text('Radar da rodada'), findsNothing);
  });

  testWidgets('limpar a query retorna ao Discovery (layout não se perde)',
      (tester) async {
    await _pump(tester);
    await tester.enterText(find.byType(TextField), 'ney');
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('Radar da rodada'), findsNothing);

    // Limpar via botão.
    await tester.tap(find.byIcon(Icons.close_rounded));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Radar da rodada'), findsOneWidget); // Discovery de volta
    expect(find.text('Descobrir'), findsOneWidget);
  });

  testWidgets('campo de busca aprovado: hint + prefixo integrados ao corpo',
      (tester) async {
    await _pump(tester);
    expect(find.text('Buscar partidas, clubes, agentes…'), findsOneWidget);
    expect(find.byIcon(Icons.search_rounded), findsOneWidget);
  });
}
