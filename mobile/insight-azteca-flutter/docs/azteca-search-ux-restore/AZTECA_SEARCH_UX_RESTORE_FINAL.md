# AZTECA-SEARCH-UX-RESTORE — Relatório Final

## CODE READINESS: **READY**
## OPERATIONAL STATUS: **NOT_DEPLOYED — USER-OPERATED APP BUILD REQUIRED**

Hotfix de UX com preservação funcional: a página Explorar aprovada foi restaurada e a FEATURE-SEARCH-V1
permanece integralmente funcional, agora COMPOSTA dentro da Explore (não mais substituindo-a).

1. **Arquivos visuais sobrescritos pela Search**: apenas `search_screen.dart` (a Explore aprovada virou um
   Search Hub monolítico). `widgets/search_history.dart` tornara o histórico uma tela cheia.
2. **Componentes recuperados** (via Git, `089b34a^`): AppBar "Explorar", campo de busca estilizado no corpo,
   _HeroCard "Radar da rodada", seção "Descobrir" (grid 2×2 com navegação real).
3. **Estrutura Discovery restaurada**: hero + grid + "Buscas recentes" (dados reais do Gateway) no slot da
   antiga seção "Tendências".
4. **Estrutura Results preservada**: tabs por capabilities + 6 cards tipados + estados + deep links + toda a
   lógica (SearchController/Service/state) intacta.
5. **Integração Explore↔Search**: campo fixo no topo; query vazia→Discovery, query≥2→Results; transição sem
   salto de layout, sem perder foco/query.
6. **Mocks removidos/evitados**: a antiga "Tendências" era trending FABRICADO (linhas hardcoded) — NÃO foi
   reintroduzida. Nenhum mock novo. Discovery usa navegação real + histórico real.
7. **Estado e navegação**: retorno de detalhe preserva query/tab/scroll (SearchController via
   `ref.keepAlive()`); limpar cancela request + volta ao Discovery.
8. **Backend inalterado**: insight-social e insight-gateway = 0 arquivos alterados. social 0.1.11 /
   gateway 0.1.16 inalterados.
9. **Testes**: flutter analyze limpo; flutter test **120 passed** (+5 do restore); diff limpo.
10. **Build necessário**: somente Flutter.
11. **Limitações**: golden tests não adicionados (sem infra golden confiável no repo) — cobertura por testes
    comportamentais + checklist visual manual (SMOKE).

## Regra permanente estabelecida
Uma feature nova integra-se à experiência aprovada; não a apaga, simplifica ou degrada para facilitar sua
implementação técnica.
