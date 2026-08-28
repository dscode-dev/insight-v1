# ADR-0049 — O critério de desempenho mede o que o PR pode mudar

**Estado:** aceito · **PR:** 06.4

## Contexto

O critério de aceitação do PR-06.4 exigia:

```
projected total p50 <= 0,5 x Parquet total p50      (2x de ponta a ponta)
```

A implementação entregou `1,30x` e o gate reprovou. A investigação mostrou que
o alvo era inalcançável **por aritmética**, e não por qualidade de execução.

## A prova

Medido, com o `resolve` cronometrado à parte:

```
ESTADO
  total Parquet          33,54 ms
  query-side (comum)     18,03 ms    ← fora do escopo do PR
  candidate-side         15,51 ms    ← o que o PR muda

  teto com candidate-side = 0
  = 33,54 / 18,03
  = 1,86x   <  2x
```

Mesmo eliminando **inteiramente** o custo do candidato, o alvo de 2x não seria
atingido. O critério media trabalho que o PR não tinha permissão de tocar.

## Decisão

Classificar como:

```
SPECIFICATION / ACCEPTANCE-CRITERION DEFECT

NÃO:  implementation defect
NÃO:  projection defect
NÃO:  performance regression
```

E substituir por critérios alinhados ao escopo:

```
Gate C   candidate-side speedup   >= 1,5x
Gate D   total p50 e p95          estritamente menores
```

## O que NÃO foi feito

O gate **não foi ajustado ao resultado**. O `1,5x` foi congelado antes de a
trajetória ser medida, e a trajetória veio em `1,63x` — passou por margem, e
teria reprovado em `1,4x`.

E a alternativa tentadora foi recusada: projetar também a linha de AVALIAÇÃO
faria o número subir e seria otimizar para a métrica. Ela está registrada como
dívida, não resolvida.

## Resultado sob os novos critérios

```
ESTADO       candidate-side 1,92x    p50 26,12 < 33,54    p95 28,28 < 36,34
TRAJETÓRIA   candidate-side 1,63x    p50 45,11 < 53,63    p95 49,12 < 56,34
```

## Registro histórico

O gate de 2x **existiu**. Esta ADR não o apaga: ela documenta por que ele era
inconsistente com o escopo, e o substitui declaradamente.
