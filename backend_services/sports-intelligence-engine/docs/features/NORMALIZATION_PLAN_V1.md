# `MATCH_STATE_NORMALIZATION_PLAN_V1` — o plano de normalização

**Versão:** 1.0 · **Espaço:** `MATCH_STATE_RAW_V2` · **PR:** 05.5.2 ·
**ADR:** [0038](../architecture/adr/0038-normalization-plan-is-explicit-and-semantic.md)

## O que ele é

Uma tabela com **uma entrada por dimensão** do espaço, dizendo qual
transformação cada eixo recebe e **por quê**. Nada é decidido em execução, e
nada é inferido do tipo do dado.

```
MATCH_STATE_NORMALIZATION_PLAN_V1@1.0
105 eixos
    PASS_THROUGH_V1        76
    ROBUST_MEDIAN_IQR_V1   29
```

## Por que ele existe

`MATCH_STATE_RAW_V2` tem 105 dimensões em unidades diferentes. Uma distância que
as some está somando gols com cotações com minutos. Normalizar resolve isso — e
normalizar **as numéricas** cria um problema pior, porque o resultado errado é
plausível.

O par que justifica o plano inteiro, as duas colunas `double` do mesmo arquivo:

```
market_1x2_home_median      2.35     uma cotação      → ROBUST
market_1x2_home_support        7     quantas casas    → PASS_THROUGH
```

Reescalar a segunda produz `(7 - 6) / 2 = 0.5`. Parece sinal. É ruído com a
unidade apagada, e a informação de que aquilo era uma contagem se perdeu na
transformação.

## As duas estratégias

O catálogo é **fechado**. Não há z-score, min-max, log, winsorização, clipping,
Box-Cox nem quantile transform — e a ausência é verificada por guarda
arquitetural.

### `PASS_THROUGH_V1`

O valor sai **exatamente** como entrou, bit a bit. O caminho **não atravessa
`Decimal`**: `float → Decimal → float` volta ao mesmo número, mas «volta ao
mesmo número» é uma afirmação sobre a implementação da conversão, e não sobre o
contrato. O contrato aqui é bit a bit, e a única forma de garanti-lo é não
converter.

### `ROBUST_MEDIAN_IQR_V1`

```
Normalized(x) = (x - mediana_C) / IQR_C
```

Por competição, com mediana e IQR exatos em `Decimal`, quantis de tipo 7
(ADR-0035). Sem epsilon, sem fallback, sem clipping.

## As nove razões

A razão não é documentação: é um catálogo fechado, e é o que permite auditar a
classificação sem reler o código.

| razão | estratégia | nº | exemplo |
|---|---|---:|---|
| `SPARSE_DISCRETE_COUNT` | PASS_THROUGH | 48 | `shots_home_5m` |
| `CONTINUOUS_COMPETITION_SCALED` | ROBUST | 12 | `xg_home_5m` |
| `STRUCTURAL_MATCH_STATE` | PASS_THROUGH | 12 | `red_cards_home` |
| `MARKET_PRICE_LEVEL` | ROBUST | 7 | `market_1x2_home_median` |
| `MARKET_PRICE_DISPERSION` | ROBUST | 7 | `market_1x2_home_iqr` |
| `BOOKMAKER_SUPPORT_COUNT` | PASS_THROUGH | 7 | `market_1x2_home_support` |
| `CALENDAR_MATCH_COUNT` | PASS_THROUGH | 6 | `matches_last_7d` |
| `CALENDAR_INTERVAL_HOURS` | ROBUST | 3 | `prev_kickoff_gap_hours` |
| `CLOCK_COORDINATE` | PASS_THROUGH | 3 | `minute` |

### Por que cada uma

**`SPARSE_DISCRETE_COUNT`.** Uma contagem numa janela de cinco minutos vale 0, 1
ou 2 na esmagadora maioria dos cortes. O IQR é frequentemente zero, e reescalar
uma distribuição sem dispersão não produz escala: produz `DEGENERATE_SCALE` ou,
com epsilon, números enormes que parecem sinal.

**`CONTINUOUS_COMPETITION_SCALED`.** xG é contínuo e a escala varia de liga para
liga. É o caso canônico da normalização robusta.

**`STRUCTURAL_MATCH_STATE`.** Cartões vermelhos, jogadores em campo, diferença
de gols. São estados discretos com significado absoluto: «10 contra 11» é a
mesma coisa em toda liga, e reescalá-lo apagaria isso.

