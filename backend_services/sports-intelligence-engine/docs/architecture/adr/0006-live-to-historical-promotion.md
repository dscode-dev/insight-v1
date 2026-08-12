# ADR-0006 — Promoção de ao vivo para histórico

**Status:** aceito · **Data:** 2026-08-12

## Contexto

Dados históricos públicos são finitos, de qualidade desigual e frequentemente
restritos por licença. Provedores comerciais custam caro em volume.

Ao mesmo tempo, o motor observa partidas ao vivo com granularidade que nenhum
arquivo público tem.

## Decisão

Toda partida processada ao vivo vira dataset histórico proprietário
(`INSIGHT_NATIVE`), por um caminho explícito:

```
LIVE → FINISHED_PENDING_RECONCILIATION → RECONCILED
     → HISTORICAL_PENDING_BUILD → HISTORICAL_ACTIVE
```

- **Reconciliação** confere o fluxo ao vivo contra as fontes definitivas.
  O fluxo tem buracos; o arquivo não.
- **Build** constrói features e vetores a partir dos fatos fechados.
- **Promoção** é o único momento em que a partida passa a alimentar retrieval.

`INSIGHT_NATIVE` tem a maior precedência (foi observado por nós, com os quatro
carimbos que nós mesmos produzimos) e licença sem restrição.

## Consequências

**Ganhamos:** o histórico cresce sozinho com granularidade própria, e a
dependência de fonte externa cai com o tempo.

**Pagamos:** reconciliação é trabalho real, e a base fica correta apenas na
medida em que ela funciona.

## Alternativas consideradas

**Promover direto do fluxo ao vivo.** Rejeitado: o fluxo perde eventos, e um
histórico com buracos silenciosos é pior que um histórico menor.

**Só comprar histórico.** Rejeitado: custo, e o dado comprado tem a
granularidade de quem vendeu.

