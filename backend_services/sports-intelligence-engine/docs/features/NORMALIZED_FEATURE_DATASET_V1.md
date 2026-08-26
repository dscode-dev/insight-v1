# `NORMALIZED_FEATURE_DATASET_V1` — a representação normalizada

**PR:** 05.5.2 · **ADR:** [0040](../architecture/adr/0040-normalized-representation-is-an-immutable-independent-projection.md)
· depende de [NORMALIZATION_PLAN_V1](NORMALIZATION_PLAN_V1.md) e
[CAUSAL_NORMALIZER_FIT_V1](CAUSAL_NORMALIZER_FIT_V1.md)

## O que ele é

Uma **projeção independente** do dataset cru: as mesmas linhas, as mesmas 105
dimensões, na mesma ordem, com 29 delas reescaladas.

```
HistoricalFeatureDatasetVersion              os números como foram extraídos
    ├── NormalizedFeatureDatasetVersion      (plano P, artefatos A)
    └── NormalizedFeatureDatasetVersion      (plano P, artefatos A')
```

**Ele não é vetor, não é embedding, não é índice de similaridade.** O que muda é
a escala de 29 eixos.

## O contrato 1:1

**Para toda linha crua existe exatamente uma normalizada.** Nenhuma some — nem
quando o artefato é degenerado, nem quando a amostra foi insuficiente, nem
quando o valor de origem não existia. A ausência é sempre **local à célula**.

Ele é conferido em três lugares independentes:

| lugar | como |
|---|---|
| domínio | `__post_init__` recusa construir a versão |
| banco | `CHECK nfdv_um_para_um` recusa publicar |
| validação | conta contra o **rodapé do Parquet cru** |

A validação não usa a coluna do banco: a coluna diz o que a construção CONTOU, o
rodapé diz o que está lá, e a diferença entre os dois é exatamente o defeito que
ela procura.

## As duas famílias de disponibilidade

Confundi-las apaga a causa, e as duas exigem ações **opostas**.

```
source availability          por que o valor CRU não existe
normalization availability   por que a NORMALIZAÇÃO não produziu número
```

### O catálogo da normalização (fechado)

| estado | causa | ação |
|---|---|---|
| `AVAILABLE` | — | usar o número |
| `SOURCE_VALUE_UNAVAILABLE` | o cru não existia | ver a coluna de origem |
| `ARTIFACT_INSUFFICIENT_SAMPLES` | a competição não juntou 30 observações | esperar mais temporadas |
| `ARTIFACT_DEGENERATE_SCALE` | IQR nulo naquela competição | aceitar: aquela liga não tem dispersão ali |
| `ARTIFACT_NOT_AVAILABLE_FOR_COMPETITION` | a competição não tem pacote | ela aparece só na avaliação |

Um `market_1x2_home_median` sem cotação publicada é `NOT_DECLARED` na origem. O
**mesmo eixo** com cotação e IQR nulo é `ARTIFACT_DEGENERATE_SCALE` na
normalização. O primeiro manda procurar um provedor de dados; o segundo manda
aceitar a liga.

## Não há fallback, e a ausência é o ponto

Um eixo classificado `ROBUST` cujo artefato saiu `DEGENERATE_SCALE` **NÃO vira
`PASS_THROUGH`**.

Se virasse, a coluna teria unidades misturadas — gols normalizados numa
competição, gols crus na outra — e a distância entre duas partidas de ligas
diferentes seria calculada somando maçãs com laranjas, **sem que nada no arquivo
denunciasse**.

Também não há:

- epsilon (`max(iqr, 1e-6)` inventa uma escala onde não há)
- troca de método (média/desvio seria outro método, e método é identidade)
- imputação por zero (`missing → 0` produz média que soma perfeitamente e erra)
- clipping ou winsorização

E não há por guarda arquitetural, e não por disciplina: a estratégia de cada
célula vem do PLANO, e o teste `test_um_eixo_robusto_nunca_vira_pass_through_em_execucao`
recusa qualquer atribuição de estratégia em execução.

## A ordem das perguntas por célula

```
a origem tinha valor?        não → SOURCE_VALUE_UNAVAILABLE
o plano diz PASS_THROUGH?    sim → o MESMO float64, bit a bit
a competição tem pacote?     não → ARTIFACT_NOT_AVAILABLE_FOR_COMPETITION
o artefato ajustou?          não → ARTIFACT_INSUFFICIENT_SAMPLES
                                 ou ARTIFACT_DEGENERATE_SCALE
ajustou                      → (x - mediana) / IQR
```

**A primeira vem antes de todas**, e a ordem importa: um eixo sem valor cru numa
competição sem pacote tem duas causas verdadeiras, e a que interessa é a da
origem — procurar o artefato de uma feature que nunca teve valor é perseguir o
problema errado.

## O arquivo

Prefixo `normalized/`, particionado `split=/competition=/season=`, Parquet com
zstd. **330 colunas**: 15 de identidade e linhagem, mais três por eixo.

```
n_<chave>   o valor normalizado, float64, nulável
m_<chave>   por que a NORMALIZAÇÃO não produziu número, texto, nunca nulo
s_<chave>   por que o valor CRU não existia, texto, nunca nulo
```

**Todas as colunas de valor são `float64`, inclusive as dos `PASS_THROUGH`.** A
coluna precisa ter UM tipo, e ele não pode depender do resultado do ajuste — um
eixo degenerado em toda competição produziria uma coluna sem número nenhum, e
inferir o tipo do conteúdo faria o arquivo de uma competição discordar do da
outra. O valor continua exato: o caminho do `PASS_THROUGH` não atravessa
`Decimal`.