**`MARKET_PRICE_LEVEL` e `MARKET_PRICE_DISPERSION`.** Cotação e dispersão de
cotação são preços. O nível típico de uma cotação de empate varia entre ligas —
uma liga com muitos empates precifica diferente.

**`BOOKMAKER_SUPPORT_COUNT`.** Quantas casas publicaram é uma medida de
COBERTURA, e não de futebol. Reescalá-la faria «sete casas» significar coisas
diferentes em ligas diferentes, e o número resultante não descreveria nem
cobertura nem preço.

**`CALENDAR_MATCH_COUNT` e `CALENDAR_INTERVAL_HOURS`.** «Quantas partidas nos
últimos sete dias» é uma contagem pequena e absoluta; «quantas horas desde o
último jogo» é um intervalo contínuo cuja distribuição varia com o calendário da
liga. As duas são de contexto, e recebem tratamentos opostos.

**`CLOCK_COORDINATE`.** O minuto do jogo é uma **coordenada**, e não uma medida.
A grade existe justamente para que «minuto 45» signifique a mesma coisa em todas
as competições; reescalá-lo pela mediana da liga desfaria isso.

## A classificação é uma função, não uma lista

Uma tabela literal de 105 linhas envelheceria em silêncio: a feature nova
entraria no espaço e ficaria de fora do plano. Aqui a classificação lê os
**metadados** do catálogo:

```python
if isinstance(spec, RollingFeatureSpec):
    if spec.family is RollingFamily.XG:  → ROBUST, CONTINUOUS_COMPETITION_SCALED
    else:                                → PASS_THROUGH, SPARSE_DISCRETE_COUNT
if isinstance(spec, ContextFeatureSpec):
    if spec.kind is PREV_KICKOFF_GAP_HOURS: → ROBUST, CALENDAR_INTERVAL_HOURS
    else:                                    → PASS_THROUGH, CALENDAR_MATCH_COUNT
if isinstance(spec, MarketFeatureSpec):
    MEDIAN → ROBUST, MARKET_PRICE_LEVEL
    IQR    → ROBUST, MARKET_PRICE_DISPERSION
    else   → PASS_THROUGH, BOOKMAKER_SUPPORT_COUNT
else: → PASS_THROUGH, (CLOCK_COORDINATE | STRUCTURAL_MATCH_STATE)
```

E o construtor **confere que o conjunto de chaves do plano é exatamente o
conjunto de chaves do espaço** — nem um a mais, nem um a menos, sem repetição.

## A identidade

```
plan_fingerprint = sha256(canonical_json({
    algorithm, name, version,
    space: {name, version, fingerprint},
    normalizer: {key, fingerprint},
    fit_split: "REFERENCE",
    input_bridge, output_encoding,
    transforms: [{feature_key, feature_version, feature_fingerprint,
                  strategy, rationale}, ...]
}))
```

**O corte do ajuste entra na identidade** através da impressão do normalizador
(PR-05.1 §89): o plano de um ajuste até junho não é o plano de um ajuste até
agosto. As decisões por eixo são as mesmas; a escala que sai delas não é.

**A ordem das transformações é a do espaço**, e ela entra na impressão:
reordená-las produziria o mesmo conjunto de decisões sobre um espaço diferente.

**Cada entrada carrega a impressão da definição da feature**, e não só a chave.
Duas versões da mesma feature têm a mesma chave e escalas diferentes; um plano
que guardasse só o nome continuaria «válido» depois de a definição mudar.

## Onde ele aparece

| lugar | forma |
|---|---|
| domínio | `NormalizationPlan`, construído por `normalization_plan_v1()` |
| manifesto normalizado | **por extenso**, com todas as 105 entradas |
| versão normalizada | por impressão, nas colunas `plan_name/version/fingerprint` |
| linha do Parquet | por impressão, na coluna `plan_fingerprint` |

O manifesto o carrega por extenso porque «este eixo foi reescalado?» é a
primeira pergunta de quem lê o dataset seis meses depois — e a impressão só
responde «é o mesmo plano de antes», o que não ajuda quem nunca viu o de antes.

## O que ele NÃO faz

- não escolhe a população do ajuste (isso é [CAUSAL_NORMALIZER_FIT_V1](CAUSAL_NORMALIZER_FIT_V1.md))
- não calcula mediana nem IQR
- não decide por `dtype`, e a guarda arquitetural recusa qualquer sinal disso
- não tem uma terceira estratégia, nem um caminho para acrescentá-la em execução
