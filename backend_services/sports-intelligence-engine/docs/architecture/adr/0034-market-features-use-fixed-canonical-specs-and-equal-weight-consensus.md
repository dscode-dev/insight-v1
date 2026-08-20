# ADR-0034 — Features de mercado usam especificações canônicas fixas e consenso robusto de peso igual

**Status:** aceito · **Data:** 2026-08-20

## Contexto

O corpus publica cotações: várias casas de aposta, vários mercados, várias
observações ao longo do tempo. O `HistoricalMatchState` (PR-05.2) já reduz isso
à última cotação temporalmente elegível de cada fluxo. Falta transformá-la em
dimensões de um espaço de features.

O obstáculo é estrutural, e não estatístico. **Um `FeatureSpace` tem dimensão
fixa** — ela é a ordem dos eixos do vetor futuro e entra na identidade do
espaço. A forma óbvia de vetorizar mercado é uma coluna por casa:

```
odds_bet365_home, odds_pinnacle_home, odds_william_home, …
```

Ela faz o tamanho do espaço depender de quantas casas aquele corpus publicou.
Dois snapshots do mesmo jogo, lidos de corpus diferentes, teriam tamanhos
diferentes — e a comparação entre eles deixaria de existir por um motivo que
não tem nada a ver com futebol.

Há um segundo obstáculo, mais silencioso. «Mediana» e «quartil» soam como
conceitos únicos e não são: há pelo menos nove definições de quantil amostral
em uso, e bibliotecas diferentes escolhem diferentes. Sobre quatro cotações,
`1.80 1.90 2.00 2.10`, a convenção inclusiva dá `IQR = 0,15` e a exclusiva dá
`0,20`. As duas são «o IQR».

## Decisão

**Os mercados são declarados por extenso, o consenso é robusto e de peso igual,
e o método de quantil é nosso e versionado.**

```
CanonicalMarketSpec = (mercado, seleção, linha)
sete especificações × três dimensões = 21 features
```

Cinco consequências:

**1. A casa de aposta não é dimensão.** Ela é entrada e procedência. O espaço
tem 21 colunas de mercado sobre qualquer corpus — com três casas ou com trinta.

**2. Três dimensões por mercado, com disponibilidades independentes.**
`median` (nível), `iqr` (dispersão), `support` (quantas casas). Uma casa
sustenta nível e suporte, e não sustenta dispersão.

**3. Todas as casas pesam 1.** Declarar que uma casa vale mais que outra é uma
decisão de modelagem com evidência própria; embuti-la aqui a esconderia dentro
de um número que parece uma média.

**4. O método de quantil é `LINEAR_INTERPOLATED_QUANTILE_V1`**, implementado em
`Decimal` neste repositório. Ele é o tipo 7 do R — escolhido por ser o mais
difundido, e não por ser «o certo»: não existe um certo, existe um DECLARADO. O
motor não pode ter a identidade das suas escalas mudada por um `pip install -U`.

**5. Suporte mínimo declarado em política versionada.** Mediana a partir de 1
casa; IQR a partir de 4 — o mínimo em que os dois quartis são interpolados
entre pontos distintos. Uma casa cotando `2.00` produz IQR **indisponível**;
quatro casas cotando `2.00` produzem `IQR = 0` **observado**.

**A autoridade temporal é o `OddsState`.** A extração de mercado não vai ao
banco e não refiltra por tempo. Uma segunda regra temporal divergiria da
primeira exatamente no caso difícil.

**O handicap fica de fora.** `ASIAN_HANDICAP` exige linha, e a linha varia por
jogo. Fixar uma produziria coluna quase sempre vazia; não fixar produziria
dimensão variável. Canonizar um mercado de handicap é decisão própria, e não
foi improvisada com alias textual.

## Consequências

**Positivas.** A dimensão do espaço é uma propriedade do catálogo, e não do
provedor. O consenso é resistente a uma casa fora da curva. A identidade da
escala não depende de biblioteca instalada. E a distinção entre «uma casa» e
«quatro casas concordando» sobrevive até o vetor.

**Negativas, e assumidas.** A mediana descarta informação: quinze casas viram
um número. Mercados fora das sete especificações não têm dimensão nenhuma —
`Over 3.5` existe no corpus e não no espaço. O suporte mínimo de 4 para IQR
deixa muitos jogos sem dispersão afirmável em corpus de cobertura fina.

**O que esta decisão NÃO fecha.** Probabilidade implícita, remoção de margem e
movimento de linha continuam possíveis — cada um com política própria.
Movimento em particular exige quatro decisões (linha de base, suporte ao longo
do tempo, conjunto variável de casas, cadência de observação), e escondê-las
numa feature `delta` faria as quatro passarem por uma.

## Alternativas consideradas

**Uma dimensão por casa de aposta.** Rejeitada pelo motivo central: dimensão
variável.

**Média em vez de mediana.** Rejeitada: uma casa com erro de digitação
—`19.0` em vez de `1.90` — desloca a média e não desloca a mediana.

**Mediana ponderada por «qualidade» da casa.** Rejeitada: exige evidência de
qualidade relativa, que não existe neste corpus.

**Usar `statistics.quantiles` do Python.** Rejeitada: a convenção padrão dele é
exclusiva, e a escolha ficaria implícita numa dependência. O que se perde ao
implementar é meia página de código; o que se ganha é o controle da identidade.

**Probabilidade implícita (`1/odds`) como feature.** Rejeitada nesta fase: sem
remover a margem, as três seleções do 1X2 somam mais que 1 — e o número parece
probabilidade.

## Referências

- ADR-0030 — definições e espaços de feature são contratos versionados
- ADR-0031 — o estado histórico é reconstruído e nunca armazenado
- ADR-0035 — normalização usa o mesmo método de quantil
- `docs/features/CANONICAL_MARKET_FEATURES_V1.md`
- `docs/features/RAW_FEATURE_CATALOG_V2.md`
