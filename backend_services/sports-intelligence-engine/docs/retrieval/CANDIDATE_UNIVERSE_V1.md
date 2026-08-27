# `SAME_COMPETITION_REFERENCE_EXACT_TIMEPOINT_V1` — o universo de candidatos

**PR:** 06.1 · **ADR:** [0041](../architecture/adr/0041-reference-only-same-competition-candidate-universe.md)

## A equação

```
Candidates(q) = { c ∈ REFERENCE :
                    Competition(c) = Competition(q)
                  ∧ TimePoint(c)   = TimePoint(q)
                  ∧ Match(c)      ≠ Match(q) }
```

Quatro condições, e cada uma impede um vazamento diferente.

| condição | o que ela impede |
|---|---|
| `c ∈ REFERENCE` | um candidato medido por uma escala que ele calibrou |
| mesma competição | comparar desvios de distribuições diferentes |
| mesmo instante | a diferença de relógio virar a maior parcela da distância |
| partida diferente | um candidato a distância zero por construção |

## Os campos da política

```
name                    SAME_COMPETITION_REFERENCE_EXACT_TIMEPOINT_V1
version                 1
query_split             EVALUATION
candidate_split         REFERENCE
competition_scope       SAME_COMPETITION
time_alignment          EXACT_MATCH_TIME_POINT_V1
same_match_policy       EXCLUDE
source_version_policy   SAME_NORMALIZED_DATASET_VERSION
candidate_sampling      NONE
candidate_cap           None
```

**`candidate_cap` é `None`, e não «ilimitado por engano».** Um teto truncaria o
universo antes das distâncias, e o resultado deixaria de ser o top-K verdadeiro
sem que nada no objeto denunciasse.

**`CandidateSampling` tem um membro só.** O catálogo existe assim mesmo porque a
amostragem é a forma mais natural de um oráculo deixar de ser exato — e um campo
ausente não poderia ser conferido por guarda nem entrar na impressão.

**`CompetitionScope.CROSS_COMPETITION` existe no catálogo e é RECUSADO pelo
construtor.** Mesma decisão do `NormalizationScope.GLOBAL` no PR-05.1: nomeá-lo
é o que permite recusá-lo com mensagem, em vez de não ter como expressá-lo.

## O alinhamento temporal

`EXACT_MATCH_TIME_POINT_V1`. Um candidato precisa ocupar exatamente a mesma
posição de jogo que a query.

```
query PRE_MATCH        →  candidatos PRE_MATCH, e mais nada
query FIRST_HALF 30    →  candidatos FIRST_HALF 30 — nem 29, nem 31,
                          nem SECOND_HALF 30
query EXTRA_TIME_FIRST 95  →  candidatos no mesmo ponto de prorrogação
```

### As quatro componentes, e as duas que a grade fixa

`MatchTimePoint` tem fase, minuto, acréscimo e desempate. A
`SnapshotGridPolicy` constrói todo corte intra-jogo com
`FeatureAsOf.at(match_id, period, minute)`: **acréscimo é sempre `0` e não há
sequência de desempate**.

Isso não é simplificação desta política — é o que a grade é. E as duas
componentes são **reconstruídas e conferidas**, não descartadas: um corte com
acréscimo chegando deste dataset é defeito a montante, e `GridTimePoint` para
com mensagem em vez de tratar «45» e «45+3» como o mesmo instante.

### O que NÃO existe

Janela de ±1 ou ±5 minutos, tolerância dinâmica, «mesma fase basta»,
alinhamento de trajetória, DTW. Uma janela traria de volta a pergunta que o
alinhamento exato evita: **quanto vale o deslocamento de relógio dentro da
distância?** Ela não é respondível hoje.

E há um efeito colateral que a janela teria: minutos adjacentes da mesma partida
são quase idênticos entre si, então o top-K viraria «os cinco minutos vizinhos
do mesmo jogo».

## A impressão do universo

Ela cobre:

```
algoritmo                       candidate-universe-sha256-v1
policy_fingerprint
competition
position                        as quatro componentes temporais
query_key
candidatos                      (chave, digesto), em ordem canônica
reference_content_fingerprint   a impressão da REFERÊNCIA normalizada
```

E **não** cobre chave de objeto, id de banco, ordem de iteração nem carimbo de
tempo. Sem isso, «acrescentar uma partida à avaliação não muda o universo» seria
indemonstrável: bastaria o escritor fechar um Parquet noutro lugar para a
impressão mudar.

**A referência que entra é a de REFERÊNCIA, e nunca a global.** A global cobre
as duas metades: usá-la faria uma partida acrescentada à avaliação mudar a
impressão do universo sem que candidato nenhum mudasse.

**A chave da query entra**, e é deliberado: o universo é *daquela* query. Duas
queries no mesmo instante da mesma competição resolvem o mesmo conjunto — menos
a exclusão da própria partida, que é justamente o que difere entre elas.

**As contagens de inelegibilidade NÃO entram.** Elas dependem do perfil, e o
universo é anterior ao perfil: o mesmo universo sob dois perfis tem atrições
diferentes e continua sendo o mesmo universo.

## A ordem: um conjunto, e não um fluxo

A impressão ordena as identidades antes de fechar. Isso é **diferente** do
dataset normalizado, onde a impressão é de fluxo e recusa a inversão — e a
diferença tem motivo:

```
dataset normalizado   a ordem física é parte do que se quer provar
universo de candidatos  é um CONJUNTO: duas varreduras em ordens
                        diferentes viram o mesmo universo
```

O que o acumulador **recusa** é a repetição: a mesma linha admitida duas vezes
apareceria em dobro no top-K, e a causa mais provável seria uma partição lida
duas vezes.

## Como o universo é lido

```
normalized/{dataset}/{versão}/split=REFERENCE/competition={liga}/season=*/
```

`split=` e `competition=` estão no **caminho**, então o leitor nunca abre a
metade de avaliação nem as outras ligas. O instante é coluna, e vai como
predicado sobre o lote lido.

Isso não é otimização: um filtro em memória sobre `split` funcionaria e faria a
correção do universo depender de um `if` — e um `if` esquecido produziria
candidatos de avaliação com o ranking parecendo normal.

**E o retriever confere de novo**, mesmo com a poda já feita. Defesa em
profundidade: a poda é do adaptador, e um adaptador novo entregaria candidatos
errados sem que nada denunciasse.

## As duas invariantes

```
∂ CandidateUniverse   / ∂ EVALUATION_outra  =  0
∂ CandidateUniverse_A / ∂ REFERENCE_B       =  0    para A ≠ B
```

A primeira vale por construção — a poda é por metade, e a impressão usa a
referência. A segunda também: a poda é por competição, e a impressão não carrega
agregado global nenhum.

## O tamanho do universo

Com a grade produzindo **uma linha por partida por minuto**, o universo de um
instante numa competição tem o tamanho do número de partidas de referência
daquela liga — centenas, e não milhões.

Isso é consequência direta do alinhamento exato, e é o que torna a varredura
exaustiva viável. Uma janela de ±1 minuto multiplicaria esse número por três.
