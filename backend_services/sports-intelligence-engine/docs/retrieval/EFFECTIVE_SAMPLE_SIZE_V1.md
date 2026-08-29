# Tamanho efetivo de amostra — V1

```
N_eff = 1 / Σ_i p_i²
```

onde `p_i` são os pesos normalizados definidos em `DISTANCE_WEIGHTING_V1.md`.

## O que ele mede

A **concentração** dos pesos, expressa numa escala fácil de ler: a de
observações equiponderadas.

```
pesos uniformes sobre k vizinhos    →  N_eff = k       (concentração mínima)
toda a massa num vizinho só         →  N_eff = 1       (concentração máxima)
```

Para `k > 0`, sempre `1 <= N_eff <= k`. Os dois extremos são alcançáveis, e os
dois são testados como goldens.

## O que ele NÃO mede

Esta seção é normativa.

```
N_eff  !=  confiança
N_eff  !=  probabilidade
N_eff  !=  certeza sobre o desfecho
N_eff  !=  correção dos dados
N_eff  !=  número de partidas
N_eff  !=  ensaios independentes
```

### Como ler `N_eff = 12,34` num top-20

**Certo:**

> A concentração dos pesos normalizados é matematicamente equivalente, sob a
> definição de ESS, a aproximadamente 12,34 observações equiponderadas.

**Errado:**

> «12,34 partidas.» São vinte partidas. Todas as vinte estão lá, todas têm
> identidade, e nenhuma foi descartada. `N_eff` descreve como a massa se
> distribui entre elas — não quantas são.

**Errado:**

> «61,7% de confiança.» `12,34 / 20 = 0,617` é uma razão entre uma medida de
> concentração e uma contagem. Não é uma probabilidade, não foi calibrada
> contra nada, e nada foi observado sobre o futuro para produzi-la.

**Errado:**

> «12,34 ensaios independentes.» Os vizinhos não são amostras independentes de
> nada. Podem ser da mesma competição, da mesma temporada, do mesmo time — e o
> universo de candidatos é justamente construído por proximidade.

## Sem limiares nesta versão

A V1 **expõe o valor e nada mais**. Não existem, e não devem ser criados:

```
HIGH_CONFIDENCE
LOW_CONFIDENCE
N_eff >= limiar
```

Um limiar sobre `N_eff` seria uma regra de decisão, e regras de decisão
pertencem à camada que interpreta a evidência — declarada e avaliada como tal.
Escondê-la aqui, dentro de uma constante de comparação, produziria um modelo que
ninguém declarou.

O catálogo de nomes do pacote é guardado por teste: nenhum símbolo público pode
se chamar `probability`, `confidence`, `likelihood` ou `certainty`. Um campo com
esse nome seria lido como tal por quem consumisse o contrato, e nenhuma
quantidade de documentação desfaz um nome.

## Ausência não é zero

Quando o retrieval não devolve vizinho elegível, o agregado é
`NO_NEIGHBORS` e `N_eff` é `None`.

Não é `0,0`. Um agregado vazio com `N_eff = 0` e soma de pesos `0` pareceria uma
**medição** — «concentração mínima», «nenhuma massa» — quando o que houve foi
ausência de dados. O estado é dito explicitamente, e os campos numéricos ficam
indefinidos.

Para `k = 1`, o peso é `1,0` e `N_eff = 1,0`. Isso é uma medição, e não uma
ausência: há um vizinho, e toda a massa é dele.

## Onde `N_eff` fica pequeno, e o que isso quer dizer

`N_eff` bem abaixo de `K` significa que poucos vizinhos concentram a massa —
porque estão bem mais próximos que os demais. É informação sobre a **geometria
do conjunto recuperado**, e não um defeito.

O caminho inverso também: `N_eff ≈ K` significa que os vizinhos do top-K estão
aproximadamente equidistantes. Também não é defeito, e também não é algo que um
`λ` maior deva «consertar» — ver a planura documentada em
`PR06_5_AGGREGATION_BASELINE.md`.
