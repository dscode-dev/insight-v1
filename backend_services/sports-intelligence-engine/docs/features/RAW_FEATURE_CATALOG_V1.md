# Catálogo de features CRUAS — `MATCH_STATE_RAW_V1`

> 75 definições. Sem normalização, sem composição, sem interpretação.
>
> Espaço: `MATCH_STATE_RAW_V1@v1.0`
> Impressão: `384038f2b11a754873451361e49e76d0f999ca653d6ac744078da30670545172`

---

## 1. O que este espaço é

```
FeatureSnapshot_t = Extract(HistoricalMatchState_t, EffectiveEvents_≤t, MATCH_STATE_RAW_V1)
```

Ele responde **«quais sinais matemáticos básicos estavam presentes no estado
atual e nos últimos 1, 3, 5 e 10 minutos»**. Ele **não** responde «o que esses
sinais significam» — interpretação, normalização e comparação histórica são
fases seguintes.

| propriedade | valor |
|---|---|
| normalização | **NENHUMA** — nenhuma definição declara `normalizer_key` |
| classe temporal | `INTRA_MATCH_CAUSAL` em todas as 75 |
| modo temporal | `AS_KNOWN` |
| comparável ao vivo | sim |
| exige do corpus | `EVENT`, `LINEUP` |
| versão de cada definição | `v1.0` |

---

## 2. A ordem

A ordem **é conteúdo**: ela é a ordem dos eixos do vetor futuro, e entra na
impressão do espaço.

```
 0- 2  clock
 3- 5  score
 6- 8  manpower
 9-12  discipline
13-14  substitutions
15-29  janela  1m   (5 famílias × home/away/diff)
30-44  janela  3m
45-59  janela  5m
60-74  janela 10m
```

Dentro de cada janela: `shots`, `shots_on_target`, `xg`, `goals`, `corners`.
Dentro de cada família: `home`, `away`, `diff`.

**Não é ordem alfabética.** `list(keys) != sorted(keys)`, e há um teste que
afirma isso — para que a ordem não passe a ser decidida pela grafia dos nomes.

---

## 3. Features derivadas do estado

Todas extraídas de `HistoricalMatchState`, **nunca recontadas dos eventos**
(§36): o estado já reduziu gols, cartões e substituições, e uma segunda
contagem divergiria da primeira no primeiro caso degradado.

### 3.1 `clock`

| chave | unidade | significado | disponibilidade |
|---|---|---|---|
| `clock_period_order` | `period_index` | posição da fase na ordem canônica do jogo | sempre |
| `clock_minute` | `minutes` | minuto do corte, **sem** os acréscimos | sempre |
| `clock_stoppage` | `minutes` | acréscimos do corte, separados | sempre |

**Por que três e não um «minuto decorrido».** `45+3` não é `48`. Achatá-los
confundiria o terceiro minuto de acréscimo do primeiro tempo com o terceiro
minuto do segundo — momentos táticos opostos. As três dimensões preservam a
distinção; quem quiser somar, soma.

Elas **não exigem família nenhuma**: o corte é dado de entrada, e o relógio
dele é conhecido por construção.

### 3.2 `score`

| chave | unidade | escopo | fonte |
|---|---|---|---|
| `score_home` | `goals` | `HOME_TEAM` | `ScoreState.home` |
| `score_away` | `goals` | `AWAY_TEAM` | `ScoreState.away` |
| `score_difference` | `goals` | `MATCH` | depende das duas acima |

Somam tempo normal **e** prorrogação; **nunca** a disputa de pênaltis. Exigem
`EVENT` — o placar do estado é reduzido de gols efetivos, e não do
`MatchResult`.

### 3.3 `manpower`

| chave | unidade | escopo |
|---|---|---|
| `players_on_field_home` | `players` | `HOME_TEAM` |
| `players_on_field_away` | `players` | `AWAY_TEAM` |
| `manpower_difference` | `players` | `MATCH` |

Exigem `LINEUP` **e** `EVENT`: a escalação dá a base, os eventos dão as
substituições e expulsões. **Sem escalação não se assume onze** — as três ficam
indisponíveis.

### 3.4 `discipline`

| chave | unidade | escopo |
|---|---|---|
| `yellow_cards_home` / `_away` | `count` | time |
| `dismissals_home` / `_away` | `count` | time |

