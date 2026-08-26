# `LIVE_COMPARABLE_MINUTE_GRID_V1` — quais cortes cada partida contribui

**Status:** vigente desde o PR-05.5.1 · ver ADR-0036

Uma partida vira quantas linhas do dataset histórico? A resposta define o
tamanho do conjunto, o custo de construí-lo e — silenciosamente — o que o motor
consegue comparar em produção.

---

## 1. O critério

**A grade é o conjunto dos cortes que a produção consegue reproduzir.**

Ao vivo, o motor recebe um estado num minuto de relógio e pergunta «que estados
históricos se parecem com este?». Um corte histórico que **não possa existir ao
vivo** é um corte que nunca será consultado — e que, pior, entra na população
que ajusta escalas e define vizinhança.

---

## 2. A grade

```
PRE_MATCH                      1 corte     índice  0
FIRST_HALF   minutos 1..45    45 cortes    índices 1..45
SECOND_HALF  minutos 46..90   45 cortes    índices 46..90
                              ─────────
                              91 cortes por partida
```

O **índice** é a coordenada estável do corte dentro da partida: `0` é sempre o
pré-jogo, `63` é sempre o minuto 63. É por ele que duas partidas se alinham
numa comparação coluna a coluna sem que ninguém precise reinterpretar
`(período, minuto)`.

A prorrogação acrescenta trinta cortes — `EXTRA_TIME_FIRST` 91..105 e
`EXTRA_TIME_SECOND` 106..120 — **quando, e somente quando**, o corpus prova que
ela aconteceu.

---

## 3. O que fica de fora, e por quê

| o que | motivo (`GridExclusionReason`) |
| --- | --- |
| `FIRST_HALF 45+n` | `STOPPAGE_TIME_NOT_UNIFORM` |
| `SECOND_HALF 90+n` | `STOPPAGE_TIME_NOT_UNIFORM` |
| `FIRST_HALF` minuto 0 | `MINUTE_ZERO_IS_PRE_MATCH` |
| `HALF_TIME` | `HALF_TIME_HAS_NO_CLOCK` |
| `EXTRA_TIME_BREAK` | `HALF_TIME_HAS_NO_CLOCK` |
| `FULL_TIME` | `POST_MATCH_KNOWS_THE_ANSWER` |
| `PENALTY_SHOOTOUT` | `SHOOTOUT_HAS_NO_MATCH_CLOCK` |
| prorrogação sem prova | `EXTRA_TIME_WITHOUT_EVIDENCE` |

**O acréscimo.** O corpus não publica **quantos** minutos de acréscimo houve.
`45+1` existe num jogo e não existe noutro, e uma grade que o incluísse deixaria
de ser a mesma grade entre partidas — que é a única propriedade que a torna
útil.

**O intervalo.** Nenhum relógio ao vivo marca «intervalo, minuto 3».

**O pós-jogo.** `FULL_TIME` tem o placar final dentro. Um snapshot ali é treinar
com a resposta.

**Os pênaltis.** Não têm minuto de jogo, e as janelas móveis do
`MATCH_STATE_RAW_V2` são todas definidas sobre minutos.

**O minuto zero.** Ele *é* o pré-jogo. Materializar os dois produziria duas
linhas para o mesmo estado sob chaves diferentes.

O catálogo de exclusões vai **dentro do manifesto**: «o que não está aqui» é
pergunta de manifesto tanto quanto «o que está».

---

## 4. A prorrogação exige prova canônica

`ExtraTimeRule.ONLY_WITH_CANONICAL_EVIDENCE`, e `ALWAYS` **não existe** no enum.

Duas fontes de prova, em ordem declarada para que a resposta seja
determinística:

1. um `CanonicalMatchEvent` carimbado em `EXTRA_TIME_FIRST` ou
   `EXTRA_TIME_SECOND` → `CANONICAL_EVENT_IN_EXTRA_TIME`;
2. um `MatchResult` com `extra_time` preenchido →
   `MATCH_RESULT_EXTRA_TIME_SCORE`.

Sem prova, não há prorrogação. Materializar 91..120 «por garantia» inventaria
trinta linhas de estado para cada jogo que terminou aos 90 — e elas entrariam na
população que ajusta escalas.

`stage` **não é prova**: um mata-mata pode ter sido decidido no tempo normal.

---

## 5. O corte de conhecimento

| corte | `knowledge_cutoff` |
| --- | --- |
| `PRE_MATCH` | o **pontapé canônico** (`actual_kickoff` ou `scheduled_kickoff`) |
| qualquer minuto do jogo | `None` |

**Por que o intra-jogo não tem instante.** A tentação é `kickoff + minuto`:
parece o carimbo de parede daquele minuto do jogo e é uma **fabricação** — ela
ignora o intervalo, os acréscimos e as interrupções, e erra por dez a vinte
minutos exatamente nos jogos mais irregulares. Um corte de conhecimento
fabricado é pior que corte nenhum, porque **parece prova**.

A causalidade intra-jogo é sustentada pela **posição** (`MatchTimePoint`), que o
corpus publica de verdade.

**Por que o pré-jogo tem.** «Antes do apito» é uma afirmação de parede que o
corpus sustenta. Usá-la impede que uma cotação publicada depois do apito entre
num snapshot rotulado como pré-jogo.

---

## 6. O pontapé canônico

```python
canonical_kickoff(match) = match.actual_kickoff or match.scheduled_kickoff
```

**Um só, e definido num lugar só.** A grade usa esse instante para o corte
pré-jogo; a divisão usa o mesmo para decidir a metade. Se cada uma usasse um, uma
partida adiada cairia numa metade e teria o corte pré-jogo carimbado na outra —
e o vazamento seria por horário, que é o tipo que ninguém procura.

---

## 7. A identidade da grade

`SnapshotGridPolicy` é versionada e impressa. Duas construções sob grades
diferentes **não são comparáveis** — uma tem 91 linhas por partida e a outra tem
19 —, e a impressão é o que impede a diferença de passar despercebida no
manifesto.

A impressão cobre: nome, versão, modo temporal, limites dos dois tempos, regra
de prorrogação, regra de corte pré-jogo e o **catálogo de exclusões**.

`TemporalMode` diferente de `AS_KNOWN` é recusado no construtor: a
comparabilidade ao vivo exige `AS_KNOWN`, e qualquer outro modo produziria uma
população que a produção nunca consegue reproduzir.

---

## 8. O que esta decisão NÃO fecha

Grades mais finas (trinta segundos), grades orientadas a evento («o estado
imediatamente antes de cada finalização») e cortes de acréscimo continuam
possíveis — cada uma como **política nova, com nome e versão próprios**. O que
não é possível é mudar esta e manter o nome.

---

## Referências

- ADR-0036 — a grade é comparável ao vivo, e não exaustiva
- ADR-0031 — o estado histórico é reconstruído e nunca armazenado
- `docs/features/FEATURE_DATASET_SPLIT_V1.md`
- `docs/features/HISTORICAL_FEATURE_DATASET_V1.md`
- `src/sports_intelligence/domain/features/dataset/grid.py`