### As colunas de identidade

```
match_id, grid_index, grid_label, period, minute, split, competition, season
source_row_digest                  aponta para a linha crua PELO DIGESTO
representation_fingerprint         as quatro decisões, juntas
plan_fingerprint
artifact_set_fingerprint
competition_bundle_fingerprint     vazio quando a competição não tem pacote
available_count
row_digest
```

**A ligação com a linha crua é pelo digesto, e não pela posição.** Provar a
correspondência por posição exigiria que os dois datasets tivessem a mesma ordem
de arquivo, e a ordem de arquivo é decisão de execução.

**A linhagem do artefato é por LINHA, e não por célula.** Gravar 105 impressões
de artefato em cada uma das 91 mil linhas repetiria 91 mil vezes o mesmo mapa. A
linha carrega a impressão do PACOTE da competição; o manifesto abre o pacote.

## A travessia numérica

```
Dataset cru          float64    IEEE754_FLOAT64_EXACT_TO_DECIMAL_V1
    ↓ entrada
Ajuste               Decimal    mediana e IQR exatos
    ↓ saída
Dataset normalizado  float64    NORMALIZED_FLOAT64_V1  (12 casas no escalado)
```

A entrada é `Decimal.from_float` — o valor binário **exato** que o arquivo
guarda — e não `Decimal(str(x))`. O dataset cru já declarou `float64` como o
valor oficial da feature: o ajuste tem de normalizar o número que de fato está
no arquivo.

`NaN` e infinito são **recusados** nas duas pontas e no digesto. Um `Decimal`
gigante vira `inf` em `float`, e é o caso real: dividir por um IQR minúsculo
produz números enormes, e um `inf` gravado no Parquet seria lido como um valor.

## A identidade da representação

```
NormalizedFeatureRepresentationSpec
    space_fingerprint          quais eixos, em que ordem
    plan_fingerprint           qual eixo recebe qual transformação
    artifact_set_fingerprint   quais medianas e IQRs
    numeric_bridge             como o Decimal escalado virou float64
```

Trocar qualquer uma das quatro torna os números **incomparáveis**. Comparar uma
distância sob os artefatos A com outra sob A' é comparar centímetros com
polegadas: os dois números existem, os dois são plausíveis, e a comparação é
falsa.

O **id** do conjunto de artefatos NÃO entra na impressão, e a impressão dele
entra: dois ajustes independentes que chegam aos mesmos artefatos sobre a mesma
referência produzem a mesma representação com ids diferentes.

## As três impressões de conteúdo

```
normalized_content_fingerprint             tudo
normalized_reference_content_fingerprint   só REFERÊNCIA
normalized_evaluation_content_fingerprint  só AVALIAÇÃO
```

Acrescentar uma partida à avaliação muda a primeira e a terceira, e **não pode
mudar a segunda**. Sem a do meio sobraria a global — e ela mudaria, deixando
impossível afirmar que a base de comparação ficou igual.

As três são calculadas numa passagem, com o mesmo acumulador ordenado
(`normalized-content-sha256-ordered-v1`). Separá-las em três varreduras leria o
dataset três vezes para responder perguntas que a mesma linha responde.

**A ordem é a canônica de partição**, e não a da chave: partições em ordem de
`(metade, competição, temporada)`, chaves em ordem dentro de cada uma. É a ordem
em que o leitor entrega, e `split=EVALUATION` vem antes de `split=REFERENCE`
porque as chaves de objeto são ordenadas como texto. A validação restaura essa
mesma ordem antes de reconstruir — ordenar só pela chave reprovaria um dataset
correto de mais de uma partição.

**O digesto da linha usa os bytes IEEE-754**, e não texto: `repr(float)` já
mudou entre versões de Python, e a identidade de uma linha publicada não pode
depender da rotina de formatação do interpretador que a gravou.

## O ciclo de vida

```
DRAFT → BUILDING → VALIDATING → READY → SUPERSEDED
```

`create` congela a representação; `build` transforma e termina em `VALIDATING`;
`validate` relê o Parquet e reconstrói as três impressões; `publish` exige
motivo e grava o manifesto ao lado dos dados.

A validação **recalcula LENDO** o que a construção calculou ESCREVENDO. Reusar o
número da construção conferiria a construção contra ela mesma.

## O manifesto

Além do que o do dataset cru já respondia, ele responde:

| pergunta | onde |
|---|---|
| qual eixo foi transformado como | o `plan` inteiro, por extenso |
| com quais números | `artifact_map`: `(competição, eixo) → impressão do artefato` |
| o que ficou sem escala, e por quê | `availability.by_state` e `by_source_state` |
| é a mesma base de comparação? | `fingerprints.reference` |

O `artifact_map` cobre **só os eixos com artefato**. Os `PASS_THROUGH` não têm
artefato nenhum — inventar uma entrada vazia para eles faria o mapa insinuar que
houve um ajuste que não houve.

## A CLI

```
engine normalize fit <raw_version_id>
engine normalize validate-artifacts <artifact_set_id> --reason "..."
engine normalize create <raw_version_id> <artifact_set_id> --version 1.0
engine normalize build <version_id>
engine normalize validate <version_id>
engine normalize publish <version_id> --reason "..."
engine normalize show
```

**A fronteira não é pedida em comando nenhum.** Ela vem da versão crua, que já a
declarou na `spec`; perguntá-la de novo abriria a porta para um ajuste cortado
numa data diferente da divisão.
