# `SAME_PERIOD_FIXED_HORIZON_1_3_5_V1` — a janela de lookback

**PR:** 06.3 · **ADR:** [0045](../architecture/adr/0045-same-period-multi-horizon-displacement-trajectory.md)

## Os três horizontes

```
H = {1, 3, 5}      minutos de grade

1 min    o movimento MUITO recente
3 min    o movimento curto
5 min    a tendência local
```

**Não é uma janela deslizante.** `t-1, t-2, t-3, t-4, t-5` traria cinco
instantes fortemente correlacionados e multiplicaria o custo por cinco para
acrescentar quase nada.

**E o conjunto é FIXO.** Ele não é derivado do que a query tem — isso é o §88 —
nem otimizado neste PR.

## O lookback não atravessa o período

A grade conta os minutos do segundo tempo **continuando** os do primeiro. O
minuto 49 é do segundo tempo; o 44 é do primeiro.

```
âncora SECOND_HALF 49
    t-1  →  48   AVAILABLE
    t-3  →  46   AVAILABLE
    t-5  →  44   OUTSIDE_PERIOD_LOOKBACK
```

O intervalo não tem duração esportiva equivalente a um minuto de jogo. Tratar
`45 → 46` como minutos adjacentes de dinâmica diria que a pressão subiu ou caiu
durante quinze minutos de vestiário.

### A escada de começo de período

```
minuto do 2º tempo    horizontes estruturais
46                     0
47                     1
48                     1
49                     2
50                     2
51 em diante           3
```

Medido no benchmark, sobre 120 queries: a faixa 46–48 tem mediana de **1**
horizonte, a 49–50 tem **2**, e de 51 em diante tem **3**.

**A trajetória simplesmente não se aplica no começo do período**, e a recusa é a
resposta certa: a alternativa seria atravessar o intervalo.

### Os limites vêm da grade

`period_first_minute(period, grid)` lê `SnapshotGridPolicy`:

```
FIRST_HALF          1
SECOND_HALF         first_half_last_minute + 1
EXTRA_TIME_FIRST    second_half_last_minute + 1
EXTRA_TIME_SECOND   EXTRA_TIME_FIRST_LAST_MINUTE + 1
```

Uma segunda tabela aqui divergiria da grade no dia em que alguém mudasse os
limites, e a trajetória passaria a atravessar o intervalo sem que nada
denunciasse.

**E não há relógio de parede.** Nada de `kickoff + minuto`, nada de inferir a
duração do intervalo. Há guarda arquitetural contra `kickoff`, `timedelta`,
`datetime` e `elapsed_match_minutes` no domínio da trajetória.

## O catálogo de status do slot

```
AVAILABLE                 o instante existe, dentro do período, e a linha veio
OUTSIDE_PERIOD_LOOKBACK   `t-h` cai antes do começo do período. ESPERADO
NOT_APPLICABLE            a âncora não tem trajetória
```

**Os erros estruturais NÃO estão no catálogo**, e a separação é deliberada:

| situação | resposta | por quê |
|---|---|---|
| slot fora do período | `OUTSIDE_PERIOD_LOOKBACK` | esperado, e é ausência estrutural |
| a linha deveria existir e não veio | `TRAJECTORY_SOURCE_ROW_MISSING` | corrupção — **falha fechada** |
| a linha existe, o eixo está vazio | célula não utilizável | ausência normal de feature |

Uma linha que a grade declara e o Parquet não entrega significa dataset
incompleto. Registrá-la como status a transformaria em ausência normal, a
célula viraria penalidade, o candidato cairia algumas posições, e a corrupção
sairia como um número plausível.

## Dois níveis de disponibilidade

```
SlotStatus                   o INSTANTE existe?
NormalizationAvailability    o EIXO tem número naquela linha?
```

Confundi-los é o defeito mais fácil deste PR.

## As fases sem trajetória

`PRE_MATCH`, `HALF_TIME`, `FULL_TIME` e `PENALTY_SHOOTOUT` não têm minuto
anterior **dentro delas**. A resposta é `TRAJECTORY_NOT_APPLICABLE`, com tipo
próprio — quem a recebe sabe que tentar de novo não muda nada.

A prorrogação é suportada quando existe no dataset, e a aritmética dela é a
mesma: `EXTRA_TIME_FIRST 93` alcança o 92 e nada mais, porque a fase começa no
91.

## A grade é conferida

```
SUPPORTED_GRIDS = { LIVE_COMPARABLE_MINUTE_GRID_V1 }
```

**Uma grade de cinco cortes também tem coluna `minute`**, e `t-3` nela não são
três minutos de jogo — são três cortes, que podem ser vinte minutos. Aceitar
qualquer grade produziria trajetórias cujos horizontes não significam o que o
nome diz.

Incompatível → `UNSUPPORTED_TRAJECTORY_GRID`, **antes** de qualquer aritmética.

**E a grade vem do DATASET**, lida da versão crua de origem — não de um
parâmetro. Recebê-la do chamador faria a conferência validar o que o chamador
disse em vez do que o dataset é.

## O futuro não é pedido

```
TrajectoryDirection = { BACKWARD }        um membro
PeriodCrossingPolicy = { STOP_AT_PERIOD_START }   um membro
```

Os dois catálogos têm um membro só para que as duas afirmações sejam campos
conferíveis e impressos, em vez de comentários. `FORWARD` e `ALLOW` não existem:
nomeá-los seria admitir que são configuráveis.

Um horizonte não positivo é recusado no construtor com a mensagem que diz por
quê. A aritmética é `anchor.minute - horizonte`, e há guarda arquitetural sobre
a expressão — trocar o sinal é uma edição de um caractere que não quebra tipo
nenhum e transforma a trajetória num vazamento do futuro.

E o construtor de `HistoricalTrajectory` recusa qualquer slot cujo alvo não seja
**estritamente anterior** à âncora, e qualquer slot de outro período.

## A impressão

```
algorithm         trajectory-window-policy-sha256-v1
direction         BACKWARD
grid_stoppage     0
horizons          [1, 3, 5]
period_crossing   STOP_AT_PERIOD_START
supported_grids   [LIVE_COMPARABLE_MINUTE_GRID_V1]
```

Ela entra na impressão do perfil de trajetória e na da distância: dois conjuntos
de horizontes são duas definições, e os números deles não se comparam.
