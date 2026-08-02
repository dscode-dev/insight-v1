# AZTECA-SEARCH-UX-RESTORE — Validação

Flutter-only. Nenhum backend alterado (confirmado: `git status --porcelain` em insight-social internal/cmd/
migrations = 0; insight-gateway internal/cmd = 0).

| Comando | Resultado |
|---|---|
| flutter analyze | **No issues found** |
| flutter test | **+120 / All tests passed** (era 115 → +5 do restore) |
| git diff --check | limpo |

## Testes novos (`test/search_ux_restore_test.dart`, 5)
1. query vazia renderiza Discovery aprovado (hero "Radar da rodada" + grid Descobrir + buscas recentes reais);
2. Tendências FABRICADAS ausentes (sem "Under 2.5"/"Tipsters em alta"/"12 comunidades ativas");
3. query → Results com tabs de capabilities; Teams/Players ocultos; Discovery sai de cena;
4. limpar query → volta ao Discovery (layout não se perde);
5. campo aprovado (hint + prefixo) integrado ao corpo.

## Suítes SEARCH-V1 preservadas
search_models_test (8) + search_controller_test (5) inalteradas e verdes. Nenhuma capacidade regrediu.

## Arquivos de produção alterados (2)
- `lib/features/search/search_screen.dart` — restaura Explore + compõe Search dentro.
- `lib/features/search/widgets/search_history.dart` — histórico de tela cheia → seção.
Todo o resto de `lib/features/search/` (state/data/model/navigation/result_cards) byte-idêntico.
