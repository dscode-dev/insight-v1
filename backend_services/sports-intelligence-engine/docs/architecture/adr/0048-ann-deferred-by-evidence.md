# ADR-0048 — ANN histórico adiado por evidência, e não por falha

**Estado:** aceito · **PR:** 06.4

## Contexto

A hipótese original do PR-06.4 era pgvector + HNSW gerando uma lista curta,
reordenada pela distância exata. Ela foi implementada por inteiro e medida
contra o oráculo.

## A medição

Arnês sintético: 50.000 linhas, 5 competições × 10 instantes, universo alvo
1.000, seletividade 2,00%, 100 queries, semente fixa.

```
K=10   B      B/U      ProxyRecall   ANNProxyRecall   E2E
       50     0,050    0,6410        0,9990           0,6410
      100     0,100    0,7770        0,9989           0,7770
      200     0,200    0,8930        0,9990           0,8930
      500     0,501    0,9880        0,9984           0,9860
```

Gate exigido: `0,995`. Ele só é aproximado com **metade do universo** na lista
curta — o dobro do teto de poda aceitável.

E o planejador não escolhe HNSW nesta escala:

```
   250 candidatos   B-tree + ordenação   0,30 ms
 1.000 candidatos   B-tree + ordenação   0,35 ms
 5.000 candidatos   HNSW                 0,70 ms
50.000 candidatos   HNSW                 4,21 ms
```

## Decisão

```
ANN HISTORICAL RETRIEVAL V1
STATUS: DEFERRED BY EVIDENCE
```

Não «falhou». `ANNProxyRecall` ficou em 0,999 — o HNSW recuperou quase
perfeitamente o que o proxy exaustivo teria escolhido. O que não alcançou o
gate foi o **teto da representação**, e o universo real é pequeno demais para
justificar aproximar.

Formulação correta:

> O ANN não se justifica operacionalmente para a distribuição atual de
> `CandidateUniverse`, e o proxy V1 `[value,mask]` não preserva o top-K
> semântico sob o envelope de poda especificado.

## Gatilho de reavaliação — `ANN_REEVALUATION_TRIGGER_V1`

Reconsiderar quando medições de PRODUÇÃO mostrarem `CandidateUniverse`
alcançando rotineiramente a casa dos milhares, ou quando alguma política de
recuperação futura ampliar materialmente o universo.

O `~5.000` medido é o ponto de virada **deste ambiente e desta consulta**, e
não uma constante universal.

## Consequência

`pgvector` foi removido como dependência de produção: nenhuma feature da V1
depende dele. A imagem do compose continua capaz de provê-lo — capacidade de
imagem não é dependência de aplicação.

O experimento inteiro está preservado em
`docs/retrieval/ANN_FEASIBILITY_EXPERIMENT_V1.md`.
