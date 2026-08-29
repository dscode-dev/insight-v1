# Agregação de vizinhos — V1

> **A fronteira que este documento existe para manter:**
>
> ```
> RETRIEVAL     determina os vizinhos históricos exatos
> AGREGAÇÃO     atribui influência relativa, calcula N_eff, resume evidência
> INFERÊNCIA    interpreta a evidência histórica
> ```
>
> `retrieval ≠ agregação ≠ inferência`. O PR-06.5 implementa **só** a do meio.

## O fluxo

```
consulta de AVALIAÇÃO
        ↓
ProjectedExactStateRetriever  /  ProjectedExactTrajectoryRetriever   (PR-06.4)
        ↓
vizinhos EXATOS, com dissimilaridade e evidência
        ↓
aggregate_state  /  aggregate_trajectory
        ↓
vizinhança ponderada + N_eff + evidência agregada
```

A agregação recebe o resultado **pronto**. Ela não resolve universo de
candidatos, não carrega linhas de projeção, não lê PostgreSQL, não lê Parquet,
não lê MinIO, não recalcula trajetória e não recalcula distância exata.

### Zero leitura adicional — medido, e não afirmado

Uma vez que o resultado exato existe, a agregação causa:

```
leituras PostgreSQL       0
leituras Parquet          0
leituras MinIO            0
leituras de fato canônico 0
```

Isso é instrumentado no E2E com três contadores — proxy de pool, proxy do object
store e troca de `pq.ParquetFile` / `pq.read_table` — e vale para **todas** as
leituras derivadas do agregado, que entram no bloco medido de propósito: se
alguma delas disparasse acesso preguiçoso, o zero seria falso.

O E2E também prova que **o contador enxerga**. Um teste companheiro roda a
recuperação *dentro* do bloco e exige que o contador acuse. Sem ele, um
instrumento cego daria zero por não estar olhando, e o gate estaria «provado»
por um medidor quebrado.

## Os contratos

### `WeightedNeighbor`

```
identity              a identidade semântica, como o retrieval a nomeou
retrieval_rank        a posição no top-K EXATO, preservada e nunca recalculada
dissimilarity         a dissimilaridade EXATA
normalized_weight     a massa relativa — NÃO é probabilidade
evidence_fingerprint  a ponte para a evidência do retrieval
```

Ele **não carrega o payload inteiro**. Identidade, posição, distância e a
impressão da evidência bastam para auditar a massa; copiar o resto multiplicaria
memória por `K` sem acrescentar nada que a impressão já não amarre.

### `NeighborAggregation`

```
query_identity · kind · policy (+ impressão, + λ resolvido)
requested_k · neighbor_count
weighted_neighbors
status                      AGGREGATED | NO_NEIGHBORS
N_eff
weighted_mean_dissimilarity · minimum · maximum
max_neighbor_weight · top3_weight_mass
evidence_summary
retrieval_fingerprint · fingerprint
```

`neighbor_count` e `N_eff` são **grandezas separadas**, e a distinção é o
documento `EFFECTIVE_SAMPLE_SIZE_V1.md` inteiro.

## A ordem do top-K é preservada

Os pesos são um **atributo** dos vizinhos, e não um novo critério de ordenação.
O top-K já tem desempate determinístico decidido pelo retrieval; reordenar aqui
por peso produziria uma segunda ordem com autoridade ambígua. Quando a
concentração precisa ser lida em ordem de massa, isso acontece dentro de
`top_mass` — e não no resultado.

O construtor **recusa** uma entrada fora da ordem do top-K, e recusa identidade
repetida.

## A impressão

Ela amarra a **entrada e a política**, e não a saída:

```
tipo de recuperação
identidade da consulta
impressão da recuperação de origem
identidades dos vizinhos, em ordem
dissimilaridades exatas (pelo `repr` do float)
impressões de evidência
impressão da política de ponderação (que inclui λ)
K pedido
```

Os **pesos não entram**: eles são derivados por completo dos vizinhos, das
distâncias e da política. Incluí-los seria hashear duas vezes a mesma
informação, e esconder a dependência.

A impressão é idêntica sob execução repetida e sob permutação física da entrada.

### As três mutações, e o que cada uma muda

| muda | pesos | `N_eff` | impressão |
|---|---|---|---|
| só a **evidência** | não | não | do agregado sim (a evidência é entrada semântica) |
| a **distância** | sim | pode | sim |
| o **`λ`** da política | sim | pode | sim (a da política também) |

A primeira linha é a mais importante: **mudar a evidência sem mudar a distância
deixa a massa intacta**. É o teste que prova que a cobertura não é cobrada duas
vezes.

## A evidência agregada

Ela é **descritiva**, calculada *com* os pesos e nunca de volta para dentro
deles. A direção é uma só: **peso → resumo**.

**Estado** (evidência do PR-06.2): contagem de eixos do perfil, eixos
compartilhados mínimo e máximo, eixos e razão compartilhados ponderados, e a
parcela de penalidade ponderada.

**Trajetória** (evidência do PR-06.3): tamanho do espaço de células, células
compartilhadas mínimo e máximo, células e razão ponderadas, horizontes
compartilhados ponderados, e os eixos compartilhados ponderados **por horizonte**
— `1m`, `3m`, `5m`.

O resumo por horizonte é o que a trajetória tem de próprio: dois conjuntos com o
mesmo `D_T` médio podem ter vindo de horizontes diferentes, e essa diferença é
sobre **quando** a comparação se sustenta.

### A média renormalizada, e por que ela existe

Quando só parte dos vizinhos tem um valor — `penalty_share` é `None` para quem
não compartilhou eixo nenhum —, os pesos deles não somam um. Usar a soma parcial
como denominador implícito daria uma média puxada para baixo por vizinhos que
nem entraram na conta. A média é renormalizada sobre os pares que têm parcela, e
responde à pergunta certa: «entre os que têm, qual é a média ponderada?».

O par `(parcela, peso)` é montado **junto**, e nunca fatiado depois — filtrar só
a lista de valores e cortar os pesos pelo comprimento pegaria os *primeiros* n
pesos, que são de outros vizinhos, e a média sairia plausível sobre pares que
não se correspondem.

## O prefixo de K

Agregar os primeiros dez de um top-20 **renormaliza**: o denominador de `K = 10`
é a soma de dez termos, e o de `K = 20` é a de vinte. Exigir
`p_i(K=10) = p_i(K=20)` seria exigir que o conjunto não importasse.

O que sobrevive ao corte é a **razão** entre vizinhos comuns, que é onde o
núcleo vive.

## A CLI

```
engine retrieval aggregate-state       <dataset_version> <match#idx> [--k N] [--lambda L]
engine retrieval aggregate-trajectory  <dataset_version> <match#idx> [--k N] [--lambda L]
```

Ela passa pela composição e pelos casos de uso — **nunca** por um adapter — e
imprime a política resolvida, o `λ`, a impressão da política, `N_eff`, a
dissimilaridade média ponderada, o peso máximo, a massa dos três maiores, a
tabela de vizinhos e o resumo de evidência.

O vocabulário é guardado por teste: nenhum rótulo de saída pode chamar o peso de
probabilidade, chance ou confiança. `NO_NEIGHBORS` é dito explicitamente, e não
desenhado como uma tabela vazia.
