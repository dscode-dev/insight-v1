# `HistoricalMatchState` v1 — o contrato

> **O que ele é:** a representação ESTRUTURAL e tipada de como uma partida
> estava num ponto do tempo, reconstruída a partir do corpus publicado.
>
> **O que ele não é:** um vetor. `MatchStateVector` é outra coisa, vem depois,
> e é derivado deste.

```
HistoricalMatchState_t = Reduce(InitialState, EffectiveCanonicalFacts<=t)
```

---

## 1. Por que estado e vetor são coisas diferentes

| | `HistoricalMatchState` | `MatchStateVector` |
|---|---|---|
| natureza | estrutural e tipada | matemática |
| forma | placar, elenco, cartões, cotações | lista de números com eixos fixos |
| disponibilidade | por componente | máscara por dimensão |
| existe hoje | sim | **não** |

Fundi-los seria conveniente e caro. Um vetor precisa de eixos ordenados,
normalização declarada e população de referência — três decisões que pertencem
ao espaço de features, não ao fato. Um estado precisa dizer «não sei» sobre uma
parte sem invalidar o resto, e um `float` não sabe dizer isso.

---

## 2. A anatomia

```python
HistoricalMatchState(
    identity,        # de qual partida, competição, temporada e times
    context,         # código da competição, temporada, fase, mando, local, horário
    as_of,           # o corte: posição na partida, modo temporal, corte de conhecimento
    source,          # a versão do corpus e a impressão dela
    policy_version,  # a política de disponibilidade temporal aplicada
    policy_fingerprint,
    score,           # tempo normal · prorrogação · disputa de pênaltis
    on_field,        # quem está em campo, por time
    discipline,      # amarelos, expulsões, quem foi expulso
    substitutions,   # as substituições APLICADAS até o corte
    events,          # contagem efetiva, último evento, digest do conjunto
    odds,            # a ÚLTIMA cotação conhecida de cada fluxo
    provenance,      # de onde veio cada componente
    issues,          # o que deu errado, tipado
)
```

### 2.1 O placar tem três compartimentos

```
regular      o tempo normal
extra_time   a prorrogação
shootout     a disputa de pênaltis
```

`home` e `away` somam **normal + prorrogação**, e nunca a disputa. «2-1, 4-3
nos pênaltis» são dois resultados; somá-los produziria 6-4, que não aconteceu.

### 2.2 O crédito do gol é do time do EVENTO

O modelo canônico não marca gol contra: `EventType` não tem `OWN_GOAL` e
`ShotDetail` não tem indicador. O que existe é o `team_id` do evento, e ele é o
time **a quem o ponto é creditado**. Deduzir o lado pelo time do jogador
inverteria o placar exatamente nos gols contra.

Quando o `team_id` não corresponde a nenhum dos dois times da partida, o placar
inteiro fica `SOURCE_UNAVAILABLE` e um `GOAL_TEAM_UNRESOLVED` é registrado.
Somar num lado ao acaso seria pior que não somar.

### 2.3 Onze é um teto, e nunca um alvo

Menos de onze é legítimo — foi expulsão. Mais de onze é conflito de estado, e o
tipo recusa. A lista NÃO é cortada para caber: escolher quem sai seria inventar
a resposta.

---

## 3. A identidade

```
fingerprint = sha256(
    algoritmo · as_of · disponibilidade · contexto · disciplina · eventos ·
    identidade · problemas · odds · campo · procedência · placar · origem ·
    substituições · política
)
```

**O que NÃO entra:** id de execução, carimbo de criação, id de processo, id de
linha de banco. Eles mudam entre duas reconstruções do MESMO estado, e um
estado que mudasse de identidade por ter sido recalculado não serviria para
comparar nada.

**A procedência ENTRA, e é uma decisão.** Dois estados com o mesmo placar
obtido de gols diferentes não são o mesmo estado — a coincidência numérica não
os torna iguais.

**A origem ENTRA.** Se o corpus mudar, a identidade muda mesmo que o estado
observável pareça igual. O «parece igual» seria coincidência.

Algoritmo declarado: `match-state-sha256-v1`. Dois hex de 64 caracteres
produzidos por construções diferentes são indistinguíveis, e por isso o nome
viaja junto.

---

## 4. Os problemas são tipados, e não consertados

Quando os fatos discordam, o motor **não escolhe**. Uma substituição cujo
jogador não está em campo pode ser evento fora de ordem, escalação incompleta
ou erro da fonte — e as três exigem ações diferentes. Reparar em silêncio
produziria um estado plausível e falso, que é o pior resultado possível porque
nada denuncia.

| código | o que aconteceu |
|---|---|
| `INCOMPLETE_EVENT_HISTORY` | a cobertura não prova a história desde o início |
| `LINEUP_UNAVAILABLE` | a versão não publica escalação para esta partida |
| `LINEUP_INCOMPLETE` | a escalação existe e não tem onze titulares |
| `LINEUP_DUPLICATE_PLAYER` | o mesmo jogador duas vezes no mesmo time |
| `PLAYER_IN_BOTH_TEAMS` | o mesmo jogador nos dois times |
| `SUBSTITUTION_PLAYER_NOT_ON_FIELD` | quem sai não estava em campo |
| `SUBSTITUTION_PLAYER_ALREADY_ON_FIELD` | quem entra já estava em campo |
| `SUBSTITUTION_WITHOUT_PLAYERS` | a substituição não diz quem sai e quem entra |
| `DISMISSAL_PLAYER_NOT_ON_FIELD` | o expulso não estava em campo |
| `DISMISSAL_PLAYER_UNKNOWN` | o cartão não identifica cor ou jogador |
| `ON_FIELD_OVER_ELEVEN` | a transição resultaria em doze |
| `GOAL_TEAM_UNRESOLVED` | o gol é de um time que não joga esta partida |
| `SCORE_RESULT_MISMATCH` | o placar reconstruído difere do resultado publicado |
| `ODDS_TEMPORAL_UNKNOWN` | há cotação e não dá para provar que era conhecida |

**Duas severidades:**

- `DEGRADED` — um componente ficou indisponível.
- `NOTED` — o estado está inteiro e alguém precisa saber de algo. O placar que
  não bate com o resultado final é `NOTED`: ele não torna o estado dos 63
  minutos menos confiável.

---

## 5. O que o estado NÃO faz

- **Não calcula feature.** Nada de janela móvel, pressão, momentum, força de
  time, influência de jogador ou grafo tático. Isso é PR-05.3, e cada um deles
  precisa de definição, versão, população e normalizador declarados.
- **Não é normalizado.** Normalização é execução de um contrato do PR-05.1, e
  nenhum PR a executa ainda.
- **Não resolve identidade.** Os identificadores vêm do corpus como estão. Nem
  clube atual de jogador, nem fusão de nomes.
- **Não persiste.** Ver ADR-0031.
- **Não usa o `MatchResult` para formar o placar.** Ele serve à conferência
  pós-jogo, e só a ela.

---

## 6. Documentos relacionados

- `MATCH_STATE_RECONSTRUCTION.md` — como a reconstrução funciona, passo a passo
- `STATE_COMPONENT_AVAILABILITY.md` — o modelo de disponibilidade por componente
- `TEMPORAL_SEMANTICS_V1.md` — `EffectiveTime ≠ KnowledgeTime`
- `TEMPORAL_LEAKAGE_MODEL.md` — o guarda que decide o que é elegível
- ADR-0031 — por que o estado é reconstruído e nunca armazenado
