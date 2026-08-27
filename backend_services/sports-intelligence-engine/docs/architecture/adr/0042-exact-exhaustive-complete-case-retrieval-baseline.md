# ADR-0042 — O baseline de recuperação é exato, exaustivo e de caso completo

**Status:** aceito · **Data:** 2026-08-26

## Contexto

Definido **quem** pode ser candidato (ADR-0041), falta decidir **como** ordená-los.
E aqui há uma tentação forte: escrever a distância «de produção» agora, com
pesos por família, tratamento de ausência e um limiar de cobertura — e sair do
PR com uma similaridade que parece pronta.

Ela seria uma decisão tomada sem os dados que a justificariam. O PR-05.5.2
mediu, sobre 9,55 milhões de células, que **40,7 % das células dos eixos
robustos saem sem escala**. Uma distância de produção precisa decidir
formalmente:

- o que é uma dimensão compartilhada entre dois snapshots;
- como a cobertura entra no número;
- se ausência penaliza, e quanto;
- se a máscara vira evidência;
- quando dois snapshots simplesmente não se comparam.

Cada uma dessas é uma decisão estatística com consequência, e improvisá-las aqui
produziria um número que **parece uma resposta**. Essas decisões são do PR-06.2.

O que falta hoje é outra coisa, e ela é anterior: **um oráculo**. Um algoritmo
cuja regra seja completamente especificada, que examine todo o universo, e cujo
resultado seja reproduzível bit a bit — para que o índice aproximado do PR-06.4
tenha contra o que provar `Recall@K`, e para que a distância ciente de ausência
do PR-06.2 tenha um ponto de partida com o qual se comparar.

## Decisão

**O PR-06.1 entrega um BASELINE DIAGNÓSTICO exato, e o nome dele diz isso por
extenso:**

```
ROBUST_COMPLETE_CASE_EXACT_BASELINE_V1
```

Três decisões, e as três são deliberadamente as mais restritivas possíveis.

### 1. Os eixos: robustos e ajustados

O perfil resolvido de uma competição são os eixos cuja estratégia no
`NormalizationPlan` é `ROBUST_MEDIAN_IQR_V1` **e** cujo artefato daquela liga
está `FITTED`.

**Só os robustos**, porque eles já estão em escala estatística comparável por
competição. Somar `minute` (0–90), `corners_home_5m` (0–3) e `xg_home_5m`
normalizado (−2 a +2) na mesma distância faz o eixo de maior magnitude dominar —
e o resultado mede principalmente o relógio. Isso não é uma escolha de
similaridade; é um acidente de unidade.

**Só os `FITTED`**, porque `DEGENERATE_SCALE` e `INSUFFICIENT_SAMPLE` significam
que **não existe escala** naquela liga naquele eixo, e a célula sai vazia
(ADR-0035). Um eixo desses no perfil produziria uma coluna que nunca tem valor.

**E a causalidade sai de graça.** O estado do artefato é decidido exclusivamente
pela REFERÊNCIA (ADR-0039), então mexer na avaliação não muda quem está
`FITTED` — logo não muda o perfil resolvido nem a impressão dele.

### 2. A elegibilidade: caso completo

Query e candidato precisam ter valor utilizável em **todos** os eixos do perfil.

```
Coverage = 1   ⟹  distância calculada
Coverage < 1   ⟹  INCOMPLETE_PROFILE, e nenhuma distância
```

Não há imputação por zero, nem por média, nem penalidade por ausência, nem
distância sobre a interseção dos eixos, nem limiar de cobertura de 70 %.

**Uma query incompleta é recusada com tipo próprio** (`QueryNotComparableError`,
`DataQualityError`) — e o perfil **não** é reduzido para caber nela. Reduzi-lo
faria cada query medir uma grandeza diferente, e dois resultados deixariam de
ser comparáveis entre si sem que nada no objeto dissesse isso.

### 3. A dissimilaridade: L2 ao quadrado, pesos iguais

```
d²(q, c) = Σ (qᵢ - cᵢ)²      para todo i no perfil resolvido
```

**Sem raiz.** `sqrt` é monotônica nos reais não negativos, então o ranking é
idêntico e o trabalho é menor.

