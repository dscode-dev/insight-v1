# Features canônicas de mercado — V1

> Vinte e uma dimensões: **nível**, **dispersão** e **suporte** de sete
> mercados declarados. Agregação, e nunca previsão.

---

## 1. O problema da dimensão fixa

Um `FeatureSpace` tem dimensão fixa — ela é a ordem dos eixos do vetor futuro e
entra na identidade do espaço. Uma feature por casa de aposta descoberta faria
o tamanho do espaço depender de quantas casas aquele corpus publicou:

```
corpus A  →  8 casas  →  vetor de tamanho X
corpus B  →  3 casas  →  vetor de tamanho Y
```

Dois snapshots do mesmo jogo deixariam de ser comparáveis por um motivo que não
tem nada a ver com o jogo.

**A saída é declarar os mercados por extenso.** A casa de aposta não aparece no
espaço: ela é **entrada** e **procedência**.

```
dimensão do espaço  ←  catálogo declarado (7 mercados)
casas de aposta     →  agregação e procedência
```

---

## 2. Os sete mercados canônicos

`CanonicalMarketSpec` é `(mercado, seleção, linha)`:

| fragmento | mercado | seleção | linha |
|---|---|---|---|
| `1x2_home` | `MATCH_RESULT_1X2` | `HOME` | — |
| `1x2_draw` | `MATCH_RESULT_1X2` | `DRAW` | — |
| `1x2_away` | `MATCH_RESULT_1X2` | `AWAY` | — |
| `totals_over_25` | `TOTAL_GOALS` | `OVER` | `2.5` |
| `totals_under_25` | `TOTAL_GOALS` | `UNDER` | `2.5` |
| `btts_yes` | `BOTH_TEAMS_TO_SCORE` | `YES` | — |
| `btts_no` | `BOTH_TEAMS_TO_SCORE` | `NO` | — |

Os três mercados pedidos pela especificação estão todos representáveis pelo
modelo canônico de odds (PR-01) — **não houve blocker**.

**A linha faz parte da identidade.** «Mais de 2,5 gols» e «mais de 3,5» são
apostas diferentes com a mesma seleção `OVER`; sem a linha na chave e na
impressão, as duas seriam a mesma feature e a agregação misturaria dois
mercados.

### 2.1 O handicap fica de fora

`ASIAN_HANDICAP` existe no modelo canônico e **não entra na V2**. A linha dele
**varia por jogo** — `-0.5`, `-1.0`, `-1.25` conforme o favoritismo:

- fixar uma linha produziria uma dimensão vazia na maioria das partidas;
- não fixar produziria dimensão variável, que é o problema da seção 1.

As duas saídas são erradas. Canonizar um mercado de handicap é uma decisão
própria, e não foi improvisada com um alias textual.

---

## 3. As três dimensões

Para cada mercado:

```
market_{fragmento}_median     nível       — onde o mercado está
market_{fragmento}_iqr        dispersão   — quanto as casas discordam
market_{fragmento}_support    suporte     — quantas casas sustentam os dois
```

`7 × 3 = 21 features`. Ordem dentro de cada mercado: mediana, IQR, suporte —
declarada, e não alfabética (o alfabeto poria `iqr` antes de `median`).

---

## 4. Consenso não é previsão

`median_decimal_odds` é o que **as casas publicaram**, agregado de forma
resistente a extremo. Não é a previsão do Insight.

A distinção importa porque, no dia em que o motor tiver previsão própria, as
duas vão aparecer lado a lado — e confundi-las faria o modelo aprender a prever
o mercado em vez do jogo.

**Todas as casas pesam 1.** Declarar que uma casa vale mais que outra é uma
decisão de modelagem com evidência própria, e embuti-la aqui a esconderia
dentro de um número que parece uma média.

---

## 5. O método de quantil é NOSSO

Há pelo menos nove definições de quantil amostral em uso, e bibliotecas
diferentes escolhem diferentes. Trocar uma pela outra muda o Q1 de uma amostra
de quatro valores — e nada denuncia.

```
LINEAR_INTERPOLATED_QUANTILE_V1

    h = (n - 1) · p
    resultado = x[⌊h⌋] + (h - ⌊h⌋) · (x[⌈h⌉] - x[⌊h⌋])
```

É a interpolação linear inclusiva — tipo 7 do R, padrão do NumPy —
implementada em `Decimal` para que o resultado não dependa de qual biblioteca
está instalada.

Um exemplo que mostra por que isso importa:

```
1.80  1.90  2.00  2.10        (n = 4)

método declarado (inclusivo)     Q1 = 1.875   Q3 = 2.025   IQR = 0.15
convenção exclusiva do Python    Q1 = 1.85    Q3 = 2.05    IQR = 0.20
```

