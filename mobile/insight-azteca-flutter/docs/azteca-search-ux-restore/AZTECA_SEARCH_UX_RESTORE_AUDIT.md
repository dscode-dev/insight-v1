# AZTECA-SEARCH-UX-RESTORE — Stage 0 Audit (Git-evidence)

## Fonte da verdade
- Aprovado: `git show 089b34a^:lib/features/search/search_screen.dart` (321 linhas) — a Explore anterior.
- Atual: HEAD/working tree — o Search Hub do Stage 3 (271 linhas) que SOBRESCREVEU o arquivo.
- Arquivo sobrescrito: **apenas `lib/features/search/search_screen.dart`** (os demais arquivos da
  FEATURE-SEARCH-V1 são novos, não substituíram nada visual).

## Composição ANTERIOR (aprovada)
1. AppBar título **"Explorar"**.
2. **Campo de busca estilizado** DENTRO do corpo (padding xl/sm/xl/md): `filled` (ds.subtle), borda
   `InsightRadii.lg`, prefixo `search_rounded`, hint "Buscar partidas, clubes, agentes…", botão limpar,
   foco com borda `ds.signal` 1.4.
3. Query vazia → **_Discovery** (padding xl/sm/xl/xl5):
   - **_HeroCard "Radar da rodada"** ("Sinais, partidas quentes e leituras da comunidade") → `R.radar`;
   - seção **"Descobrir"** — GridView 2×2 de **_DiscoveryCard** (ds.subtle, radius lg): Clubes→R.hub,
     Agentes→R.agents, Discussões→R.hub, Sinais→R.radar (atalhos de navegação REAIS);
   - seção **"Tendências"** — 3 **_TrendRow** **HARDCODED**: "Brasileirão · 12 comunidades ativas",
     "Under 2.5 · sinais subindo", "Tipsters em alta · novas leituras hoje".
4. Query não vazia → `_NoResultsYet` (stub honesto da época).

## Composição ATUAL (regressão)
AppBar com TextField genérico no título; query vazia → SOMENTE "Buscas recentes" (SearchHistoryView em tela
cheia); query → tabs+resultados. **Hero, grid Descobrir e toda a identidade da Explore apagados.**

## Classificação das regressões
| Elemento | Classe | Decisão |
|---|---|---|
| AppBar "Explorar" | REGRESSÃO | RESTAURAR |
| Campo estilizado no corpo | REGRESSÃO (virou input genérico no AppBar) | RESTAURAR estilo/posição aprovados |
| _HeroCard Radar | REGRESSÃO · REAL (navegação) | RESTAURAR |
| Grid "Descobrir" (4 cards) | REGRESSÃO · REAL (navegação) | RESTAURAR |
| Seção "Tendências" (_TrendRow ×3) | **MOCK_REMOVIDO — trending fabricado** | **NÃO reintroduzir** (viola SEARCH-V1: "não invente trending"). Slot da hierarquia ocupado por seção REAL "Buscas recentes" (histórico do Gateway), mesma densidade visual |
| _NoResultsYet | substituído corretamente | resultados reais da SEARCH-V1 |
| Histórico em tela cheia | mudança indevida de hierarquia | vira SEÇÃO dentro do Discovery |

## O que a SEARCH-V1 entregou e DEVE ser preservado integralmente
SearchService/DTOs/SearchController (debounce 300ms, CancelToken, epoch out-of-order, cursores por
categoria, dedupe), capabilities→tabs, All, partial, histórico Gateway, estados
(offline/timeout/unauthorized/unavailable/empty/partial), deep links validados, 6 cards tipados, sem
Teams/Players/Trending. Nenhum backend muda.

## Plano de composição final
```
SearchScreen (rota inalterada)
 ├── AppBar "Explorar"
 ├── _ExploreSearchField (estilo aprovado, posição aprovada, comportamento SEARCH-V1)
 ├── query vazia  → _DiscoveryContent  (Hero + Descobrir grid + Buscas recentes [reais])
 └── query válida → _SearchResultsContent (tabs capabilities + resultados/estados SEARCH-V1)
```
Campo fixo no topo do corpo (mesmos paddings) ⇒ transição Discovery↔Results sem salto de layout.
