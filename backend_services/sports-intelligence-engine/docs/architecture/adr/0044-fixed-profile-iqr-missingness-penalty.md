# ADR-0044 — A ausência é penalizada em unidade de IQR², sobre denominador fixo

**Status:** aceito · **Data:** 2026-08-27

## Contexto

O [ADR-0043](0043-explicit-shared-coverage-eligibility.md) decidiu **quem** pode
ser comparado quando falta dimensão. Falta decidir **quanto vale** a dimensão
que faltou.

Há três respostas erradas, e todas as três produzem números plausíveis:

**Imputar.** Preencher o eixo ausente com zero, com a média, com o valor
anterior. Num espaço robusto zero é a **mediana da competição** — imputá-lo
afirma «este estado era típico», que é uma afirmação forte sobre um dado que não
existe, e deixa o candidato incompleto artificialmente PERTO de qualquer query
mediana.

**Ignorar de graça.** Somar só o que é compartilhado e dividir pelo que sobrou.
Um candidato que compartilha duas dimensões e acerta as duas teria média zero e
ganharia de um que compartilha vinte e erra pouco em uma.

**Penalizar por um número inventado.** `λ = 0,3`, `λ = 5`. Sem unidade, o número
não significa nada — e sem rótulo de verdade não há como calibrá-lo.

Formalmente, o que precisa valer é:

```
MISSING ≠ 0
MISSING ≠ EXACT_MATCH
MISSING ≠ IGNORE_FOR_FREE
```

## Decisão

```
              Σ_{i∈S} (qᵢ - cᵢ)²   +   p·(m - s)
D_AA(q,c) =  ───────────────────────────────────        p = 1
                            m
```

Nome:

```
AVAILABILITY_AWARE_FIXED_PROFILE_IQR_PENALTY_V1
```

### 1. O denominador é `m`, e nunca `s`

```
FIXED_PROFILE_DENOMINATOR_V1
```

Esta é a decisão central, e ela é a que impede a segunda resposta errada. Com o
perfil no divisor, **o que falta continua na conta**: a ausência não some por ter
sumido do numerador.

```
denominador fixo    dois candidatos com coberturas diferentes produzem
                    números na MESMA escala, e comparar os dois significa
                    alguma coisa
denominador móvel   cada candidato mede uma grandeza diferente
```

Há guarda arquitetural que lê a expressão: a divisão na propriedade `value` é
por `profile_axis_count`, e `shared_count` não aparece ali. Trocar o denominador
é uma edição de uma palavra que não quebra nenhum tipo e muda o significado
inteiro do número.

`observed_mse = Σ_S δ² / s` **existe** e divide por `s` de propósito — ele é
diagnóstico, responde «quão parecidos eles são no que dá para comparar?», e
nunca é o ranking.

### 2. A penalidade é `p = 1`, em unidade de IQR²

```
MISSING_AXIS_PENALTY_SQUARED_IQR_V1
```

O nome carrega a **unidade**, porque «penalidade = 1» sem unidade não significa
nada — um por cento, um gol e um IQR são todos «1».

Os eixos robustos estão em `(x − mediana) / IQR`, então uma diferença de `1` é
uma diferença de um IQR da competição. Cobrar `1` por eixo desconhecido diz:

> não sei o que havia aqui, e trato isso como se houvesse uma discrepância
> de um IQR

E `p = 1` é o ponto em que a troca entre evidência e incerteza é **neutra na
unidade em que os eixos vivem**. Quando um eixo ausente passa a ser observado, a
contribuição dele deixa de ser `1` e passa a ser `δ²`:

```
|δ| < 1     o candidato MELHORA — a evidência era favorável
|δ| = 1     empate exato com a incerteza
|δ| > 1     o candidato PIORA — a evidência era desfavorável
```

**O terceiro caso não é defeito, e não é para ser evitado.** Descobrir que dois
estados diferem em dois IQRs num eixo é informação, e ela tem de valer mais que
a suposição que ocupava aquele lugar. Uma penalidade alta demais tornaria o
desconhecido sempre pior que qualquer evidência; uma baixa demais, sempre
melhor.

**Sem epsilon, sem suavização, sem penalidade por feature, sem penalidade por
família, sem penalidade aprendida.** E `p` NÃO foi escolhido testando cem
lambdas: não há rótulo de verdade com que medir qual é «melhor», e o que sairia
de um otimizador seria o valor que maximiza uma métrica inventada.

### 3. Dois ausentes não são um acordo

Se query e candidato não têm o eixo, ele **não é compartilhado** e recebe a
penalidade igual. Dois desconhecidos coincidirem não é evidência de igualdade —
é ausência de evidência, e a conta trata as duas do mesmo jeito.