Os dois são «o IQR». Um `pip install -U` que trocasse um pelo outro mudaria
toda escala derivada, e o sintoma apareceria longe da causa.

---

## 6. Suporte mínimo

`MarketConsensusPolicy` declara os limiares, versionada e impressa:

```
median_minimum_support = 1
iqr_minimum_support    = 4
quantile_method        = LINEAR_INTERPOLATED_QUANTILE_V1
duplicate_bookmaker    = LAST_KNOWN_PER_STREAM
```

**Por que a mediana admite 1.** Uma casa já diz onde aquela casa está, e isso é
informação legítima.

**Por que o IQR exige 4.** É o mínimo em que os dois quartis são interpolados
entre pontos distintos. Com três, Q1 e Q3 caem sobre os próprios valores e o
IQR vira a amplitude entre o primeiro e o terceiro — outra medida com o mesmo
nome.

E o caso decisivo:

```
uma casa cotando 2.00      →  IQR unavailable
quatro casas cotando 2.00  →  IQR = 0  AVAILABLE
```

Os dois «poderiam valer zero». Só o segundo é uma observação sobre o mercado —
o primeiro seria afirmar unanimidade quando não há com quem concordar.

---

## 7. A autoridade temporal é o `OddsState`

A extração de mercado **não vai ao banco** e **não refiltra por tempo**.

```
canonical_odds_observations
      ↓  TemporalLeakageGuard (PR-05.1) + última por fluxo (PR-05.2)
OddsState                              ← a autoridade
      ↓  compute_consensus
MarketConsensus
```

O `OddsState` já carrega a última cotação temporalmente elegível de cada fluxo,
uma por casa. Reimplementar o filtro aqui criaria uma segunda regra temporal,
que divergiria da primeira no caso difícil.

Consequência direta: **cotações futuras não mudam nada**, e o mercado **evolui
com o corte** — uma cotação publicada aos 20 minutos entra num snapshot de 30 e
não num de 10.

---

## 8. Disponibilidade

Três ausências que produziriam o mesmo `None` e significam coisas diferentes:

| situação | estado |
|---|---|
| a versão não publica `ODDS` | `NOT_DECLARED` |
| publica, e nenhuma cotação é elegível no corte | `TEMPORALLY_UNAVAILABLE` + motivo tipado |
| publica, e **este mercado** não veio | `SOURCE_UNAVAILABLE` |
| veio, e o suporte é insuficiente | `INSUFFICIENT_COVERAGE` |

A cotação decimal zero **não existe no domínio** — ela é recusada como dado
inválido, e não tratada como ausência. Por isso não há semântica de
`missing ≠ zero` para o nível de mercado: `0` nunca é um preço.

`ODDS` é **opcional** no espaço V2. Um corpus sem mercado continua produzindo
snapshot, com as vinte e uma dimensões indisponíveis na máscara. Torná-la
obrigatória recusaria o corpus inteiro por causa de uma família acessória.

---

## 9. Procedência

Cada um dos três números aponta as **observações de odds** que o sustentam.

A referência de uma cotação começa pelo **fluxo** — `casa|mercado|seleção|linha`
— e não pelo registro de origem. Quatro casas de um mesmo arquivo compartilham
o `source_record_id`, e usá-lo sozinho faria as quatro contribuições
colapsarem numa: a procedência diria «uma cotação sustenta esta mediana»
quando são quatro. O registro de origem viaja junto, depois do `#`, para a
travessia até o corpus.

A ordem das casas não muda nada — nem valor, nem digest de procedência.

---

## 10. O que este PR NÃO calcula

| ausente | por quê |
|---|---|
| probabilidade implícita (`1/odds`) | sem remover a margem, o vetor soma mais que 1 e parece probabilidade |
| overround / remoção de vig | exige política de mercado própria |
| movimento de linha (abertura → atual) | exige decidir linha de base, suporte ao longo do tempo, conjunto variável de casas e cadência de observação |
| velocidade, aceleração, *steam*, *drift* | derivadas do anterior |
| peso por casa de aposta | exige evidência de qualidade relativa |
| handicap | ver seção 2.1 |

O movimento é o mais tentador: um `delta` parece uma subtração. Ele esconde
**quatro decisões** — e escondê-las numa feature aparentemente simples faria as
quatro passarem por uma.

**Este PR mede o mercado em `t`, e não a trajetória dele.**

---

## 11. Documentos relacionados

- ADR-0034 — a decisão e as alternativas rejeitadas
- `RAW_FEATURE_CATALOG_V2.md` — o espaço estendido inteiro
- `PRE_MATCH_CONTEXT_V1.md` — a outra família nova da V2
- `HISTORICAL_MATCH_STATE_V1.md` — o `OddsState` que alimenta este consenso
- `ROBUST_NORMALIZATION_V1.md` — o mesmo método de quantil, outro uso
