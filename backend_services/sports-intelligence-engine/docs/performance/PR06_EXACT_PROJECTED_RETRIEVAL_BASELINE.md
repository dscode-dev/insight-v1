# Baseline da recuperação projetada exata

**PR:** 06.4 · **Execução oficial:** revisão final, isolada, `EXIT=0`

> **AUTORIDADE.** Só os números desta página valem. As execuções anteriores —
> a de 8 candidatos e as do experimento ANN — estão explicitamente
> DESCARTADAS e não aparecem aqui como referência de desempenho.

## 1. O que este baseline mede

O caminho **projetado** contra o **oráculo Parquet**, mesma query set, ordem
ALTERNADA por query, condição **morna** declarada e igual para os dois.

O gate semântico já provou igualdade exata; aqui só se mede custo.

## 2. O insumo (fora da conta)

```
partidas                96
projeção STATE          4.277 linhas em 0,4 s
projeção TRAJETÓRIA     4.136 linhas em 3,1 s
universo p50            47 candidatos
queries                 60   (trajetória medida em 53)
                             1 não aplicável, 6 recusadas
```

## 3. ESTADO

```
Parquet     p50  33,54   p95  36,34   p99  37,97 ms
projetado   p50  26,12   p95  28,28   p99  29,62 ms

total speedup            1,28x
query-side (comum)      18,03 ms
candidate-side Parquet  15,51 ms
candidate-side projeção  8,09 ms

CANDIDATE SPEEDUP        1,92x     gate >= 1,5x   PASSA
teto de Amdahl           1,86x
  lookup 6,19 · decode 0,36 · cálculo 1,36 ms
```

## 4. TRAJETÓRIA

```
Parquet     p50  53,63   p95  56,34   p99  57,75 ms
projetado   p50  45,11   p95  49,12   p99  50,77 ms

total speedup            1,19x
query-side (comum)      31,57 ms
candidate-side Parquet  22,06 ms
candidate-side projeção 13,54 ms

CANDIDATE SPEEDUP        1,63x     gate >= 1,5x   PASSA
teto de Amdahl           1,70x
  lookup 6,65 · decode 2,73 · cálculo 4,26 ms
```

**O denominador foi REMEDIDO nesta revisão**, como manda o contrato. O baseline
histórico do PR-06.3 registrou `p50 ≈ 364,2 ms` para trajetória exata, medido
com outro arnês — 109 queries, instrumentação própria, e sem o `resolve`
cronometrado à parte. Os dois números não se comparam diretamente, e é por isso
que o oficial é o desta página.

## 5. Aquisição eliminada

```
Parquet   objetos lidos   2
projeção  objetos lidos   1     só a QUERY
projeção  consultas SQL   1     nunca uma por candidato
```

Plano real, sem forçar nada:

```
Index Scan using hspr_universo_idx  (actual time=0,027..0,061  rows=47)
  Index Cond: (projection_version_id, competition, period, minute, stoppage, tie_break)
  Filter: (match_id <> ...)
```

## 6. O gate de 2x foi aposentado — e por quê

O critério original exigia `2x` de ponta a ponta. Ele foi retirado como
**DEFEITO DE ESPECIFICAÇÃO**, e não relaxado por conveniência. A aritmética:

```
ESTADO      total Parquet 33,54 ms
            query-side    18,03 ms   ← este PR não pode tocar

            teto com custo de candidato ZERO
            = 33,54 / 18,03 = 1,86x  <  2x
```

O alvo exigia otimizar trabalho fora do escopo do PR. O critério passou a medir
o que o PR muda:

```
candidate-side  >= 1,5x
total p50/p95   estritamente menor
```

**O histórico fica registrado.** O gate de 2x existiu; não foi 1,5x desde
sempre.

## 7. A dívida medida — `QUERY_REPRESENTATION_PARQUET_IO`

```
ESTADO       18,03 ms de 26,12 ms projetados   69%
TRAJETÓRIA   31,57 ms de 45,11 ms projetados   70%
```

A leitura da linha de AVALIAÇÃO do Parquet é hoje o custo dominante nos dois
caminhos projetados. Ela está **fora do escopo do PR-06.4** por decisão
explícita: projetá-la apenas para melhorar o benchmark seria otimizar para a
métrica. Pertence ao caminho de serving/live-state futuro.