`SECOND_YELLOW` conta como amarelo **e** como expulsão — a semântica do
PR-05.2, herdada sem reinterpretação. **Não há feature de diferença aqui**, e a
ausência é deliberada: a vantagem numérica já está em `manpower_difference`, e
uma segunda medida da mesma coisa convidaria as duas a divergirem.

### 3.5 `substitutions`

| chave | unidade | escopo |
|---|---|---|
| `substitutions_home` / `_away` | `count` | time |

Substituições **aplicadas** até o corte, contadas de `SubstitutionState`.

---

## 4. Famílias móveis

Cinco famílias × quatro janelas × (`home`, `away`, `diff`) = **60 definições**.

| família | prefixo | tipo canônico | unidade | agregação |
|---|---|---|---|---|
| `SHOT` | `shots` | `EventType.SHOT` | `count` | `COUNT` |
| `SHOT_ON_TARGET` | `shots_on_target` | `EventType.SHOT` | `count` | `COUNT` |
| `XG` | `xg` | `EventType.SHOT` | `expected_goals` | `SUM` |
| `GOAL` | `goals` | `EventType.GOAL` | `goals` | `COUNT` |
| `CORNER` | `corners` | `EventType.CORNER` | `count` | `COUNT` |

Chave: `{prefixo}_{home|away|diff}_{1m|3m|5m|10m}`.
Exemplos: `shots_home_5m`, `xg_diff_10m`, `shots_on_target_away_1m`.

### 4.1 `shots` conta `SHOT`, e não `SHOT` mais `GOAL`

A taxonomia é fechada e declarada: um gol é `EventType.GOAL`. Assumir que todo
gol também é uma finalização **somaria os dois** quando o provedor emite os dois
para o mesmo lance.

A escolha **subconta** em provedores que só emitem `GOAL` — e subcontar uma
coisa declarada é visível, enquanto contar duas vezes a mesma finalização não
é. Quem quiser «finalizações totais» soma `shots_*` com `goals_*`: as duas
estão no espaço.

### 4.2 `shots_on_target`

No alvo = `ShotOutcome.GOAL` ou `SAVED`. **Trave e bloqueio não contam** —
convenção estatística padrão: nenhum dos dois exigiu defesa.

**Se qualquer finalização da janela não tem `ShotDetail`**, a feature fica
`PARTIAL_INPUT`. Contar só as classificáveis e chamar o resultado de total
produziria um número menor que o real com cara de completo.

`shots_*` da mesma janela **continua disponível**: a independência vale dentro
da família.

### 4.3 `xg`

Soma dos xG **publicados pela fonte**. Nunca calculado aqui.

| situação | resultado |
|---|---|
| nenhuma finalização na janela | `0` `AVAILABLE` |
| todas com xG, uma delas `0.0` | soma inclui o zero — `0.0` é observação legítima |
| **qualquer** finalização sem xG | `PARTIAL_INPUT` |

**Política conservadora por decisão.** Somar as conhecidas e omitir o resto
produziria um valor sistematicamente menor, e nada no número diria isso.

**A soma é `Decimal`.** `0.1 + 0.2` em binário não dá `0.3`, e a diferença
entraria na impressão da feature. Acumulação em `Decimal`, quantização fixa em
6 casas, conversão única no fim.

### 4.4 `goals` e `corners`

Contagens puras. O gol é creditado ao `team_id` **do evento** — a mesma
semântica de gol contra do PR-05.2, herdada sem reinterpretação. Escanteio não
tem cálculo de perigo.

### 4.5 Diferenças

`home - away`, sempre nessa ordem. **Só existem quando os dois lados são
afirmáveis.** Um lado indisponível ⇒ diferença indisponível — nunca se preenche
o ausente com zero: a diferença teria o sinal e a magnitude de uma vantagem que
ninguém mediu.

A procedência da diferença é a **união** das duas bases.

---

## 5. Matriz de disponibilidade

| família | exige | zero é válido? | entrada parcial |
|---|---|---|---|
| `clock` | nada | — | não se aplica |
| `score` | `ScoreState` afirmável (`EVENT`) | sim (0-0 observado) | — |
| `manpower` | `OnFieldState` afirmável (`LINEUP` + `EVENT`) | não (dez é legítimo, zero não) | lado degradado ⇒ indisponível |
| `discipline` | `DisciplinaryState` afirmável (`EVENT`) | **sim** — zero cartão com `EVENT` publicado é fato | — |
| `substitutions` | `SubstitutionState` afirmável (`EVENT`) | sim | — |
| móveis (todas) | `EVENT` publicado **e** história completa **e** período com cronômetro | sim, quando a ausência é observável | ver abaixo |
| `shots_on_target` | idem + `ShotDetail` em todas as finalizações da janela | sim | `PARTIAL_INPUT` |
| `xg` | idem + xG em todas as finalizações da janela | sim | `PARTIAL_INPUT` |
| diferenças | os dois lados afirmáveis | herda | herda |