**E por isso o nome é «dissimilaridade», e não «distância euclidiana».** `d²`
NÃO satisfaz a desigualdade triangular — `d²(a,c) = 4` contra
`d²(a,b) + d²(b,c) = 2` num exemplo de uma dimensão. Ela satisfaz identidade,
não-negatividade e simetria, e essas três estão testadas; a quarta está testada
como **falha**, para que ninguém a assuma e depois pode uma busca com uma cota
que não existe.

**Pesos iguais.** Sem alfa, beta, gama, peso por família ou peso aprendido. O
perfil já garante que todos os eixos estão na mesma escala robusta, que é o que
torna a soma legítima.

**A soma é `math.fsum`.** A justificativa fácil — «`sum` depende da ordem» — é
falsa neste interpretador: o CPython 3.12 passou a somar `float` com compensação
de Neumaier, e nas magnitudes deste dataset os dois concordam sempre. O motivo
verdadeiro é de **contrato**: a exatidão de `fsum` é garantia documentada da
linguagem, enquanto a compensação de `sum` é detalhe de implementação do CPython.
A divergência existe e é demonstrável, mas só com razões de escala extremas que
features normalizadas robustas nunca produzem.

### 4. A exaustividade

Todo candidato comparável recebe distância **antes** de o top-K ser escolhido.
Sem poda por distância, sem parada antecipada, sem amostragem.

O top-K usa um heap limitado de `K` elementos — `O(K + lote)` de memória,
`O(C log K)` de tempo —, e isso **não** é busca aproximada: o candidato
descartado foi medido e perdeu. Numa busca aproximada ele nunca teria sido
visitado.

**O desempate é canônico**: `(d², chave)`, sempre ascendente. Sem ele, dois
candidatos à mesma distância trocariam de posição entre execuções conforme a
ordem de leitura do bucket. O heap inverte a chave **inteira** — distância e
desempate —, porque inverter só a distância desempataria ao contrário e
produziria um top-K correto em conteúdo e errado em ordem exatamente quando há
empate no corte do `K`.

## Consequências

**A atrição é um produto, e não um defeito.** `universe_count`,
`comparable_count` e as contagens por motivo saem em todo resultado. Se 90 % dos
candidatos caírem por `INCOMPLETE_PROFILE`, isso não é para consertar aqui: é a
medição que justifica o PR-06.2 existir, e escondê-la atrás de um top-K cheio
seria transformar evidência em silêncio.

**O resultado é reproduzível bit a bit.** Mesma query, mesmo dataset, mesma
política, mesmo perfil, mesma distância e mesmo `K` produzem a mesma impressão —
sob qualquer ordem de iteração, qualquer tamanho de lote e qualquer layout de
Parquet. Há teste de propriedade para cada uma das três variações.

**O `K` tem propriedade de prefixo.** `top10(K=50)` é exatamente
`resultado(K=10)` sobre o mesmo universo, **inclusive quando há empate no
corte**.

**`exhaustive = True` é um campo, e não uma convenção de nome.** Ele existe
porque um dia haverá um resultado aproximado ao lado deste, e os dois precisam
ser distinguíveis por tipo.

**Este número NÃO é a similaridade final do Insight, e o objeto diz isso.**
`RetrievalFeatureProfile.is_diagnostic` é uma propriedade consultável, e a saída
da CLI a imprime. Deixar essa afirmação só na documentação faria alguém citar um
top-K deste perfil como resposta de produto.

## Alternativas descartadas

**Escrever a distância final agora.** Descrita no contexto: seria uma decisão
estatística tomada sem os dados que a justificariam.

**Distância sobre a interseção dos eixos.** Cada par de snapshots mediria uma
grandeza diferente, e dois resultados não se comparariam. É uma das opções que
o PR-06.2 vai avaliar — com o número da atrição na mão.

**Imputar zero no que falta.** Num espaço robusto, zero é a **mediana** da
competição: imputá-lo diz «este estado é típico», que é uma afirmação forte
sobre um dado que não existe. E um candidato com metade dos eixos ausentes
sairia artificialmente próximo de qualquer query mediana.

**Raiz quadrada no resultado.** Custo sem ganho de ranking. Se algum consumidor
futuro precisar da métrica, ele tira a raiz — e aí ele sabe que está tirando.

**Ordenar todos os candidatos e fatiar.** `O(C log C)` de tempo e `O(C)` de
memória para um resultado idêntico ao do heap.
