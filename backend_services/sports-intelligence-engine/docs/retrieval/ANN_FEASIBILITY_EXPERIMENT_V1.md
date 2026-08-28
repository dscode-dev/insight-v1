# ANN histórico — experimento de viabilidade, e por que ele foi adiado

**PR:** 06.4 · **Resultado:** `DEFERRED BY EVIDENCE` · **Data:** 2026-08-27

> Este documento registra um experimento **concluído com resultado negativo
> útil**. O ANN não foi adotado, e a razão não é que a implementação falhou —
> é que a medição mostrou que ele não se justifica para a forma do problema.

## A pergunta

Os PRs 06.1, 06.2 e 06.3 produziram três oráculos exatos e exaustivos. Eles
varrem todo o `CandidateUniverse`, e o custo medido era:

```
estado exato       p50 ≈  33,5 ms
trajetória exata   p50 ≈ 364,2 ms
```

A hipótese natural: gerar candidatos por ANN (pgvector + HNSW), reduzir o
universo a uma lista curta, e reordenar com a distância exata.

## O que foi construído e medido

Tudo o que a hipótese exigia, até o fim:

```
proxy [value, mask]        58 dimensões (estado), 174 (trajetória)
pgvector 0.8.6             HNSW, vector_l2_ops, m=16, ef_construction=64
iterative_scan             strict_order — verificado, e usado
harness sintético          50.000 linhas, 5 competições × 10 instantes
                           universo alvo 1.000, seletividade 2,00 %
decomposição de erro       ProxyCandidateRecall / ANNProxyRecall / E2ERecall
varredura                  K ∈ {5,10,20} × B ∈ {2K…50K} × ef ∈ {40…640}
                           100 queries, semente 20260827
```

## Resultado 1 — o teto da representação

`ProxyCandidateRecall@B` mede se o proxy consegue trazer o top-K **semântico**
para dentro do orçamento, olhando o universo inteiro. É o **teto** do ANN: o
HNSW não pode recuperar o que o vetor não ordena para perto.

Com `K = 10`:

| B | B/U | ProxyCandidateRecall | E2ERecall | set match |
|--:|--:|--:|--:|--:|
| 50 | 0,050 | 0,6410 | 0,6410 | 0,070 |
| 100 | 0,100 | 0,7770 | 0,7770 | 0,220 |
| 200 | 0,200 | 0,8930 | 0,8930 | 0,500 |
| 500 | 0,501 | 0,9880 | 0,9860 | 0,880 |

O portão exigia `0,995`. **Ele só é aproximado com metade do universo na lista
curta** — o dobro do teto de poda aceitável. Uma lista curta que contém metade
do universo não é uma lista curta.

## Resultado 2 — o HNSW não era o problema

`ANNProxyRecall` ficou entre **0,9984 e 0,9990** em toda a varredura, sob filtro
de 2 %, com zero subpreenchimento. E `E2ERecall` acompanhou
`ProxyCandidateRecall` em todas as células.

**Toda a perda entrava antes do índice.** Um número de recall único teria lido
como «o ANN está ruim» e mandado ajustar `ef_search` — que já estava perfeito. A
decomposição em três perdas é o que evitou o diagnóstico errado.

## Resultado 3 — o planejador não escolhe HNSW nesta escala

O plano real da consulta filtrada, com 50.000 linhas físicas e universo de 1.000:

```
Limit → Sort (top-N heapsort)
  → Index Scan using ..._u   (B-tree: competition, period, minute, stoppage, tie_break)
     rows=998
```

**Sem HNSW.** O PostgreSQL prefere buscar as 998 linhas pelo B-tree e ordenar.
O ponto de virada foi medido:

| universo | escolha do planejador | p50 |
|--:|---|--:|
| 250 | B-tree + ordenação | 0,30 ms |
| 1.000 | B-tree + ordenação | 0,35 ms |
| 5.000 | HNSW | 0,70 ms |
| 20.000 | HNSW | 1,93 ms |
| 50.000 | HNSW | 4,21 ms |

## A conclusão

O `CandidateUniverse` é **pequeno por construção**: uma competição num instante
EXATO da grade. No corpus real ele tem **~47 candidatos**. Abaixo de alguns
milhares o planejador declina o HNSW, e ordenar mil vetores custa 0,35 ms.

E os 33,5 ms do estado exato **não são cálculo de distância** — quarenta e sete
distâncias sobre quinze eixos não custam isso. São a AQUISIÇÃO das
representações: baixar Parquet do MinIO, abrir, projetar, materializar.

> **Não se aproxima o que já é barato calcular. Move-se o dado para perto do
> cálculo.**

Foi essa leitura que reorientou o PR-06.4 para uma **projeção exata em
PostgreSQL**, sem aproximação nenhuma.

## Formulação honesta do resultado

O que **não** se pode dizer:

- ~~«HNSW falhou»~~ — ele teve fidelidade de 0,999 contra o próprio teto.
- ~~«o proxy `[value,mask]` é inútil»~~ — ele correlaciona **+0,93** com
  `D_state`; só não o bastante para o envelope de poda exigido.

O que se pode dizer:

> O ANN não se justifica operacionalmente para a distribuição atual de
> `CandidateUniverse`, e o proxy V1 não preserva o top-K semântico sob o
> orçamento de poda especificado.

## Um defeito de harness, e o que ele ensina

A primeira execução mediu `ProxyCandidateRecall` entre 0,31 e 0,63 e teria
produzido um blocker de representação. **Era defeito do harness.**

Ele sorteava disponibilidade por linha nos 29 eixos canônicos, enquanto
`D_state` roda sobre os 15 eixos do perfil resolvido — 14 dimensões de ruído
puro no L2 que a semântica nunca olha. Na produção isso não existe: o perfil é
por COMPETIÇÃO, e um eixo sem artefato `FITTED` está indisponível em **toda**
linha dela, com valor e máscara constantes em zero, invisíveis ao L2.

Corrigido o modelo, com a mesma semente:

| | correlação com `D_state` | top-10 exato dentro do top-50 do proxy |
|---|--:|--:|
| harness com disponibilidade por linha | +0,5902 | 3/10 |
| harness com perfil por competição | **+0,9316** | **9/10** |

A lição não é sobre ANN: **um harness que não modela a forma real do dado
produz um veredito confiante e errado.**

## Quando reconsiderar — `ANN_REEVALUATION_TRIGGER_V1`

O ANN volta à mesa quando **medições de produção** mostrarem `CandidateUniverse`
alcançando rotineiramente a escala de **alguns milhares** de candidatos, ou
quando alguma política de recuperação futura ampliar materialmente o universo.

O `5.000` medido aqui é o ponto de virada **deste ambiente e desta forma de
consulta**, e não uma constante universal. Ele é ponto de partida para a próxima
medição, não um limiar a ser citado sem remedir.
