# Contexto pré-jogo — V1

> Nove features de **calendário**. Nem força de time, nem forma, nem confronto
> direto.

---

## 1. O que ele mede — e o que o nome admite

```
Context(M) = f(partidas anteriores da MESMA competição, kickoff < kickoff(M))
```

A pergunta natural é «quanto descanso o time teve». A resposta honesta que este
corpus sustenta é mais estreita: **quanto tempo desde o jogo anterior desta
mesma competição**.

Um time que jogou a Champions na quarta aparece aqui como se tivesse
descansado a semana inteira. Isso é uma limitação real, e a solução não é
disfarçá-la: é **nomear a feature pelo que ela mede**.

```
ctx_same_comp_prev_gap_hours_home     ✅  diz o escopo
rest_days_home                        ❌  promete o que não entrega
```

---

## 2. As nove features

| chave | unidade | significado |
|---|---|---|
| `ctx_same_comp_prev_gap_hours_home` | `hours` | horas entre este apito e o da partida anterior do mandante na mesma competição |
| `ctx_same_comp_prev_gap_hours_away` | `hours` | idem, visitante |
| `ctx_same_comp_prev_gap_hours_diff` | `hours` | mandante menos visitante |
| `ctx_same_comp_matches_14d_home` | `count` | partidas do mandante em `[T-14d, T)` |
| `ctx_same_comp_matches_14d_away` | `count` | idem, visitante |
| `ctx_same_comp_matches_14d_diff` | `count` | mandante menos visitante |
| `ctx_same_comp_matches_30d_home` | `count` | partidas do mandante em `[T-30d, T)` |
| `ctx_same_comp_matches_30d_away` | `count` | idem, visitante |
| `ctx_same_comp_matches_30d_diff` | `count` | mandante menos visitante |

`T` é o **apito inicial programado** da partida atual. O intervalo é medido de
apito a apito — o corpus não publica quando a partida anterior terminou.

---

## 3. Pré-jogo significa pré-jogo

Estas nove features são `PRE_MATCH`, e o valor é **o mesmo em todos os cortes**:

```
as_of 10'   →  ctx_same_comp_matches_14d_home = 1
as_of 30'   →  ctx_same_comp_matches_14d_home = 1
as_of 63'   →  ctx_same_comp_matches_14d_home = 1
```

Elas descrevem o que havia **antes** do apito. A fronteira é o kickoff da
partida atual, e não o `FeatureAsOf` — usar o corte intra-jogo faria uma
feature de calendário mudar durante o jogo, o que não significa nada.

---

## 4. A política

`HistoricalContextPolicy` é versionada e impressa. Ela declara as quatro
decisões que a pergunta esconde:

```
scope        SAME_COMPETITION
eligibility  PUBLISHED_RESULT
lookback     (14, 30) dias
boundary     CLOSED_OPEN — [T-w, T)
```

A impressão da política entra nos **parâmetros de cada definição de feature**,
e portanto na identidade dela. Trocar o escopo, a prova de conclusão ou as
janelas muda o que a feature mede — e a identidade muda junto.

`ALL_COMPETITIONS` existe no catálogo **para ser recusado**. Nomeá-lo é o que
permite negá-lo com mensagem em vez de não ter como expressá-lo.

---

## 5. O que prova que a partida anterior aconteceu

```
PUBLISHED_RESULT   está na versão + começou antes + o corpus publica o resultado
KICKOFF_BEFORE     está na versão + começou antes
```

A V1 usa `PUBLISHED_RESULT`. A alternativa contaria uma partida adiada como
jogada.

**O `MatchResult` da partida ANTERIOR não é vazamento.** Ela terminou antes de
a atual começar, então o resultado dela já era conhecido no apito inicial da
atual.

**Mas o VALOR dele não vira feature.** O tipo `PriorMatchRef` carrega apenas
`(kickoff, match_id)` — não há por onde somar pontos, gols ou vitórias. Isso é
estrutural, e há um teste que afirma exatamente esses dois campos.

---

## 6. As fronteiras

```
Window(T, w) = [T - w, T)
```

