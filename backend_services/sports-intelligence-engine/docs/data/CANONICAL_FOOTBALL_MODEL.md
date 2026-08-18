# Canonical Football Domain V1

O idioma interno do motor. A partir daqui:

> Provider fala a própria língua no adapter.
> O Sports Intelligence Engine fala somente Canonical Football Domain.

---

## Diagrama

```
Competition  (catálogo fechado: 5)
   └── Season  (label + janela + CompetitionRegime)
        └── Match  ← agregado central
             ├── home / away Team
             ├── Stage (tipo + rodada/grupo)
             ├── Lineup*  (uma por time; configuração INICIAL)
             │     ├── FormationLabel?
             │     └── LineupEntry*  → Player, Position?, TacticalRole?
             ├── CanonicalMatchEvent*  (revisões; append-only)
             │     ├── PitchCoordinate?  (start / end)
             │     └── detalhe tipado?   (Shot | Pass | Card | Sub | GK | Duel)
             └── OddsQuote*  (série temporal por bookmaker × market × line)

MatchResult   ← observação PÓS-JOGO, ligada por id — NÃO vive dentro de Match

Team
   └── PlayerTeamTenure*  (janela de validade)
          └── Player
```

`*` = múltiplos · `?` = opcional

---

## Aggregates

### Match

O agregado central, e o que ele **não** sabe.

`Match` **não carrega o resultado**. É a decisão mais importante do modelo e
contraria o instinto — uma partida "tem" um placar.

Mas o placar é informação pós-jogo, e o motor descreve estados *anteriores*.
Se o agregado o carrega, qualquer caminho que descreva o minuto 63 pode
lê-lo, e a descrição passa a conter a resposta. Nada falha: a similaridade
fica excelente e não descreve nada.

```
Match          quem joga, quando, sob que regime e fase  → o que se sabe ANTES
MatchResult    o que aconteceu                            → observação pós-jogo
```

A separação é o que torna o replay honesto.

### Lineup

A configuração **inicial** — e ela não muda. Substituição é evento, não edição
da escalação. Reconstruir "quem estava em campo no minuto 63" é aplicar
eventos sobre a escalação; guardar só o estado corrente torna isso impossível
e apaga o que o técnico planejou.

---

## Entidades

| Entidade | Identidade | Notas |
|---|---|---|
| `Competition` | derivada do **código** | catálogo fechado de 5 |
| `Season` | derivada de (competição, label) | idempotente na reingestão |
| `Team` | **sorteada** | nunca derivada do nome |
| `Player` | **sorteada** | homônimos são comuns |
| `Match` | **sorteada** | duas partidas do mesmo par no mesmo dia existem |

### Por que a identidade de competição é derivada e a de clube não

O **código** de uma competição é estável por construção — `PREMIER_LEAGUE` tem
uma grafia só. O **nome** de um clube tem muitas: `Manchester City`,
`Man City`, `Manchester City FC`. Derivar identidade de nome faria três
grafias virarem três clubes, cada um com um terço do histórico — e o número
continuaria fechando.

A ponte entre "o texto que a fonte mandou" e "qual clube é este" é resolução
de identidade: etapa explícita, com regras próprias, capaz de falhar e de
pedir revisão humana. **Nunca** um `uuid5` sobre um nome.

---

## Value Objects

### Competição e temporada

- **`CompetitionCode`** — as cinco da V1, fechado
- **`CompetitionType`** — `DOMESTIC_LEAGUE` | `CONTINENTAL_CLUB`
- **`CompetitionRegime`** — `code` + janela + `regulation_version`
- **`RegimeCode`** — `DOUBLE_ROUND_ROBIN` | `GROUP_STAGE_KNOCKOUT` | `LEAGUE_PHASE_KNOCKOUT`
- **`Stage`** / **`StageType`** — nove fases; rodada e grupo opcionais

**Por que o regime existe.** A Champions de 2020 tinha grupos de 32 clubes; a
de 2025 tem league phase com 36. São formatos diferentes, com números
diferentes de jogos. Um histórico que ignora isso compara coisas
incomparáveis — em silêncio, porque "a competição é a mesma".

### Jogador

- **`Position`** — 12 posições estruturais, agrupadas em `PositionLine`
- **`TacticalRole`** — função contextual: `RoleCode` conhecido **ou** `extra` descrito
- **`PlayerTeamTenure`** — vínculo com janela de validade

**Position ≠ TacticalRole.** Dois volantes em `DM` podem ser um
`HOLDING_MIDFIELDER` que fica e um `BOX_TO_BOX` que chega na área. Tratá-los
como sinônimos apaga o segundo — que é justamente o que descreve estilo.

### Resultado

- **`Score`** — gols de um escopo; `outcome` **derivado**, nunca informado
- **`MatchResult`** — `regular_time` + `extra_time?` + `penalties?`

**Um 1-1 que foi 4-2 nos pênaltis não é um 4-2.** Somar pênaltis ao placar
falsifica o jogo corrido e infla o ataque de todo clube que foi a decisões.

```
result.goals            prorrogação incluída, pênaltis NUNCA
result.goals.outcome    como terminou o JOGO          → DRAW
result.outcome          quem passou de fase           → HOME
```

As duas leituras são legítimas e respondem perguntas diferentes.

### Escalação

