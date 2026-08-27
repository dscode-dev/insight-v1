# `MINIMUM_EVIDENCE_COVERAGE_V1` — quanta evidência é evidência bastante

**PR:** 06.2 · **ADR:** [0043](../architecture/adr/0043-explicit-shared-coverage-eligibility.md)

## Os três conjuntos

Sobre o perfil resolvido `A`, com `m = |A|`:

```
Q = { i ∈ A : q_i utilizável }          |Q| = eixos que a QUERY tem
C = { i ∈ A : c_i utilizável }          |C| = eixos que o CANDIDATO tem
S = Q ∩ C                                s  = eixos COMPARTILHADOS
u = m - s                                     eixos não compartilhados
```

«Utilizável» são três condições, e as três são necessárias:

```
disponibilidade = AVAILABLE     a normalização afirma que o número existe
valor presente                  ele está lá
valor finito                    e é um número
```

**Qualquer inconsistência entre os três PARA a varredura.** Uma célula que se
declara `AVAILABLE` sem número finito — ou que se declara indisponível e traz um
número — é o dataset normalizado contradizendo a si mesmo, e não uma ausência.
Tratá-la como ausência esconderia um invariante quebrado atrás de uma penalidade
que parece normal.

**E nada de valor cru.** Se o valor normalizado não existe, o eixo está ausente.
Buscar o cru, o canônico ou o do provedor traria um número de outra grandeza
para dentro de uma soma de desvios robustos.

## As máscaras

São **tuplas ordenadas pelo perfil**, e não conjuntos de nomes:

```
perfil    (xg_home_10m, xg_away_10m, xg_diff_10m, ctx_home, ctx_away, ctx_diff)
query      1  1  1  1  1  1        →  "111111"
candidato  1  1  1  0  0  0        →  "111000"
comum      1  1  1  0  0  0        →  "111000"     s = 3
```

Três motivos, e o terceiro decide:

```
posição     a posição i da máscara é o eixo i do perfil, que é o eixo i da soma
tamanho     um perfil de cem eixos são cem caracteres, e não cem cadeias
impressão   um `set[str]` serializado depende da ordem de iteração de um dict;
            um texto posicional não depende de nada
```

## Os quatro números de cobertura

```
Coverage_query        |Q| / m
Coverage_candidate    |C| / m
Coverage_shared       |S| / m        ← a AUTORIDADE
Coverage_shared|query |S| / |Q|      ← evidência, e não substitui a anterior
```

**O denominador da autoridade é o PERFIL.** Com denominador variável, um
candidato com duas dimensões teria `2/2 = 100 %` e pareceria tão bem sustentado
quanto um com vinte.

**A cobertura relativa à query não substitui a do perfil**, e o caso que mostra
isso é curto: um par com `m = 20`, `|Q| = 4`, `|S| = 4` tem **100 %** do que a
query tem e **20 %** do perfil. É o piso do perfil que decide.

`Coverage_shared|query` é `None` quando `|Q| = 0` — zero seria um valor legítimo
de uma razão que não existe.

## O piso

```
minimum_profile_axes          4
minimum_query_available_axes  4
minimum_shared_axes           4
query_coverage_floor          3/5
shared_coverage_floor         3/5
```

```
admits_query(Q)  ⟺  |Q| ≥ 4  ∧  5|Q| ≥ 3m
admits_pair(S)   ⟺   s  ≥ 4  ∧   5s  ≥ 3m
```

### Os dois pisos são ambos necessários

| caso | absoluto | relativo | resultado |
|---|---|---|---|
| `m = 4`, `s = 3` | recusa | admite (15 ≥ 12) | **recusado** |
| `m = 20`, `s = 4` | admite | recusa (20 < 60) | **recusado** |
| `m = 10`, `s = 6` | admite | admite (30 = 30) | admitido, **no piso** |
| `m = 15`, `s = 8` | admite | recusa (40 < 45) | **recusado** |

### A aritmética é INTEIRA

```
5 * s >= 3 * m
```

**E a justificativa fácil é falsa.** «`0.6` não existe em `float64`, logo a
comparação erra na fronteira» — não erra. Medido: para todo `(s, m)` com `m` até
duzentos mil, em três formulações naturais e sobre quatro pisos, o resultado em
ponto flutuante coincide com o exato **em todos os casos**. Na fronteira, `s/m` e
`3/5` são a mesma razão e arredondam para o mesmo `float64`.

O motivo verdadeiro é de contrato: a comparação inteira é exata **por
construção** e não precisa desse argumento; a versão em `float` é correta sob
uma propriedade do arredondamento que teria de ser reestabelecida a cada
mudança. A medição virou teste, e ele vive ao lado da implementação.

## As três recusas

| motivo | quem | quando |
|---|---|---|
| `PROFILE_INSUFFICIENT_EVIDENCE_AXES` | a COMPETIÇÃO | `m < 4` |
| `QUERY_INSUFFICIENT_COVERAGE` | a QUERY | `|Q|` abaixo do piso |
| `INSUFFICIENT_SHARED_COVERAGE` | o CANDIDATO | `s` abaixo do piso |

**As duas primeiras são exceções tipadas; a terceira é uma contagem.** A
diferença é o que se faz com elas: a query recusada não tem resposta, e o
candidato recusado é parte da atrição que este PR existe para medir.

**A recusa da query vem ANTES da leitura dos candidatos** — medido: ela custa
1 objeto e 182.591 bytes contra 2 objetos e 353.510 da varredura completa. Isso
não saiu de graça: a primeira versão avaliava `candidates=await ...` como
argumento e pagava o universo inteiro antes de recusar. Ver o baseline.

**O piso não cede.** Se a competição tem `m < 4`, ela é recusada inteira — não se
baixa o mínimo até ela caber.

## A atrição, aberta em três

```
coverage_eligible      recebeu distância
coverage_ineligible    no universo, abaixo do piso — NORMAL, e é o produto
structural_ineligible  mesma partida, representação divergente — NÃO deveria
```

**A ordem das perguntas é parte do contrato.** O estrutural é perguntado antes
da cobertura: um candidato da mesma partida contado como «sem cobertura»
inflaria o número que este PR existe para medir com um defeito de integridade.

E a soma das três é **exatamente** `universe_count` — conferido no construtor do
resultado. Uma diferença ali é candidato perdido pela varredura.

## O que não mudou

```
CandidateUniverse_PR06.1  ==  CandidateUniverse_PR06.2
ResolvedAxes(CompleteCase) == ResolvedAxes(AvailabilityAware)
```

A política de candidatos, o alinhamento temporal, a exclusão da própria partida,
a ausência de amostragem e a exaustividade são os do
[ADR-0041](../architecture/adr/0041-reference-only-same-competition-candidate-universe.md).
Os dois caminhos leem o universo pelo **mesmo código** — `resolve_base` e
`candidates` —, e é isso que torna a igualdade verdadeira por construção.