**Estados de indisponibilidade usados:**

```
NOT_DECLARED            a versão do corpus não publica EVENT
INSUFFICIENT_COVERAGE   a história de eventos é incompleta para o corte
NOT_APPLICABLE          o período do corte não tem cronômetro
PARTIAL_INPUT           a fonte veio, e veio incompleta
SOURCE_UNAVAILABLE      herdado do componente de estado
```

**`ObservedZero ≠ Unavailable` é absoluto.** `shots_home_5m = 0 AVAILABLE`
significa «não houve finalização»; `shots_home_5m = ∅ NOT_DECLARED` significa
«não se sabe». Os dois «valem 0» para quem não olha a máscara, e um consumidor
que os confundisse aprenderia que partidas sem cobertura são partidas sem
finalização.

---

## 6. Procedência

| tipo de feature | procedência |
|---|---|
| `clock` | derivada do corte declarado; sem fatos contribuintes |
| `score`, `discipline`, `manpower` | a amostra do componente correspondente do estado |
| `substitutions` | os ids das substituições aplicadas daquele time |
| móveis | os ids dos eventos da janela |
| diferenças | união das duas bases |

Classe: `DERIVED_FROM_CANONICAL` em todas. Contagem exata, amostra limitada a
16, digest do conjunto **inteiro** — ordem-independente.

**Uma feature zero tem `count = 0` e digest vazio, e é `AVAILABLE` com
`value = 0`.** É o par (disponibilidade, valor) que a separa de uma ausente:
`ComputedFeature` estruturalmente proíbe «disponível sem valor» e «indisponível
com valor».

---

## 7. O que este catálogo NÃO tem

| ausente | por quê |
|---|---|
| `passes_*` | contagem altamente sensível à granularidade do provedor; dois provedores dão números incomparáveis |
| `events_*` (total) | mede a taxonomia da fonte, não o jogo |
| `pressure_*` | `EventType.PRESSURE` existir não autoriza um score de pressão — isso é composição |
| `recovery_rate` | idem |
| `field_tilt`, `momentum` | composições, e cada uma é uma decisão de modelagem |
| `elo`, `team_strength`, `player_influence` | exigem população histórica e ajuste versionado |
| features de odds | um espaço de dimensão fixa não pode depender de quantas casas de aposta existem; antes é preciso mercado canônico, contrato de seleção e semântica de consenso |
| qualquer coisa normalizada | o contrato existe desde o PR-05.1 e continua sem execução |

Cada ausência é uma decisão registrada, e há testes de arquitetura que falham
se alguma delas aparecer por conveniência.

---

## 8. Identidade

```
FeatureIdentity      = key + version + fingerprint(conteúdo)
FeatureSpaceIdentity = nome + versão + fingerprint(ordem + conteúdo)
```

Os parâmetros que entram na impressão de uma feature móvel:

```
aggregation           COUNT | SUM
canonical_event_type  SHOT | GOAL | CORNER
family                SHOT | SHOT_ON_TARGET | XG | GOAL | CORNER
side                  HOME | AWAY | DIFFERENCE
window_scope          PERIOD_LOCAL
window_seconds        60 | 180 | 300 | 600
```

Trocar a janela de 5 para 10 muda a impressão. O registro de produção **recusa**
duas definições com a mesma chave e versão e conteúdos diferentes — a
ambiguidade mais cara, porque quem comparasse dois números acharia que comparou
a mesma feature.

Impressões douradas de referência estão em
`tests/unit/test_feature_catalog.py`; mudá-las exige uma decisão sobre versão.

---

## 9. Documentos relacionados

- `ROLLING_WINDOW_SEMANTICS_V1.md` — a régua das janelas
- `MATCH_FEATURE_EXTRACTION.md` — como o snapshot é montado
- `FEATURE_CONTRACT_V1.md` — o contrato de `FeatureDefinition`
- `FEATURE_SPACE_V1.md` — por que a ordem é identidade
- `HISTORICAL_MATCH_STATE_V1.md` — a fonte das features de estado
- ADR-0030, ADR-0032
