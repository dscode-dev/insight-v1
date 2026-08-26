# `CAUSAL_NORMALIZER_FIT_V1` — o ajuste sobre a referência

**PR:** 05.5.2 · **ADR:** [0039](../architecture/adr/0039-normalizer-fit-is-reference-only-and-evaluation-blind.md)
· depende de [ADR-0035](../architecture/adr/0035-feature-normalization-uses-competition-scoped-exact-median-iqr-artifacts.md)
e [ADR-0036](../architecture/adr/0036-snapshot-grid-is-live-comparable-and-the-split-is-temporal.md)

## A invariante

```
FitPopulation ⊆ REFERENCE                 por construção, e não por conferência
∂ ArtifactSet / ∂ EVALUATION  =  0
∂ Bundle(C)   / ∂ REFERENCE(C')  =  0     para todo C' ≠ C
```

Em palavras: **mexer na metade de AVALIAÇÃO não pode mudar NADA do ajuste**, e
mexer na referência de uma competição não pode mudar o que outra afirma.

A primeira linha é fácil. As outras duas são sobre IDENTIDADE, e o defeito que
elas impedem **não produz número errado nenhum**: ele destrói a capacidade de
AFIRMAR que nada mudou.

## O normalizador

```
key      competition_median_iqr_reference
version  1.0
method   MEDIAN_IQR
scope    COMPETITION
cutoff   BEFORE_INSTANT(reference_end_exclusive)
```

### Por que ele não é o `DEFAULT_V1_NORMALIZER`

Há **dois cortes causais diferentes**, e confundi-los produz ou um vazamento ou
um custo impossível:

| corte | o que é | custo |
|---|---|---|
| `BEFORE_EVALUATED_MATCH` | um ajuste POR partida avaliada | N ajustes para N partidas |
| `BEFORE_INSTANT` | UM ajuste, cortado na fronteira | um conjunto para o dataset |

O `DEFAULT_V1_NORMALIZER` (PR-05.1) declara o primeiro, e ele continua sendo o
contrato do caminho **ao vivo**: quando um jogo é avaliado em tempo real,
«antes desta partida» é conhecível e é o corte certo.

Este PR precisa do segundo, e a razão é a estrutura do dataset. A divisão já é
temporal e atômica por partida (ADR-0036): toda linha de REFERÊNCIA vem de uma
partida iniciada antes de `reference_end_exclusive`. Um corte nesse instante é
então **exatamente** a população de referência — nem uma linha a mais.

E ele é **mais conservador** que o primeiro, não menos:
`BEFORE_EVALUATED_MATCH` deixaria o ajuste da última partida da avaliação
enxergar as anteriores DA AVALIAÇÃO; o corte na fronteira não deixa nenhuma
linha de avaliação entrar em ajuste nenhum.

### A conferência que amarra as duas fronteiras

`assert_fit_boundary_matches_split` recusa um normalizador cujo corte não seja o
da divisão do dataset. As duas são independentes no código e têm de ser a mesma
no domínio: um normalizador cortado uma semana depois traria algumas partidas de
avaliação para dentro da escala, as medianas continuariam plausíveis, e a
invariância deixaria de valer **em silêncio**.

## As três impressões de referência

```
raw_content_fingerprint                       REFERÊNCIA + AVALIAÇÃO   ← linhagem
reference_content_fingerprint                 só REFERÊNCIA            ← identidade
competition_reference_content_fingerprint(C)  só REFERÊNCIA, só C      ← pacote
```

Elas são calculadas **durante a varredura do ajuste**, e não numa passagem
extra: o ajuste já lê exatamente as linhas de referência, então a identidade
delas sai de graça.

Algoritmo: `reference-content-sha256-ordered-v1`. É **ordenada** e RECUSA um
fluxo fora de ordem — uma impressão comutativa aceitaria duas linhas trocadas e
diria «igual», e permutação é um dos defeitos que ela existe para pegar.

### A ordem canônica é em dois níveis

```
1. as PARTIÇÕES, em ordem de (metade, competição, temporada)
2. as LINHAS, em ordem de chave DENTRO de cada partição
```

**Ela não é a ordem da chave**, e a diferença foi revelada pelo benchmark e não
pelo E2E — porque o E2E tem uma partição só. As partidas são identificadas por
`uuid5`, então as chaves de duas competições se **intercalam** no espaço de
identificadores: exigir chave globalmente crescente recusaria o fluxo que o
leitor de fato entrega.

O que a guarda (`PartitionOrderGuard`) continua pegando:

