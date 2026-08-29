# ADR-0050 — Ponderar por distância é agregar evidência, e não estimar probabilidade

**Estado:** aceito · **PR:** 06.5

## Contexto

O PR-06.4 fechou entregando um conjunto de vizinhos históricos **exato e
determinístico**: dada uma consulta, o motor sabe dizer quais partidas passadas
são comparáveis e a que dissimilaridade cada uma está.

A pergunta do PR-06.5 é o que fazer com esse conjunto:

> Como transformar vizinhos exatos em evidência agregável, ponderada e
> numericamente estável — sem transformar distância em probabilidade, sem
> inventar confiança e sem olhar desfecho?

Um conjunto de vinte vizinhos com dissimilaridades entre `0,00` e `0,63` não é
utilizável como está. O vizinho a `0,00` e o vizinho a `0,63` não podem valer o
mesmo, e o consumidor precisa de alguma noção de quanto o conjunto está
concentrado. Mas o passo seguinte — chamar isso de probabilidade — é curto
demais para ser deixado implícito.

## A tentação, e por que ela é um erro

`exp(-λd)` normalizado produz números que somam um, são não negativos, e são
maiores para os vizinhos mais próximos. Eles **têm a forma** de uma distribuição
de probabilidade, e é exatamente por isso que a confusão é fácil.

Mas a forma não é a semântica. `p_i = 0,115` significa:

> este vizinho responde por 11,5% da massa comparativa do conjunto recuperado

e **não** significa:

> há 11,5% de chance de qualquer coisa

Não há espaço amostral, não há evento, e nada foi observado sobre o futuro. O
número descreve a geometria do conjunto recuperado, e nada além disso.

## Decisão

Adotar o núcleo exponencial com normalização deslocada, e declarar
explicitamente o que ele **não** produz.

### O núcleo

```
u_i = exp(-λ (d_i - d_min))

p_i = u_i / Σ_j u_j
```

O deslocamento por `d_min` é **estabilidade numérica, e não semântica**: ele
cancela na razão, então `p_i` é idêntico ao de `exp(-λd_i)` normalizado — e o
maior expoente vira sempre `exp(0) = 1`, o que impede o subfluxo que
`exp(-λd)` produziria com `λ` grande.

    IEEE754_FLOAT64_FSUM_V1              a soma é `math.fsum`
    SHIFTED_EXPONENTIAL_MIN_DISTANCE_V1  a normalização é esta, e é congelada

### O tamanho efetivo

```
N_eff = 1 / Σ_i p_i²        com  1 <= N_eff <= k
```

### As quatro negativas, que são normativas

```
dissimilaridade   !=  probabilidade
peso normalizado  !=  probabilidade de desfecho
peso normalizado  !=  confiança
N_eff             !=  confiança
```

`N_eff = 12,34` num top-20 significa que a concentração dos pesos é
matematicamente equivalente, sob a definição de ESS, a cerca de 12,34
observações equiponderadas. Não significa «12,34 partidas», não significa
«61,7% de confiança», e não significa «12,34 ensaios independentes».

## O que sustenta a decisão

**A agregação não lê desfecho.** Guardas de arquitetura sobre imports e
símbolos, e uma prova de conteúdo sobre o objeto que sai da execução real.

**A agregação não lê armazenamento.** Uma vez que o resultado exato existe, a
transformação é pura: PostgreSQL, MinIO e Parquet medidos em zero, com um teste
que primeiro prova que o contador **enxerga** leituras quando elas existem.

**A cobertura não entra duas vezes.** A distância exata já cobra a ausência —
`p = 1` por eixo ausente no PR-06.2, por célula ausente no PR-06.3. Multiplicar
o peso pela cobertura cobraria a mesma ausência uma segunda vez:

```
PROIBIDO   peso = exp(-λd) × cobertura
PROIBIDO   peso = exp(-λd) × razão_de_eixos_compartilhados
```

A direção é uma só: **peso → resumo**, nunca o contrário. O resumo de evidência
é calculado *com* os pesos, para descrever o conjunto que de fato influencia, e
nunca volta ao cálculo deles. Isto é testado diretamente: mudar a evidência sem
mudar a distância deixa pesos e `N_eff` **idênticos**.

## Consequências

O motor passa a transformar vizinhos exatos em vizinhança ponderada com tamanho
efetivo, sem acesso adicional a armazenamento e sem informação de desfecho.

E continua **sem fazer afirmação alguma** sobre o que esses vizinhos implicam
para a partida consultada. Isso começa no PR-06.6, e é uma camada declarada e
avaliada — não um efeito colateral de ter chamado um peso de probabilidade.

## Alternativas descartadas

**Núcleo uniforme.** Ignora informação que existe: um vizinho a `0,00` e outro
a `0,63` não são igualmente comparáveis. Preservado apenas como linha de base de
teste (`UNIFORM_WEIGHTING_BASELINE_V1`), onde serve para provar `N_eff = k`.

**Softmax sobre similaridade.** Mesma forma funcional, com o agravante de
carregar o vocabulário de classificação — «logits», «probabilidades de classe» —
para dentro de uma camada que não classifica nada.

**Corte rígido por limiar de distância.** Descarta informação de forma abrupta e
introduz um parâmetro com a mesma necessidade de justificativa que `λ`, sem a
continuidade que torna o comportamento previsível perto do limiar.
