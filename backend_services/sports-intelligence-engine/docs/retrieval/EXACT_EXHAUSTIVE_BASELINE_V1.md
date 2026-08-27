# `ROBUST_COMPLETE_CASE_EXACT_BASELINE_V1` — o oráculo

**PR:** 06.1 · **ADR:** [0042](../architecture/adr/0042-exact-exhaustive-complete-case-retrieval-baseline.md)

> **ISTO É UM BASELINE DIAGNÓSTICO.** Não é a similaridade final do Insight, e
> o objeto diz isso: `RetrievalFeatureProfile.is_diagnostic` é consultável, e a
> CLI o imprime em toda saída. A distância de produção precisa decidir
> formalmente o que fazer com ausência, cobertura e evidência — e isso é o
> PR-06.2.

## Os eixos

O perfil resolvido de uma competição são os eixos que satisfazem **as duas**
condições:

```
estratégia no NormalizationPlan  =  ROBUST_MEDIAN_IQR_V1
artefato daquela competição      =  FITTED
```

### Por que só os robustos

Eles já estão em escala estatística comparável por competição —
`(x − mediana) / IQR` sobre a referência daquela liga. Os `PASS_THROUGH` não
passaram por escala nenhuma:

```
minute                    0 a 90     uma coordenada de relógio
corners_home_5m           0 a 3      uma contagem esparsa
market_1x2_home_support   0 a 12     quantas casas publicaram
xg_home_5m normalizado   −2 a +2     um desvio robusto
```

Somá-los na mesma distância faz o eixo de maior magnitude dominar, e o resultado
mede principalmente o relógio. **Isso não é uma escolha de similaridade — é um
acidente de unidade.**

### Por que só os `FITTED`

`DEGENERATE_SCALE` diz que aquela liga não tem dispersão naquele eixo;
`INSUFFICIENT_SAMPLE` diz que ela não juntou observações bastantes. Nos dois
casos **não existe escala**, e a célula sai vazia no dataset normalizado
(ADR-0035). Um eixo desses no perfil produziria uma coluna que nunca tem valor.

### E a causalidade sai de graça

O estado do artefato é decidido exclusivamente pela REFERÊNCIA (ADR-0039).
Mexer na avaliação não muda quem está `FITTED`, logo não muda o perfil resolvido
nem a impressão dele. Há teste de propriedade sobre isso.

### O casamento é por impressão, e não por nome

Duas versões da mesma feature têm a mesma chave e escalas diferentes. O perfil
confere a impressão da feature do plano contra a do artefato, e recusa a
divergência — casá-las por nome produziria uma distância entre grandezas
diferentes.

## A elegibilidade: caso completo

```
Coverage = 1   ⟹  distância calculada
Coverage < 1   ⟹  INCOMPLETE_PROFILE, e nenhuma distância
```

Não há imputação por zero, nem por média, nem penalidade, nem distância sobre a
interseção dos eixos, nem limiar de cobertura.

**Zero é a mediana da competição** num espaço robusto. Imputá-lo diria «este
estado é típico» — uma afirmação forte sobre um dado que não existe —, e um
candidato com metade dos eixos ausentes sairia artificialmente próximo de
qualquer query mediana.

### Query incompleta

`QueryNotComparableError` (`DataQualityError`), com a lista dos eixos que
faltaram. É `DataQualityError` e não `ValidationError` porque a **ação é outra**:
uma falha de validação se conserta reenviando; esta não — o pedido está correto,
a linha existe, e o que falta é dado.

**O perfil não é reduzido para caber na query.** Reduzi-lo faria cada query
medir uma grandeza diferente, e dois resultados deixariam de ser comparáveis
entre si sem que nada no objeto dissesse isso.

### Candidato incompleto

Ele **pertence ao universo** e não ao conjunto comparável. É contado como
`INCOMPLETE_PROFILE`, separado dos motivos estruturais:

| motivo | estrutural? | significa |
|---|---|---|
| `INCOMPLETE_PROFILE` | não | o número normal, e o insumo do PR-06.2 |
| `SAME_MATCH` | sim | a divisão deveria ter impedido |
| `REPRESENTATION_MISMATCH` | sim | linhas de escalas diferentes no mesmo universo |

