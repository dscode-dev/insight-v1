# AZTECA-SEARCH-UX-RESTORE — Comparação Visual

| Elemento | Aprovado (089b34a^) | Pós-SEARCH-V1 (regressão) | Restaurado (agora) |
|---|---|---|---|
| AppBar | "Explorar" | TextField genérico no título | **"Explorar"** ✓ |
| Campo de busca | filled ds.subtle, radius lg, prefixo search, hint "Buscar partidas, clubes, agentes…", limpar | input genérico no AppBar | **estilo aprovado restaurado** ✓ + comportamento SEARCH-V1 |
| Hero "Radar da rodada" | presente → R.radar | removido | **restaurado** ✓ |
| Seção "Descobrir" (grid 2×2) | Clubes/Agentes/Discussões/Sinais (navegação real) | removida | **restaurada** ✓ |
| Seção "Tendências" | 3 linhas HARDCODED (fabricadas) | removida | **NÃO reintroduzida** (era mock/trending falso) — slot ocupado por "Buscas recentes" reais |
| Query vazia | Discovery completo | só "Buscas recentes" (tela cheia) | **Discovery completo** ✓ |
| Query preenchida | _NoResultsYet (stub) | tabs+resultados | **tabs+resultados reais** ✓ (mantido) |
| Buscas recentes | não existia | tela inteira | **seção na densidade aprovada** (card+borda radius md) |

## Regressões corrigidas
Hero, grid Descobrir, identidade "Explorar", campo estilizado — todos recuperados via Git.

## Preservado da SEARCH-V1 (sem regressão funcional)
tabs por capabilities, 6 cards tipados, deep links validados, debounce/cancel/out-of-order, cursores por
categoria, dedupe, partial, histórico Gateway, estados offline/timeout/unauthorized/unavailable/empty,
ausência de Teams/Players/Trending.

## Evidência
Testes: `search_ux_restore_test.dart` (5) verificam hero+grid na query vazia, Tendências fabricadas ausentes,
troca para Results na query, retorno ao Discovery ao limpar, campo aprovado. Screenshots manuais no SMOKE.
