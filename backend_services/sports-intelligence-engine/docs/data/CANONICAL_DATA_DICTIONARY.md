# Dicionário de dados canônico — V1

Para cada campo: o que significa, tipo, unidade, se aceita ausência, se é
observado ou derivado, e a semântica temporal.

**As três colunas que o PR de Data Fusion vai usar mais:**

- **origem** — `observado` (veio de fonte) vs `derivado` (calculado por nós).
  Nunca misturar os dois: comparar um xG de fonte com um xG nosso mede a
  diferença entre modelos, não entre partidas.
- **ausente?** — se `None` é legítimo, e o que ele significa. Onde diz
  **nunca**, a ausência é erro de dado.
- **temporal** — `pré-jogo`, `em jogo`, `pós-jogo` ou `atemporal`. É o que
  decide se um campo pode alimentar a descrição de um estado anterior.

---

## Competition

| campo | significado | tipo | unidade | ausente? | origem | temporal |
|---|---|---|---|---|---|---|
| `id` | identidade canônica, derivada do código | `CompetitionId` | — | nunca | derivado | atemporal |
| `code` | chave estável do catálogo | `CompetitionCode` | — | nunca | observado | atemporal |
| `name` | nome de exibição | `str` | — | nunca | observado | atemporal |
| `region` | país ou confederação | `str` | ISO-3166 / sigla | nunca | observado | atemporal |
| `competition_type` | liga nacional ou torneio continental | `CompetitionType` | — | nunca | observado | atemporal |
| `active` | ainda é disputada | `bool` | — | nunca | observado | atemporal |

> O `name` **não** é autoridade de identidade: muda com patrocinador e
> tradução. O `id` vem do `code`.

## Season

| campo | significado | tipo | unidade | ausente? | origem | temporal |
|---|---|---|---|---|---|---|
| `id` | derivada de (competição, label) | `SeasonId` | — | nunca | derivado | atemporal |
| `competition_id` | a competição | `CompetitionId` | — | nunca | observado | atemporal |
| `label` | rótulo publicado (`2024-2025`, `2025`) | `str` | — | nunca | observado | atemporal |
| `starts_at` / `ends_at` | janela da edição | `Instant` | UTC | nunca | observado | atemporal |
| `regime` | formato sob o qual ocorreu | `CompetitionRegime` | — | nunca | observado | atemporal |

## CompetitionRegime

| campo | significado | tipo | ausente? | origem |
|---|---|---|---|---|
| `code` | o formato | `RegimeCode` | nunca | observado |
| `effective_from` | quando passou a valer | `Instant` UTC | nunca | observado |
| `effective_to` | quando deixou | `Instant` UTC | **sim** = vigente | observado |
| `regulation_version` | versão do regulamento | `str` | nunca | observado |

## Stage

| campo | significado | tipo | ausente? |
|---|---|---|---|
| `type` | a fase | `StageType` | nunca |
| `round_number` | rodada | `int ≥ 1` | **sim** — mata-mata não tem |
| `group_label` | grupo | `str` | **sim** — só `GROUP_STAGE` tem |

## Team

| campo | significado | tipo | ausente? | origem |
|---|---|---|---|---|
| `id` | identidade **sorteada** | `TeamId` | nunca | derivado |
| `canonical_name` | nome de referência | `str` | nunca | observado |
| `country` | país | `str` ISO-3166 α-2 | nunca | observado |
| `short_name` | abreviação | `str` | sim | observado |
| `active` | ainda compete | `bool` | nunca | observado |

> Aliases e ids de provedor **não pertencem à entidade** — Identity Resolution.

## Player

| campo | significado | tipo | ausente? | origem |
|---|---|---|---|---|
| `id` | identidade **sorteada** | `PlayerId` | nunca | derivado |
| `canonical_name` | nome de referência | `str` | nunca | observado |
| `date_of_birth` | nascimento | `date` | sim | observado |
| `nationality` | nacionalidade | `str` ISO-3166 α-2 | sim | observado |
| `preferred_foot` | pé preferido | `PreferredFoot` | sim | observado |
| `primary_position` | posição habitual | `Position` | sim | observado |

