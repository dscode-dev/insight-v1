# AZTECA-SEARCH-UX-RESTORE — Arquitetura Final

## Composição (Explore é a superfície; Search é uma capacidade dentro dela)
```
SearchScreen (rota /search inalterada)
 ├── AppBar "Explorar"
 ├── _ExploreSearchField          (estilo aprovado: filled ds.subtle, radius lg, prefixo, hint, limpar)
 └── query.trim().length >= 2 ?
        _SearchResultsContent      → capabilities → tabs → _CategoryResults (FEATURE-SEARCH-V1)
      : _DiscoveryContent          → _HeroCard(Radar) + grid Descobrir + RecentSearchesSection (real)
```
Campo FIXO no topo do corpo (Column) ⇒ Discovery↔Results troca só o conteúdo abaixo, sem salto de layout,
sem perder foco/teclado/query.

## Fluxo de dados (inalterado — a regra da SEARCH-V1)
```
UI Composition → Search State → SearchController → SearchService → Gateway
```
Widgets nunca tocam Dio. Discovery nunca toca fixtures. `RecentSearchesSection` lê `searchHistoryProvider`
(Gateway, fonte única).

## Separação de responsabilidades
- **Composição visual**: `search_screen.dart` (_ExploreSearchField, _DiscoveryContent + _HeroCard +
  _DiscoveryCard, _SearchResultsContent + _Tabs + _CategoryResults) e `widgets/search_history.dart`
  (RecentSearchesSection + _RecentRow) e `widgets/result_cards.dart` (6 cards tipados).
- **Lógica de busca**: intacta em `state/` + `data/` + `model/` + `navigation/` — nenhum arquivo desses
  foi tocado neste hotfix.

## O que mudou (somente 2 arquivos de produção)
- `search_screen.dart` — reescrito para restaurar a Explore e compor Search dentro (não mais um Search Hub
  monolítico).
- `widgets/search_history.dart` — de tela cheia (`SearchHistoryView`) para seção (`RecentSearchesSection`).
Tudo o mais da FEATURE-SEARCH-V1 permanece byte-idêntico.

## Regra permanente estabelecida
Uma feature nova integra-se à experiência aprovada; não a apaga/simplifica/degrada para facilitar sua
implementação técnica.
