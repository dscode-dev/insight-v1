# Catálogo de features CRUAS — `MATCH_STATE_RAW_V2`

> 105 definições: as **75 da V1 intactas**, mais 9 de contexto pré-jogo e 21 de
> mercado canônico.
>
> Espaço: `MATCH_STATE_RAW_V2@v2.0`
> Impressão: `9ab9b3222f9997a272d3dbde25b18698a1807092a0c6278382eb8a25194f266a`

**A V1 não mudou.** `MATCH_STATE_RAW_V1@v1.0` continua com 75 definições e a
mesma impressão `384038f2b11a754873451361e49e76d0f999ca653d6ac744078da30670545172`.
`RAW_FEATURE_CATALOG_V1.md` continua descrevendo-a, e este documento não a
reescreve.

---

## 1. Por que uma versão nova em vez de crescer a V1

Um espaço que ganhasse trinta dimensões mantendo o número da versão faria todo
snapshot histórico comparar com um espaço que não é o dele. A comparação **não
falharia** — ela mentiria, porque os primeiros 75 eixos ainda casariam.

```
V1  75 features   v1.0   384038f2…
V2 105 features   v2.0   9ab9b322…
```

As duas coexistem no registro de produção. Um snapshot declara qual espaço usou,
e a impressão do espaço entra na impressão dele.

---

## 2. A compatibilidade de prefixo

```
V2[0:75] == V1
```

Não «equivalente»: são **os mesmos objetos**, vindos de
`production_feature_catalog()`. O construtor do catálogo estendido confere isso
e recusa qualquer prefixo alterado.

Consequências práticas:

- as 75 primeiras chaves da V2 são as da V1, na mesma ordem;
- as impressões de cada uma são idênticas;
- os **valores** calculados são idênticos — a V2 chama o extrator da V1, e não
  uma cópia;
- a impressão do *snapshot* difere, porque o espaço difere. Isso é natural, e
  não defeito.

---

## 3. A ordem

```
  0- 74   as 75 da V1   (clock, score, manpower, discipline, substitutions,
                         rolling 1m/3m/5m/10m)
 75- 83   contexto pré-jogo
 84-104   mercado canônico
```

Dentro do contexto: intervalo (home, away, diff), depois contagem de 14 dias,
depois de 30 — as janelas seguem a ordem declarada na política.

Dentro do mercado: os sete mercados na ordem do catálogo, cada um com mediana,
IQR e suporte.

A ordem é **contrato**, e `list(keys) != sorted(keys)` é afirmado por teste.

---

## 4. As nove de contexto

```
ctx_same_comp_prev_gap_hours_{home|away|diff}     hours
ctx_same_comp_matches_14d_{home|away|diff}        count
ctx_same_comp_matches_30d_{home|away|diff}        count
```

Classe temporal `PRE_MATCH`: elas **não mudam com o corte**. Exigem apenas a
família `MATCH`.

Detalhes completos em `PRE_MATCH_CONTEXT_V1.md`.

---

## 5. As vinte e uma de mercado

```
market_{1x2_home|1x2_draw|1x2_away}_{median|iqr|support}
market_{totals_over_25|totals_under_25}_{median|iqr|support}
market_{btts_yes|btts_no}_{median|iqr|support}
```

Classe temporal `INTRA_MATCH_CAUSAL`: elas **evoluem com o corte**, ao
contrário do contexto. Exigem a família `ODDS`.

Detalhes completos em `CANONICAL_MARKET_FEATURES_V1.md`.

---

## 6. Exigências do espaço

```
obrigatórias   EVENT, LINEUP, MATCH
opcional       ODDS
```

`ODDS` ser **opcional** é o que permite um corpus sem mercado produzir snapshot
— com as vinte e uma dimensões indisponíveis na máscara. Torná-la obrigatória
recusaria o corpus inteiro por causa de uma família acessória.

`CorpusRequirement.optional_families` foi acrescentado neste PR e só aparece na
forma canônica **quando existe**. Um espaço sem opcionais produz exatamente o
documento que produzia antes do campo — e é isso que mantém a impressão dourada
da V1 intacta.

---

## 7. A V2 continua CRUA

```
normalization = NONE
```

Nenhuma das 105 definições declara `normalizer_key`, e nenhum caminho do motor
aplica normalizador. O runtime de ajuste existe (`ROBUST_NORMALIZATION_V1.md`) e
é um **segundo passo explícito** — a população científica de ajuste é o PR-05.5.

---

## 8. Identidade

Os parâmetros que entram na impressão das definições novas:

**contexto**

```
context_scope                SAME_COMPETITION
context_eligibility          PUBLISHED_RESULT
context_boundary             CLOSED_OPEN
context_policy_fingerprint   a impressão da HistoricalContextPolicy
kind                         PREV_KICKOFF_GAP_HOURS | MATCHES_IN_WINDOW
side                         HOME | AWAY | DIFFERENCE
lookback_days                14 | 30   (só nas contagens)
```

**mercado**

```
consensus_policy_fingerprint a impressão da MarketConsensusPolicy
kind                         MEDIAN | IQR | SUPPORT
market                       MATCH_RESULT_1X2 | TOTAL_GOALS | BOTH_TEAMS_TO_SCORE
market_line                  2.5 nos totais, null nos demais
selection                    HOME | DRAW | AWAY | OVER | UNDER | YES | NO
```

Trocar a janela de contexto de `(14, 30)` para `(7, 30)` muda as chaves **e** a
impressão do espaço. Trocar um limiar da política de consenso muda a impressão
de todas as features de mercado.

---

## 9. Documentos relacionados

- `RAW_FEATURE_CATALOG_V1.md` — as 75 herdadas, uma a uma
- `PRE_MATCH_CONTEXT_V1.md` — as nove de contexto
- `CANONICAL_MARKET_FEATURES_V1.md` — as vinte e uma de mercado
- `ROBUST_NORMALIZATION_V1.md` — o segundo passo, ainda não aplicado
- `MATCH_FEATURE_EXTRACTION.md` — como o snapshot é montado
- ADR-0030, ADR-0033, ADR-0034, ADR-0035