Contá-los juntos esconderia que os dois últimos não deveriam acontecer.

## A dissimilaridade

```
d²(q, c) = Σ (qᵢ - cᵢ)²      para todo i no perfil resolvido
```

### Sem raiz, e o nome diz isso

`sqrt` é monotônica nos reais não negativos, então `d₁² < d₂² ⟺ d₁ < d₂` e o
ranking é idêntico. O que muda é o que se pode afirmar do número:

```
vale        d(q,q) = 0 · d(q,c) ≥ 0 · d(q,c) = d(c,q)
NÃO vale    d(a,c) ≤ d(a,b) + d(b,c)
```

Com `a=0`, `b=1`, `c=2` numa dimensão: `d²(a,c) = 4` e
`d²(a,b) + d²(b,c) = 2`. A desigualdade falha — e isso está **testado como
falha**, para que ninguém a assuma e depois pode uma busca com uma cota que não
existe.

Por isso o nome é **dissimilaridade L2 ao quadrado**, e o campo se chama
`squared_distance`.

### Pesos iguais

Sem alfa, beta, gama, peso por família ou peso aprendido. O perfil já garante
que todos os eixos estão na mesma escala robusta, e é isso que torna a soma
legítima.

### `math.fsum`, e o motivo verdadeiro

A justificativa fácil — «`sum` depende da ordem e `fsum` não» — **é falsa neste
interpretador**. O CPython 3.12 passou a somar `float` com compensação de
Neumaier; em duzentas mil amostras de oito termos nas magnitudes deste dataset
os dois concordam em todos os casos, inclusive com os termos invertidos.

O motivo verdadeiro é de **contrato**: a exatidão de `fsum` é garantia
documentada da linguagem e vale em qualquer implementação e versão; a
compensação de `sum` é detalhe de implementação do CPython, não está na
especificação e não existia antes da 3.12.

A divergência existe e é demonstrável, mas só com razões de escala extremas
(1e18 contra 1e-18) que features normalizadas robustas nunca produzem. Escolher
`fsum` não é consertar um defeito observado: é não depender de um detalhe.

### Não finito é corrupção

`NaN` e infinito são recusados. O dataset normalizado os recusa na escrita
(ADR-0040); um deles chegando aqui significa invariante quebrado a montante, e
tratá-lo como «candidato sem valor» esconderia o defeito atrás de uma ausência
que parece normal.

## A exaustividade

Todo candidato comparável recebe distância **antes** de o top-K ser escolhido.
Sem poda por distância, sem parada antecipada, sem amostragem — e há guarda
arquitetural que recusa um `break` dentro da varredura.

```
memória   O(K + lote)
tempo     O(C log K)   depois do custo das C distâncias
```

**Heap limitado ≠ busca aproximada.** O candidato descartado aqui foi medido e
perdeu; numa busca aproximada ele nunca teria sido visitado. Há teste em que o
melhor candidato é o **último** da varredura — uma parada antecipada o perderia.

### O desempate

```
ordem = (d², chave canônica)   ascendente, sempre
```

O heap inverte a chave **inteira**. Inverter só a distância desempataria ao
contrário e produziria um top-K correto em conteúdo e errado em ordem
exatamente quando há empate no corte do `K` — o defeito que um cenário de cinco
candidatos nunca revela.

## O que o resultado carrega

```
universe_count       quantos a política admitiu
comparable_count     quantos tinham TODOS os eixos
ineligible           a diferença, por motivo
returned_k           min(requested_k, comparable_count)
neighbors            o ranking
exhaustive           True
```

**A atrição é o produto científico deste PR**, tanto quanto o ranking. Um top-10
sozinho não permite dizer se ele saiu de dez mil candidatos ou de onze — e essa
diferença muda completamente o que o número significa.

Se 90 % dos candidatos caírem por `INCOMPLETE_PROFILE`, isso **não é para
consertar aqui**. É a medição que justifica o PR-06.2 existir.

## O que vem depois

Este resultado é a autoridade contra a qual terão de provar correção:

```
Recall@K = |ANN_K ∩ Exact_K| / K       PR-06.4
```

E é o ponto de partida contra o qual a distância ciente de ausência do PR-06.2
vai se comparar.
