# `AVAILABILITY_AWARE_FIXED_PROFILE_IQR_PENALTY_V1` — a dissimilaridade

**PR:** 06.2 · **ADR:** [0044](../architecture/adr/0044-fixed-profile-iqr-missingness-penalty.md)

> **ISTO NÃO É A SIMILARIDADE FINAL DO INSIGHT.** O perfil se chama
> `ROBUST_AVAILABILITY_AWARE_EXACT_V1` e `is_diagnostic` devolve `True`:
> ponderação é do PR-06.5, trajetória é do PR-06.3, e confiança é do PR-06.7.

## A fórmula

```
              Σ_{i∈S} (qᵢ - cᵢ)²   +   p·(m - s)
D_AA(q,c) =  ───────────────────────────────────        p = 1
                            m
```

Três decisões, e cada uma impede uma fraude diferente.

## 1. O denominador é `m`, e nunca `s`

Com `s` no denominador, um candidato que compartilha duas dimensões e acerta as
duas teria média zero e ganharia de um que compartilha vinte e erra pouco em
uma. Com o perfil no divisor, **o que falta continua na conta**.

```
denominador fixo    dois candidatos com coberturas diferentes produzem
                    números na MESMA escala
denominador móvel   cada candidato mede uma grandeza diferente
```

`observed_mse = Σ_S δ² / s` existe e divide por `s` **de propósito** — ele
responde «quão parecidos eles são no que dá para comparar?». É diagnóstico, e
nunca o ranking. Um candidato com MSE baixíssimo sobre quatro eixos de vinte é
exatamente o caso que o denominador fixo existe para não premiar.

Há guarda arquitetural sobre a expressão da propriedade `value`.

## 2. A penalidade é `1`, em unidade de IQR²

Os eixos robustos estão em `(x − mediana) / IQR`, então uma diferença de `1` é um
IQR da competição. Cobrar `1` por eixo desconhecido diz:

> não sei o que havia aqui, e trato isso como se houvesse uma discrepância
> de um IQR

**Isso não é preencher com zero.** Zero é a MEDIANA da competição; imputá-lo
afirmaria que o estado ausente era típico, e deixaria o candidato incompleto
artificialmente PERTO de qualquer query mediana. A penalidade faz o contrário:
empurra para longe.

### Evidência real substitui incerteza — e pode piorar

Quando um eixo ausente passa a ser observado, a contribuição muda de `1` para
`δ²`:

```
|δ| < 1     o candidato MELHORA        a evidência era favorável
|δ| = 1     empate exato
|δ| > 1     o candidato PIORA          a evidência era desfavorável
```

O terceiro caso **não é defeito**. Descobrir que dois estados diferem em dois
IQRs num eixo é informação, e ela tem de valer mais que a suposição que ocupava
aquele lugar. `p = 1` é o ponto em que a troca é neutra na unidade em que os
eixos vivem.

Há teste para os três casos.

## 3. Dois ausentes não são um acordo

Se query e candidato não têm o eixo, ele não é compartilhado e recebe a
penalidade igual. Dois desconhecidos coincidirem é **ausência de evidência**, e
não evidência de igualdade.

## Os goldens

Com `m = 5` e `q = [0,0,0,0,0]`:

| candidato | `s` | observado | incerteza | `D` |
|---|---|---|---|---|
| `[0,0,0,–,–]` | 3 | 0 | 2 | **0,4** |
| `[0,0,0,0,–]` | 4 | 0 | 1 | **0,2** |
| `[1,1,1,1,1]` | 5 | 5 | 0 | **1,0** |
| `[1,2,0,–,–]` | 3 | 5 | 2 | **1,4** |
| `[1,2,0,0,–]` | 4 | 5 | 1 | **1,2** |

> **Uma ressalva sobre a primeira e a quarta linhas.** Elas são a aritmética dos
> §141 e §144 da especificação, e o §141 as anota como «elegível exatamente no
> limiar». Com `m = 5`, `s = 3` NÃO é elegível: o §21 fixa o mínimo absoluto em
> quatro eixos e o §88 diz por extenso `shared_count = 3 → ineligible`. A
> implementação segue o §21 e o §88 — eles são normativos, concordam entre si, e
> o §186 lista «below-floor candidate receiving distance» como blocker. A conta
> das duas linhas está verificada direto na definição de distância, que não
> decide elegibilidade.

## O que ela NÃO é

### Não é métrica

```
vale        D ≥ 0 · D(q,c) = D(c,q) · D(x,x) = 0 quando x é COMPLETO
NÃO vale    D(x,x) = 0 quando x é INCOMPLETO
```

`D_AA(x, x) = u/m > 0`: a incerteza dos eixos que `x` não tem continua na conta.
Isso viola a identidade dos indiscerníveis, e basta para que **nenhuma**
propriedade métrica possa ser assumida — inclusive as que ninguém testou.

`incomplete_self_dissimilarity(s)` existe para que a afirmação seja citável, e
`is_metric` devolve `False`.

### Não tem pesos, epsilon nem confiança

Sem alfa, beta, gama, peso por família ou peso aprendido — ponderação é do
PR-06.5. Sem epsilon, sem suavização, sem penalidade por feature ou por família.
`PenaltyShare` é evidência; convertê-la em `confiança = 0,82` é do PR-06.7.

### Não usa valor cru

Se o valor normalizado não existe, o eixo está ausente. Ponto.

### Não inventou semântica numérica

`IEEE754_FLOAT64_FSUM_V1`, a MESMA do PR-06.1 — inventar outra tornaria os dois
números incomparáveis por um motivo que não tem nada a ver com ausência.

## A equivalência com o oráculo

Quando `s = m`:

```
D_AA = d²_PR06.1 / m       logo   Ranking_AA|completos = Ranking_PR06.1
```

Testado por propriedade sobre trinta candidatos completos misturados a parciais,
e por E2E sobre o dataset real: a ordem relativa do subconjunto completo é a
mesma nos dois, e cada número é exatamente `d²/m`.

**É por isso que os dois oráculos coexistem.** Sem o de caso completo
executável, «a política de ausência mudou o quê?» não teria contra o que ser
medido — e a comparação `CompareExactRetrievalPolicies` roda os dois sobre a
MESMA leitura do universo, na mesma execução.

## A ordem do top-K

```
1. dissimilaridade        ASC
2. eixos compartilhados   DESC
3. chave canônica         ASC
```

**A cobertura desempata, e não lidera.** Ordenar por cobertura primeiro faria um
candidato completamente diferente com 100 % de cobertura ganhar necessariamente
de um quase idêntico com 95 %. Ela já está DENTRO do número, pela penalidade.

**Mas ela desempata antes da chave**: com o mesmo `D`, quem o produziu com mais
eixos observados o sustenta com mais evidência.

O heap inverte a tripla **inteira** — `(-D, s, chave descendente)` —, e cada
posição é invertida separadamente. Uma posição não invertida produz um top-K
correto em conteúdo e errado em ordem exatamente quando há empate no corte do
`K`; há dois testes de prefixo com empate deliberado ali, um para cada critério.

## Determinismo

| variação | teste |
|---|---|
| ordem de iteração | 10 permutações + ordem inversa |
| tamanho do lote | 1, 7, 128, 512, 2048, 4096 |
| layout do Parquet | duas execuções sobre o dataset real |
| `K` | prefixo, com empate no corte em `D` **e** em cobertura |
