# A reconstrução de estado, passo a passo

> Como `HistoricalMatchState` sai do corpus publicado. O que cada camada
> decide, e o que ela deliberadamente não decide.

---

## 1. O fluxo

```
corpus publicado
      │
      ▼
┌──────────────────────────────────────────────────────────────┐
│ APLICAÇÃO — a única camada com I/O                           │
│                                                              │
│   PostgresHistoricalMatchStateSource.load(version, ids)      │
│     5 consultas POR LOTE:                                    │
│       membros + partidas + contexto                          │
│       escalações                                             │
│       eventos (pela PERTINÊNCIA da versão)                   │
│       cotações                                               │
│       resultados                                             │
│                                                              │
│   BuildHistoricalMatchState  /  BuildHistoricalMatchStates   │
└──────────────────────────────────────────────────────────────┘
      │  CanonicalMatchStateInput (tipado, sem linha de banco)
      ▼
┌──────────────────────────────────────────────────────────────┐
│ DOMÍNIO — puro, sem I/O, sem relógio, sem sorteio            │
│                                                              │
│   1. valida a partida         fato de outro jogo é ERRO      │
│   2. projeta os eventos       EffectiveEventProjection       │
│   3. filtra as cotações       TemporalLeakageGuard           │
│   4. monta o estado inicial   placar e escalação             │
│   5. reduz os eventos         StateReducer                   │
│   6. fecha a disponibilidade  por componente                 │
│   7. monta a procedência      limitada, com digest           │
│   8. imprime                  determinístico                 │
└──────────────────────────────────────────────────────────────┘
      │
      ▼
HistoricalMatchState + issues
```

---

## 2. A leitura parte da PERTINÊNCIA

`matches`, `canonical_match_events` e `canonical_odds_observations` são
**globais**: contêm tudo que qualquer build já escreveu. O que uma versão
publica está em `historical_canonical_members` e
`historical_canonical_event_members`.

Ler o registro canônico direto traria eventos que aquele corpus nunca publicou
— e o estado passaria a depender de **quando o build rodou**, em vez de **qual
versão foi pedida**. É a diferença entre um resultado reproduzível e um que
muda sozinho.

A `included_families` do membro é o que distingue «zero cartões» de «sem
eventos publicados». Sem ela, a tabela de eventos vazia teria duas leituras
possíveis e nenhuma forma de escolher.

### 2.1 Cinco consultas por lote, e nunca por partida

Com N+1 seriam cinco por partida — vinte e cinco mil consultas para cinco mil
partidas. O benchmark de escala afirma o número exato (`lotes × 5`), e não só a
tendência: se alguém acrescentar uma sexta consulta, o teste diz. A sexta pode
ser legítima, desde que seja uma decisão e não um acidente.

---

## 3. A projeção decide o que é EFETIVO

O reducer **não** decide isso. Gol cancelado não chega até ele; correção ainda
não conhecida não chega até ele. Quem decide é a `EffectiveEventProjection` do
PR-05.1, e reimplementar revisão neste módulo criaria uma segunda autoridade
sobre a mesma pergunta — que divergiria da primeira no primeiro caso difícil,
que é justamente o que ninguém testa.

```
candidatos (tudo que a versão publica)
      │  EffectiveEventProjection.project(as_of, knowledge)
      ▼
efetivos (o que se sabia naquele corte, sob aquela política)
```

Isso vale para as duas réguas:

- **posição na partida** — o gol dos 70 não entra num estado de 63;
- **relógio de parede** — a correção conhecida às 19:52 não entra num replay
  de 19:50.

---

## 4. O estado inicial

**`0-0` não é o padrão universal.** Ele é o placar de uma partida cuja história
de eventos começa no apito inicial. Quando a família `EVENT` não é publicada,
«zero a zero» é uma afirmação que ninguém pode fazer — e o placar nasce
`NOT_DECLARED`, com `INCOMPLETE_EVENT_HISTORY` registrado.

**A escalação inicial é a base do campo, e não é mutada.** Ela é fato publicado
e imutável; o que muda é o estado em campo, que nasce dela e segue o próprio
caminho.

**Escalação parcial não se completa.** Dez titulares declarados não viram onze
por conveniência: afirmar o campo a partir deles produziria um elenco que nunca
existiu. O lado fica `SOURCE_UNAVAILABLE`, e o outro lado continua afirmável.

---

## 5. A redução

O despacho é por **efeito estrutural declarado**, e não por comparação de
string. A classificação `EventType → StructuralEffect` é um mapa fechado e
exaustivo: um tipo novo sem classificação faz o módulo falhar **na importação**.

```
NO_STRUCTURAL_EFFECT   o fato existe e não move ESTE estado
SCORE                  GOAL
SUBSTITUTION           SUBSTITUTION
DISCIPLINE             CARD
```