- **`FormationLabel`** — `4-3-3`, validado; o goleiro não entra no rótulo
- **`LineupEntry`** — jogador + status + número? + posição? + função? + capitão
- **`LineupStatus`** — `STARTER` | `BENCH`

**A formação é declarada, nunca inferida.** Contar posições e concluir `4-3-3`
erra: um `4-2-3-1` e um `4-5-1` têm a mesma contagem por linha e são desenhos
diferentes.

### Coordenadas

- **`PitchCoordinate`** — `x`, `y` ∈ [0,1] + `frame`
- **`CoordinateFrame`** — `ATTACKING` (canônico) | `ABSOLUTE`

```
ATTACKING:   x = 0.0  o próprio gol de quem executa
             x = 1.0  o gol adversário
```

Assim um chute perigoso é `x ≈ 0.95` **sempre** — primeiro tempo, segundo
tempo, mandante, visitante. Comparar coordenadas de referenciais diferentes é
somar metros com jardas sem que nada falhe, e `assert_comparable` recusa.

### Odds

- **`BookmakerRef`**, **`OddsMarket`**, **`OddsSelection`**, **`OddsQuote`**

Cada quote é uma **observação com instante próprio**. Não existe
`current_odds`: a diferença entre abertura e fechamento é o sinal, e um campo
"atual" a apagaria.

`decimal_odds` é `Decimal` e não `float` — odds vêm como texto decimal e serão
comparadas; `float` introduz ruído que faz duas casas cotando o mesmo preço
parecerem diferentes.

**Nenhum cálculo aqui**: probabilidade implícita, overround, consenso e
velocidade são interpretação versionada, e pertencem ao Odds Intelligence.

---

## Eventos canônicos

`CanonicalMatchEvent` é **imutável**. Correção é evento novo:

```
revisão 1  GOAL  camisa 9   status=CORRECTED   supersedes=None
revisão 2  GOAL  camisa 11  status=ACTIVE      supersedes=rev1
```

**Por que não sobrescrever.** Duas perguntas ficariam sem resposta: «o que
sabíamos no minuto 63?» e «quando soubemos que mudou?». A primeira é o que
torna o replay honesto — se a correção chegou aos 85 e o replay do minuto 63
usa a versão corrigida, o replay enxerga o futuro.

`CORRECTED` ≠ `CANCELLED`: o primeiro diz "existe versão melhor deste fato"; o
segundo diz "este fato não aconteceu". Um gol anulado pelo VAR não é um gol
corrigido.

`current_truth()` devolve só as ativas, ordenadas explicitamente por
(período, minuto, acréscimo, sequência) — a ordem de chegada não serve.

### Detalhes tipados

`ShotDetail` · `PassDetail` · `CardDetail` · `SubstitutionDetail` ·
`GoalkeeperDetail` · `DuelDetail`

**Por que não `dict[str, Any]`.** Um dicionário livre parece flexível e custa:
o nome da chave vira convenção oral, nenhum checker pega quem lê a chave
errada, ausente e zero ficam indistinguíveis, e o schema real passa a ser "o
que os provedores mandaram até hoje".

---

## Invariantes protegidos em código

| Invariante | Onde |
|---|---|
| catálogo de competições é fechado | `resolve_code` |
| identidade de competição vem do código, não do nome | `CatalogEntry.id` |
| identidade de clube/jogador **não** deriva de nome | ausência de `Team.derive` |
| renomear não muda a identidade | `Team.rename` |
| regime cobre a temporada inteira | `Season.__post_init__` |
| mata-mata não tem rodada de liga | `Stage.__post_init__` |
| mandante ≠ visitante | `Match.__post_init__` |
| `Match` não expõe resultado | ausência de `.result` |
| candidato de identidade **não** funde | ausência de `.matches()` |
| pênaltis não entram em `goals` | `MatchResult.goals` |
| prorrogação é acumulada e só após empate | `MatchResult.__post_init__` |
| máximo 11 titulares | `Lineup.__post_init__` |
| jogador não se repete na escalação | `Lineup.__post_init__` |
| capitão é titular | `LineupEntry.__post_init__` |
| jogador não está nos dois times | `assert_squads_are_disjoint` |
| goleiro fora do rótulo de formação | `FormationLabel.__post_init__` |
| coordenada em [0,1] com frame declarado | `PitchCoordinate` |
| frames diferentes não se comparam | `assert_comparable` |
| evento estrutural não tem dono | `CanonicalMatchEvent.__post_init__` |
| revisão > 1 aponta o predecessor | `CanonicalMatchEvent.__post_init__` |
| cancelado não se corrige | `correct_to` |
| passe incompleto não tem destinatário | `PassDetail` |
| substituição com jogadores distintos | `SubstitutionDetail` |
| seleção pertence ao mercado | `OddsQuote.__post_init__` |
| mercado com linha exige linha | `OddsQuote.__post_init__` |
| `decimal_odds > 1` | `OddsQuote.__post_init__` |
| vínculo não termina antes de começar | `PlayerTeamTenure` |
| histórico não usa o clube atual | `team_at` devolve `None` |

---

## Ausência nunca é zero

Herdado do PR-00 (Constituição §4), aplicado aqui:

```
xG ausente        ≠  xG 0.0        FeatureValue.absent(...)
número ausente    ≠  camisa 0      shirt_number = None
coordenada ausente≠  (0, 0)        start_location = None
clube desconhecido≠  clube atual   team_at → None
```
