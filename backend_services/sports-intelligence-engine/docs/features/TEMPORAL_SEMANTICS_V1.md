# Semântica temporal de features — V1

Como o motor decide **o que um modelo poderia legitimamente saber** num
instante. Implementado em **PR-05.1**.

---

## As duas réguas

```
EffectiveTime   quando o fato PERTENCE à realidade esportiva
                   «o gol aconteceu aos 63:21»

KnowledgeTime   quando o fato PODERIA SER CONHECIDO pelo sistema
                   «o provedor publicou 63:22; a correção chegou 64:10»
```

**Elas não são a mesma coisa, e a diferença é o assunto inteiro deste PR.** Um
replay histórico que aplica, aos 63:30, uma correção que só ficou conhecida às
64:10 produz um estado que nenhuma partida ao vivo jamais terá. O modelo
treinado nele aprende a comparar com um mundo que não existe.

```
HistoricalState_t  ~  InformationThatWouldHaveBeenAvailableLive_t
HistoricalState_t  ≠  RetrospectiveFinalTruth_t
```

**Elas também não se convertem uma na outra.** A posição na partida ordena o
que aconteceu DENTRO do jogo; o instante de parede ordena o que se soube FORA
dele. Converter exigiria saber o instante exato de cada minuto de jogo,
incluindo paralisação, VAR e intervalo — e o corpus não sabe. Um `as-of` pode
declarar as duas; cada fato é elegível pela régua que ele de fato tem.

---

## `FeatureAsOf` — o corte

```python
FeatureAsOf(
    match_id,
    position,           # MatchTimePoint: fase, minuto, acréscimo, desempate
    mode,               # AS_KNOWN | CANONICAL_FINAL
    knowledge_cutoff,   # instante de parede, quando o chamador sabe dizer
)
```

**`minute: int` não serve como contrato temporal** (§7, §8, §9):

| confusão | consequência |
|----------|--------------|
| `45+3` virando `48` | o terceiro minuto de acréscimo do 1º tempo confundido com o do 2º — momentos táticos opostos |
| minuto sem fase | o minuto 40 do 2º tempo comparado com o 40 do 1º |
| sem desempate | dois eventos no mesmo relógio sem ordem definida |

`MatchTimePoint` ordena por `(fase, minuto, acréscimo, sequência)`, e a ordem
das fases vem de `Period.order` — a mesma tabela que o registro canônico de
eventos usa.

**O corte é inclusivo** (`<=`): um estado «aos 63» inclui o que aconteceu aos
63. Quando o corte declara uma sequência, ele passa a ser sensível ao desempate
e corta no meio do minuto; quando não declara, o relógio inteiro entra. A
decisão é explícita porque as duas leituras são defensáveis, e a diferença
aparece exatamente nos empates.

---

## `TemporalAvailability` — como cada fato pode ser usado

| classe | significado |
|--------|-------------|
| `PRE_MATCH_KNOWN` | conhecido antes do apito — escalação, mando, competição |
| `OCCURRENCE_OBSERVABLE` | observável no instante em que acontece |
| `OBSERVED_AT_TIMESTAMP` | o corpus carrega o carimbo REAL de observação |
| `POST_MATCH_ONLY` | só existe depois do apito — resultado, agregado final |
| `RETROSPECTIVE_ONLY` | existe, e não há evidência de quando ficou disponível |
| `UNKNOWN` | nem a classe é conhecida |

### A classificação padrão, e a suposição que ela declara

```
MATCH_IDENTITY      PRE_MATCH_KNOWN
MATCH_RESULT        POST_MATCH_ONLY
FINAL_AGGREGATE     POST_MATCH_ONLY
LINEUP_INITIAL      PRE_MATCH_KNOWN
EVENT_ORIGINAL      OCCURRENCE_OBSERVABLE   ← a suposição
EVENT_REVISION      RETROSPECTIVE_ONLY      ← o conservadorismo
ODDS_OBSERVATION    OBSERVED_AT_TIMESTAMP
ODDS_CLOSING        UNKNOWN
```

**`EVENT_ORIGINAL = OCCURRENCE_OBSERVABLE` é a suposição mais forte do modelo,
e ela está à vista.** O corpus histórico não guarda quando o provedor publicou
cada evento — o PR-04.4.1 grava `ObservationTimes.at_once(ingestão)`, que é
outra coisa. Assumir que um gol é observável quando acontece é defensável (quem
assiste vê) e **ignora a latência real do provedor**.

Uma política mais estrita existe e é executável: `strict_observed()` exige
carimbo para todo fato intra-jogo. Sob ela, um corpus sem carimbos simplesmente
não produz feature intra-jogo — honesto e pouco útil, e é por isso que não é o
padrão. A escolha é versionada e impressa: dois snapshots calculados sob
políticas diferentes não se confundem.

**`EVENT_REVISION = RETROSPECTIVE_ONLY` é conservadora do outro lado.** A
correção existe no corpus, não há evidência de quando ficou disponível, e
aplicá-la retroativamente é o vazamento clássico. Quando a fonte de fato tem o
carimbo, ele entra por `EventKnowledge` e a comparação passa a ser objetiva.

---

## Os dois modos

```
AS_KNOWN          «o que se sabia aos 63 minutos»
CANONICAL_FINAL   «o que hoje sabemos que era verdade aos 63 minutos»
```

| | causalidade de OCORRÊNCIA | causalidade de CONHECIMENTO |
|---|---|---|
| `AS_KNOWN` | exigida | exigida |
| `CANONICAL_FINAL` | **exigida** | dispensada |

**`CANONICAL_FINAL` não é um passe livre.** Um gol aos 80 não faz parte de um
estado de 63 sob verdade nenhuma; o que ele dispensa é a prova de quando aquilo
foi sabido. Ele serve à auditoria e à análise retrospectiva — e um
`FeatureSpace` que se declare `live_comparable` **não constrói** com ele
(ADR-0029).

---

## Fail-closed

```
UnknownTemporalAvailability  ⇒  FailClosed
```

Quando a disponibilidade não pode ser provada e a feature exige causalidade
estrita, o resultado é `UNAVAILABLE` com motivo tipado. Nunca o fato «porque
provavelmente já era conhecido».

O guarda responde em **três** estados, e o terceiro é o que evita o chute:

```
ALLOWED   pode entrar
DENIED    existe, e é do futuro — ou de classe proibida no modo
UNKNOWN   não dá para provar
```

E `DENIED ≠ SOURCE_UNAVAILABLE`: «o fato existe e vem do futuro» e «o fato não
existe» produzem a mesma ausência no resultado e exigem investigações opostas.

---

## Relacionados

- [ADR-0029 — semântica temporal as-known](../architecture/adr/0029-feature-generation-uses-as-known-temporal-semantics.md)
- [Modelo de vazamento temporal](TEMPORAL_LEAKAGE_MODEL.md)
- [Contrato de feature](FEATURE_CONTRACT_V1.md)