> `date_of_birth` e `nationality` existem para **resolver identidade**: eles
> distinguem homônimos melhor que qualquer heurística sobre o nome.

## PlayerTeamTenure

| campo | significado | tipo | ausente? | temporal |
|---|---|---|---|---|
| `player_id` / `team_id` | as pontas | `PlayerId` / `TeamId` | nunca | atemporal |
| `valid_from` | início do vínculo | `Instant` UTC | nunca | atemporal |
| `valid_to` | fim | `Instant` UTC | **sim** = ainda é | atemporal |

> `team_at(tenures, momento)` devolve **`None`** quando nenhum vínculo cobre a
> data. Devolver o clube atual como aproximação reescreveria o passado.

## Match

| campo | significado | tipo | ausente? | origem | temporal |
|---|---|---|---|---|---|
| `id` | identidade **sorteada** | `MatchId` | nunca | derivado | atemporal |
| `competition_id` / `season_id` | onde se encaixa | ids | nunca | observado | atemporal |
| `regime` | formato vigente | `CompetitionRegime` | nunca | observado | atemporal |
| `stage` | fase e rodada | `Stage` | nunca | observado | atemporal |
| `home_team_id` / `away_team_id` | quem joga | `TeamId` | nunca | observado | pré-jogo |
| `scheduled_kickoff` | horário marcado | `Instant` UTC | nunca | observado | pré-jogo |
| `actual_kickoff` | pontapé real | `Instant` UTC | **sim** antes do jogo | observado | em jogo |
| `venue` | estádio | `Venue` | sim | observado | pré-jogo |
| `neutral_venue` | campo neutro | `bool` | nunca | observado | pré-jogo |
| `lifecycle` | estado no ciclo | `MatchLifecycle` | nunca | derivado | atemporal |

> **`Match` não tem campo de resultado.** Ver `MatchResult`.

## MatchResult — **pós-jogo**

| campo | significado | tipo | ausente? | temporal |
|---|---|---|---|---|
| `regular_time` | placar dos 90 minutos | `Score` | nunca | **pós-jogo** |
| `extra_time` | placar acumulado após prorrogação | `Score` | **sim** = não houve | **pós-jogo** |
| `penalties` | disputa de pênaltis | `Score` | **sim** = não houve | **pós-jogo** |
| `goals` *(derivado)* | gols da partida, pênaltis **excluídos** | `Score` | nunca | **pós-jogo** |
| `outcome` *(derivado)* | quem passou, pênaltis incluídos | `Outcome` | nunca | **pós-jogo** |

> **Nada que descreva um estado anterior pode ler esta tabela.**

## Lineup / LineupEntry

| campo | significado | tipo | ausente? | temporal |
|---|---|---|---|---|
| `match_id` / `team_id` | a quem pertence | ids | nunca | pré-jogo |
| `formation` | rótulo declarado | `FormationLabel` | sim — **nunca inferido** | pré-jogo |
| `player_id` | o jogador | `PlayerId` | nunca | pré-jogo |
| `status` | titular ou banco | `LineupStatus` | nunca | pré-jogo |
| `shirt_number` | camisa | `int` 1–99 | **sim ≠ 0** | pré-jogo |
| `position` | posição estrutural | `Position` | sim | pré-jogo |
| `tactical_role` | função contextual | `TacticalRole` | sim | pré-jogo |
| `captain` | é o capitão | `bool` | nunca | pré-jogo |

> A escalação é a **configuração inicial** e não muda: substituições são
> eventos.

## PitchCoordinate