| defeito | como |
|---|---|
| linha repetida | a mesma chave duas vezes na mesma partição |
| linha fora de ordem | dentro de uma partição |
| partição revisitada | voltar a uma já fechada — duas leituras se misturando |
| partição fora de ordem | o leitor entregando `PREMIER` antes de `BRA_SERIE_A` |

## Onde a cegueira à avaliação vira código

Três lugares, e errar em qualquer um quebra a invariante sem produzir número
errado:

**1. `source_corpus_fingerprint` de cada artefato** = a impressão da referência
**daquela competição**. Essa escolha tira a avaliação e as outras competições da
identidade do artefato de uma vez só.

**2. `population_digest`** = a impressão das observações de referência daquela
competição naquele eixo, e nenhuma observação de avaliação entra nela.

**3. `fit_corpus_fingerprint` do normalizador fica VAZIO.** Ele é global, e um
valor global faria a referência da La Liga mudar os artefatos da Premier League.
A pergunta «este ajuste veio de qual dataset cru?» é respondida pelo
`NormalizerArtifactSet.lineage()`, num nível acima.

## A população de ajuste

```
DatasetFeaturePopulation      um eixo, uma competição, acumulado em fluxo
    array('d')                os valores disponíveis, 8 bytes cada
    contador de ausentes      as indisponíveis contam e não entram na distribuição
    SHA-256 em andamento      a impressão ordenada, algoritmo
                              `dataset-fit-population-sha256-ordered-v1`
```

**Ela RECUSA o que chega fora de ordem**, e a diferença para a
`FeaturePopulation` do PR-05.4 é deliberada. Aquela ORDENA o que recebe, porque
recebe um conjunto materializado e a ordem do banco não pode decidir a
identidade. Esta recusa, porque recebe um fluxo cuja ordem já é canônica — e
reordenar um fluxo exigiria materializá-lo. A recusa é mais forte que a
ordenação: a mesma observação duas vezes chega como `key <= última` e é
recusada (PR-05.4 §107).

**A exatidão não é negociada.** Os quantis continuam sendo os de tipo 7 sobre a
população inteira, em `Decimal`. O que foi comprimido é o ARMAZENAMENTO das
observações — não o método. Guardar 29 eixos × 45 mil linhas como
`FeatureObservation` custaria centenas de megabytes para responder às cinco
perguntas que o ajustador faz.

## Os três estados do artefato

| estado | quando | o que a célula recebe |
|---|---|---|
| `FITTED` | amostra suficiente e IQR > 0 | o número escalado |
| `INSUFFICIENT_SAMPLE` | menos de 30 observações disponíveis | `ARTIFACT_INSUFFICIENT_SAMPLES`, sem número |
| `DEGENERATE_SCALE` | IQR = 0 | `ARTIFACT_DEGENERATE_SCALE`, sem número |

E há um quarto caso, que não é do artefato e sim da ausência dele: uma
competição que aparece só na avaliação nunca teve população de referência, e as
linhas dela recebem `ARTIFACT_NOT_AVAILABLE_FOR_COMPETITION`.

**Nenhum deles cai para `PASS_THROUGH`.** Ver
[NORMALIZED_FEATURE_DATASET_V1](NORMALIZED_FEATURE_DATASET_V1.md).

## O ciclo de vida

```
DRAFT → BUILDING → VALIDATING → READY
  ↓        ↓            ↓
FAILED   FAILED       FAILED
```

O ajuste lê, calcula e grava numa chamada só — não há uma fase de construção
separada da de cálculo —, e por isso ele termina em `BUILDING`. A conferência
segue por `VALIDATING` até `READY`. O salto `DRAFT → READY` não existe, e a
ausência é o ponto.

**Um conjunto em `READY` não aceita artefato novo**, e a recusa é do
REPOSITÓRIO. Sem ela, toda versão normalizada publicada sobre ele passaria a
apontar para números diferentes dos que gravou.

## O que a conferência confere

| conferência | o que ela pega |
|---|---|
| a impressão fecha | os números no banco não são os que a produziram |
| o plano é o mesmo | um pacote ajustado sob outra classificação de eixos |
| a competição é a própria | um artefato da Premier no pacote da La Liga |
| a fronteira é a da divisão | o corte do ajuste depois da metade |
| `FITTED` tem IQR > 0 | uma divisão por zero esperando o momento |

## A leitura ao vivo (o que o PR-06 vai usar)

```python
bundle = await artifacts.bundle_of(set_id, competition="PREMIER")
```

Um acesso por chave, com 29 artefatos. Trazer o conjunto inteiro para normalizar
uma partida da Premier League traria as medianas de todas as ligas — e é por
isso que o pacote é uma tabela, e não um `GROUP BY`.