### 4. Nada de valor cru

Se o valor normalizado não existe, o eixo está ausente. Não se busca o valor
cru, o canônico, o do provedor nem o da linha anterior: qualquer um deles
traria um número de **outra grandeza** para dentro de uma soma de desvios
robustos, e ele pareceria um vizinho próximo por acidente de escala.

### 5. Falha fechada na contradição

Uma célula que se declara `AVAILABLE` e não traz número finito — ou que se
declara indisponível e traz um número — **para a varredura**
(`AVAILABILITY_VALUE_INCONSISTENCY`). O dataset normalizado garante
`AVAILABLE ⟺ valor finito presente` na escrita (ADR-0040); uma linha que viola
isso foi escrita por outro caminho ou corrompida depois.

> Isto é mais estrito que o PR-06.1, e a diferença é deliberada. Lá a ausência e
> a contradição caíam no mesmo `None`, porque o caso completo recusava o par de
> qualquer jeito. Aqui a contradição viraria **penalidade silenciosa**, e a
> atrição medida sairia inflada por um defeito de escrita.

### 6. Pesos iguais, e a mesma semântica de `float`

Sem alfa, beta, gama, peso por família ou peso aprendido — ponderação é do
PR-06.5. A soma usa `IEEE754_FLOAT64_FSUM_V1`, a MESMA do PR-06.1: inventar
outra tornaria os dois números incomparáveis por um motivo que não tem nada a
ver com ausência.

### 7. A ordem do top-K

```
1. dissimilaridade        ASC
2. eixos compartilhados   DESC
3. chave canônica         ASC
```

**A cobertura desempata, e não lidera.** Ordenar por cobertura primeiro faria um
candidato completamente diferente com 100 % de cobertura ganhar necessariamente
de um quase idêntico com 95 % — e cobertura viraria prioridade absoluta em vez
de evidência. Ela já está DENTRO do número, pela penalidade; usá-la de novo como
primeiro critério a contaria duas vezes.

**Mas ela desempata antes da chave**: com o mesmo `D`, quem o produziu com mais
eixos observados o sustenta com mais evidência. A chave entra por último, e só
para que o resultado seja reproduzível quando os dois primeiros empatam.

## Consequências

**A equivalência com o PR-06.1 vale exatamente, e é testada.** Quando `s = m`:

```
D_AA = d²_PR06.1 / m       logo   Ranking_AA|completos = Ranking_PR06.1
```

Há teste de propriedade sobre trinta candidatos completos misturados a parciais,
e teste E2E sobre o dataset real: a ordem relativa do subconjunto completo é a
mesma nos dois, e cada número é exatamente `d²/m`.

**Isto NÃO é uma métrica, e o nome diz isso.** Um vetor incompleto comparado
consigo mesmo tem dissimilaridade **positiva**:

```
D_AA(x, x) = u/m > 0     quando x tem eixo ausente
```

Isso viola a identidade dos indiscerníveis, e basta para que nenhuma
propriedade métrica possa ser assumida — inclusive as que ninguém testou. O
método `incomplete_self_dissimilarity` existe para que essa afirmação seja
citável, e `is_metric` devolve `False`.

O que vale e está testado: não-negatividade, simetria dada a mesma máscara, e
`D(x,x) = 0` quando `x` é completo.

**As três parcelas são preservadas separadamente.** `D = 0,4` pode ser
discrepância pura sobre o perfil inteiro ou incerteza pura sobre metade dele, e
as duas coisas dizem coisas opostas sobre o vizinho. `NeighborEvidence` carrega
`observed_squared_sum`, `missing_penalty_sum`, `observed_mse`, `penalty_share` e
as três máscaras — e há teste de que **todo** vizinho reconstrói o próprio
número a partir delas.

**`PenaltyShare` é evidência, e não confiança.** Convertê-la em
`confiança = 0,82` é do PR-06.7, e há guarda arquitetural contra o vocabulário.

**Este número também não é a similaridade final do Insight.** Ponderação é do
PR-06.5; trajetória, do PR-06.3.

## Alternativas descartadas

**Imputar zero.** Descrito no contexto. Há teste-sentinela em que a imputação
mudaria o ranking, e ele prova que a implementação não a faz.

**Denominador na interseção.** Ver §1.

**Penalidade aprendida ou por família.** Sem rótulo, não há o que aprender.

**Penalidade por feature.** Exigiria decidir que um eixo ausente «custa mais»
que outro — outra decisão sem dado que a sustente hoje.

**Raiz quadrada.** Mesmo argumento do ADR-0042: monotônica, ranking idêntico,
custo sem ganho.