| posição | entra? |
|---|---|
| exatamente `T - 14d` | **sim** — o início é inclusivo |
| um segundo antes de `T - 14d` | não |
| exatamente `T` (a partida atual) | **nunca** |
| depois de `T` | recusado pelo tipo |

Uma partida posterior ao apito no contexto **levanta**. Ela não é filtrada em
silêncio: um contexto plausível de um calendário que não existia é pior que um
erro, porque nada denuncia.

---

## 7. Zero observado ≠ histórico ausente

Este é o ponto mais sutil do contexto, e é o caso da **primeira rodada de
qualquer corpus**.

```
o corpus alcança T-14d   e o time não jogou   →  0  AVAILABLE
o corpus começa em T-3d                       →  INSUFFICIENT_COVERAGE
```

Os dois produziriam `0`. O segundo seria uma afirmação sobre o mundo feita a
partir de uma limitação do arquivo — e o modelo aprenderia que quem joga a
primeira rodada está sempre descansado.

`ContextCoverage` carrega o instante da **primeira partida daquela competição
naquela versão publicada**. É contra ele que a janela é conferida.

O mesmo vale para o intervalo:

| situação | disponibilidade |
|---|---|
| há partida anterior | `AVAILABLE` |
| o corpus alcança o passado e o time não jogou | `SOURCE_UNAVAILABLE` |
| o corpus não alcança instante anterior nenhum | `INSUFFICIENT_COVERAGE` |

E as diferenças só existem quando **os dois lados** existem. Nunca se completa
o lado ausente com zero: a diferença teria o sinal e a magnitude de uma
vantagem que ninguém mediu.

---

## 8. A pertinência decide, não a existência

Uma partida anterior só conta se pertencer à **mesma
`HistoricalCanonicalDatasetVersion`**. Existir na tabela `matches` não basta.

O E2E prova isso da forma mais direta possível: as partidas anteriores **estão
fisicamente no PostgreSQL**, uma segunda versão publicada não as inclui, e o
contexto daquela versão diz que não sabe.

Sem essa regra, o contexto passaria a depender de quando o build rodou em vez
de qual versão foi pedida — e dois cálculos sobre «o corpus 1.0» dariam
resultados diferentes em datas diferentes.

---

## 9. A leitura

`HistoricalContextSourcePort`, com duas responsabilidades separadas por custo:

```
coverage(version_id)                    uma vez por VERSÃO — memorizada
load(version_id, match_ids, policy)     duas consultas por LOTE
```

As duas consultas por lote:

1. **a janela** — a partida atual e as anteriores dentro do maior retrospecto,
   na mesma varredura. O `LEFT JOIN` é o que faz a partida atual aparecer mesmo
   sem anteriores, dispensando uma terceira consulta.
2. **a última** — a anterior mais recente, **sem limite inferior**. Ela pode
   ter três meses (parada de seleções, calendário irregular), e a janela de
   trinta dias não a encontraria.

Uma consulta por partida daria vinte mil consultas para dez mil partidas. O
benchmark afirma o número exato.

---

## 10. O que este contexto NÃO tem

| ausente | por quê |
|---|---|
| pontos recentes, aproveitamento | exige decidir janela, peso e o que fazer com jogo adiado |
| gols marcados/sofridos em forma | idem, e mistura ataque com calendário |
| Elo, power ranking | exige população histórica e ajuste versionado |
| confronto direto (H2H) | amostra pequena, e a decisão de quantos jogos é própria |
| descanso real entre competições | exige decidir quais torneios compõem a carga de cada time |

Cada uma é um sinal legítimo com uma decisão estatística por trás. Nenhuma
delas cabe dentro de uma feature de calendário sem que a feature passe a medir
outra coisa.

---

## 11. Documentos relacionados

- ADR-0033 — a decisão e as alternativas rejeitadas
- `RAW_FEATURE_CATALOG_V2.md` — o espaço estendido inteiro
- `CANONICAL_MARKET_FEATURES_V1.md` — a outra família nova da V2
- `HISTORICAL_MATCH_STATE_V1.md` — a fonte das features de estado