| campo | significado | tipo | unidade | ausente? |
|---|---|---|---|---|
| `x` | eixo do ataque | `float` | [0,1] normalizado | **sim ≠ 0.0** |
| `y` | eixo lateral | `float` | [0,1] normalizado | **sim ≠ 0.0** |
| `frame` | referencial | `CoordinateFrame` | — | nunca |

> Normalizado e **não em metros**: as dimensões do campo variam.

## CanonicalMatchEvent

| campo | significado | tipo | ausente? | origem | temporal |
|---|---|---|---|---|---|
| `id` | identidade da revisão | `UUID` | nunca | derivado | em jogo |
| `match_id` | a partida | `MatchId` | nunca | observado | em jogo |
| `type` | o tipo canônico | `EventType` | nunca | observado | em jogo |
| `clock` | período + minuto + acréscimo | `MatchClock` | nunca | observado | em jogo |
| `sequence` | ordem dentro do período | `int ≥ 0` | nunca | observado | em jogo |
| `team_id` | equipe executora | `TeamId` | **sim** se estrutural | observado | em jogo |
| `player_id` | executante | `PlayerId` | sim | observado | em jogo |
| `start_location` / `end_location` | onde | `PitchCoordinate` | sim | observado | em jogo |
| `detail` | payload tipado | união | sim | observado | em jogo |
| `provenance` | de onde veio | `DataProvenance` | nunca | observado | em jogo |
| `quality` | qualidade da fonte | `DataQuality` | nunca | derivado | em jogo |
| `revision` | número da revisão | `int ≥ 1` | nunca | derivado | atemporal |
| `supersedes` | revisão anterior | `UUID` | **sim** se revisão 1 | derivado | atemporal |
| `status` | ativa, corrigida, cancelada | `EventStatus` | nunca | derivado | atemporal |

## Detalhes tipados

| detalhe | campos | ausente? |
|---|---|---|
| `ShotDetail` | `outcome`, `body_part?`, `xg?` | **`xg` ausente ≠ 0.0** — `FeatureValue` |
| `PassDetail` | `outcome`, `recipient_id?`, `body_part?` | destinatário só em passe completo |
| `CardDetail` | `card_type`, `reason?` | `SECOND_YELLOW` ≠ `RED` |
| `SubstitutionDetail` | `player_out`, `player_in` | nunca; precisam ser distintos |
| `GoalkeeperDetail` | `action_type`, `outcome` | nunca |
| `DuelDetail` | `outcome`, `opponent_id?` | adversário opcional |

> **`xg` é observado, nunca calculado por nós neste PR.** Quando o motor
> calcular o próprio, será feature derivada com versão — e as duas coisas não
> se misturam.

## OddsQuote

| campo | significado | tipo | unidade | ausente? | origem | temporal |
|---|---|---|---|---|---|---|
| `match_id` | a partida | `MatchId` | — | nunca | observado | pré-jogo / em jogo |
| `bookmaker` | a casa | `BookmakerRef` | — | nunca | observado | — |
| `market` | o mercado | `OddsMarket` | — | nunca | observado | — |
| `selection` | o lado | `OddsSelection` | — | nunca | observado | — |
| `decimal_odds` | cotação decimal | `Decimal` | > 1 | nunca | observado | pontual |
| `line` | linha do mercado | `Decimal` | gols / handicap | **sim** se o mercado não tem | observado | pontual |
| `observed_at` | quando foi vista | `Instant` | UTC | nunca | observado | **pontual** |
| `suspended` | mercado suspenso | `bool` | — | nunca | observado | pontual |
| `provenance` | de onde veio | `DataProvenance` | — | nunca | observado | — |

> Não existe `current_odds`. A série de observações **é** o dado.

---

## Semântica temporal — resumo operacional

| classe | pode descrever um estado anterior? |
|---|---|
| `atemporal` | sim — não muda com o tempo |
| `pré-jogo` | sim — conhecido antes do apito |
| `em jogo` | sim, **desde que** o carimbo seja ≤ o instante descrito |
| `pós-jogo` | **não** — é a resposta |