`NO_STRUCTURAL_EFFECT` não é «irrelevante»: é «não muda este estado». Um chute
alimentará as features do PR-05.3 a partir da mesma projeção efetiva.

**Por que um mapa e não um `if/else`.** O `else` silencioso é a armadilha: no
dia em que a taxonomia ganhar `PENALTY_AWARDED`, ele cairá ali sem ninguém
decidir, e o estado passará a ignorar um fato que muda o jogo. E o lugar da
falha importa: um tipo esquecido que só quebrasse na hora de reconstruir
apareceria como uma partida específica ruim num lote de dez mil, e a
investigação começaria pelo lugar errado.

### 5.1 As transições, uma a uma

| evento | efeito |
|---|---|
| gol no tempo normal | soma em `regular`, no lado do `team_id` do evento |
| gol na prorrogação | soma em `extra_time` |
| gol na disputa | soma em `shootout`, e não entra em `home`/`away` |
| gol de time desconhecido | placar → `SOURCE_UNAVAILABLE` + `GOAL_TEAM_UNRESOLVED` |
| substituição válida | sai um, entra um, o outro time não é tocado |
| substituição sem detalhe | campo daquele time degrada |
| quem sai não está em campo | campo daquele time degrada |
| quem entra já está em campo | campo daquele time degrada |
| transição passaria de onze | campo daquele time degrada |
| amarelo | conta, e não tira ninguém do campo |
| segundo amarelo | conta como amarelo **e** como expulsão, e tira do campo |
| vermelho | conta como expulsão, e tira do campo |
| cartão sem `CardDetail` | não conta, e registra `DISMISSAL_PLAYER_UNKNOWN` |

**O segundo amarelo é as duas coisas.** Contá-lo só como expulsão faria a soma
de amarelos do time ficar menor que a súmula.

**A substituição entra no histórico mesmo quando o campo não é afirmável.** Ela
aconteceu; o que pode faltar é a base para dizer quem está em campo, e apagar o
histórico junto perderia um fato que o corpus tem.

---

## 6. As cotações

O filtro é o **guarda do PR-05.1**, e não uma comparação local: uma segunda
regra temporal aqui divergiria da primeira no caso difícil.

O estado guarda a **última cotação conhecida de cada fluxo**
(`bookmaker · mercado · seleção · linha`), e não uma pilha. O desempate é
determinístico e não é a ordem do banco: instante, depois referência da
observação de origem, depois valor. Duas leituras do mesmo corpus precisam
escolher a mesma cotação — senão o estado muda de identidade sem o conteúdo
mudar.

Cotação sem carimbo, ou corte sem `knowledge_cutoff`, produz
`TEMPORALLY_UNAVAILABLE` e um `ODDS_TEMPORAL_UNKNOWN`. **Fail-closed por
desenho:** assumir que a cotação já existia é exatamente o vazamento que o
motor existe para tornar difícil.

---

## 7. O resultado publicado

Ele é lido sempre — custa uma consulta por lote — e usado quase nunca.

- **Num corte intra-jogo:** invisível. O `2-1` do banco não pode virar o placar
  dos 63 minutos.
- **Num corte pós-jogo:** conferência, e só. Quando os dois discordam, o estado
  continua sendo o que os eventos dizem e um `SCORE_RESULT_MISMATCH` (`NOTED`)
  é registrado.

Usar o resultado para «consertar» o placar seria vazamento com desculpa de ser
pós-jogo.

---

## 8. O lote

`BuildHistoricalMatchStates` lê em lotes e reduz por partida. Ele **não**
distribui trabalho e **não** guarda cache.

A saída é **limitada**: contagem exata (`built`, `partial`), problemas
agregados por código, e uma **amostra** de estados com `sample_truncated`
dizendo quando ela não é o conjunto. Devolver dez mil estados numa lista faria
o pico de memória seguir o corpus — e o caso de uso deixaria de ser usável
exatamente quando passasse a importar.

O corte vem de fora, por uma fábrica: uma partida pode precisar de cinco cortes
e outra de um, e embutir a escolha aqui obrigaria o caso de uso a ter opinião
sobre o que se quer medir.

---

## 9. O que a reconstrução recusa

| situação | o que acontece |
|---|---|
| evento de outra partida na entrada | `ValidationError` — não se filtra em silêncio |
| escalação de outra partida | `ValidationError` |
| cotação de outra partida | `ValidationError` |
| corte de outra partida | `ValidationError` |
| partida fora da versão | `NotFoundError` — não é «partida sem eventos» |
| versão não publicada | `ValidationError` em `CorpusSource.of` |

Filtrar em silêncio produziria um estado plausível de um jogo que não é o
pedido — e um estado plausível e errado é pior que nenhum, porque nada
denuncia.
