# ADR-0007 — Prevenção de vazamento histórico

**Status:** aceito · **Data:** 2026-08-12

## Contexto

Uma partida ao vivo consulta o índice histórico procurando situações
parecidas. Se ela — ou uma versão parcial dela — estiver nesse índice, ela
encontra a si mesma.

**O sintoma é bom.** A similaridade fica excelente, a concordância sobe, as
métricas melhoram. O sistema parece ótimo até enfrentar uma partida que nunca
viu.

## Decisão

Só partidas em `HISTORICAL_ACTIVE` podem alimentar retrieval histórico.

A regra vive em três lugares, de propósito:

1. `MatchLifecycle.can_feed_historical_index` — a definição;
2. `assert_can_feed_historical_index()` — a guarda chamável;
3. `MatchRepositoryPort.historical_candidates()` — o contrato do port já
   embute o filtro, para não depender de cada chamador lembrar.

Junto vai o **corte temporal**: só partidas anteriores ao instante da
consulta. Incluir o futuro é o mesmo vazamento por outra porta.

## Consequências

**Ganhamos:** o número que o motor reporta descreve capacidade real, e não a
si mesmo.

**Pagamos:** uma partida recém-terminada não está disponível para as
seguintes até completar reconciliação e build — latência deliberada.

## Alternativas consideradas

**Filtrar por id na consulta** (excluir a própria partida). Rejeitado: resolve
o caso trivial e não resolve estados parciais da mesma partida, nem partidas
posteriores ao corte.

**Confiar na consulta filtrar por estado.** Rejeitado: funciona até alguém
escrever a segunda consulta.

