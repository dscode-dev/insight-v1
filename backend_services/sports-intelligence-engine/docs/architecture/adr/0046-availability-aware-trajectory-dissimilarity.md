# ADR-0046 — A dissimilaridade de trajetória, e por que ela não se soma ao estado

**Status:** aceito · **Data:** 2026-08-27

## Contexto

O [ADR-0045](0045-same-period-multi-horizon-displacement-trajectory.md) decidiu
**o que** a trajetória é: deslocamentos `Δ_{h,i}` sobre horizontes fixos, dentro
do período. Falta decidir **como comparar duas delas**, e o que fazer com o
número que sai.

Duas perguntas, e a segunda é a que define o PR:

1. Como medir a distância entre dois conjuntos de deslocamentos, quando parte
   das células não existe?
2. O que fazer com `D_state` e `D_trajectory` — dois números sobre a mesma
   query?

A resposta tentadora para a segunda é somar. Ela é errada, e é errada agora.

## Decisão

```
MULTI_HORIZON_DISPLACEMENT_FIXED_PROFILE_IQR_PENALTY_V1   a distância
MULTI_HORIZON_MINIMUM_EVIDENCE_COVERAGE_V1                o piso
```

### 1. A fórmula reusa a do PR-06.2, com outra unidade de célula

```
              Σ_{(h,i)∈S_T} (Δ^q − Δ^c)²  +  p·(n − s)
D_T(q,c) =  ──────────────────────────────────────────      p = 1
                              n = |H| · m
```

Denominador fixo, penalidade uniforme, pesos iguais — as três decisões já foram
tomadas e justificadas no ADR-0044, e mudá-las aqui faria a comparação entre
estado e trajetória medir duas coisas de uma vez.

**O que muda é a unidade da célula, e o que ela contém:**

```
estado        célula = eixo                (q_i − c_i)²      diferença de NÍVEL
trajetória    célula = (horizonte, eixo)   (Δ^q − Δ^c)²      diferença de MOVIMENTO
```

**E a penalidade continua fazendo sentido.** `Δ` é a diferença entre dois valores
normalizados pelo IQR da competição, logo `Δ` vive em unidades de IQR — as
mesmas do estado. É por isso que não dividimos por `h` (ADR-0045 §4).

### 2. O denominador é `n`, e ele NÃO encolhe

Se o horizonte de cinco minutos estiver fora do período, as `m` células dele
ficam indisponíveis e **continuam no divisor**:

```
remover o horizonte     uma trajetória com UM minuto de história pareceria
                        tão evidenciada quanto uma com cinco
manter no denominador   ela tem no máximo `2m/3m = 2/3` de cobertura, e o
                        piso decide se isso basta
```

### 3. O piso ganhou uma dimensão: HORIZONTES DISTINTOS

O PR-06.2 tinha dois pisos — absoluto e relativo. Aqui há um terceiro, e ele é
o que a unidade nova exige:

```
minimum_profile_axes                4
minimum_usable_horizons             2      ← NOVO
minimum_shared_horizons             2      ← NOVO
minimum_query_trajectory_cells      8
minimum_shared_trajectory_cells     8
query_trajectory_coverage_floor     3/5
shared_trajectory_coverage_floor    3/5
per_horizon_axis_coverage_floor     3/5    ← NOVO
minimum_axes_per_evidential_horizon 4      ← NOVO
```

**Por que dois horizontes.** Um candidato com o horizonte de um minuto perfeito
e os outros dois vazios teria, num perfil de vinte eixos, vinte células de
sessenta — e zero informação sobre tendência. «Movimento parecido» com base num
minuto só é uma afirmação que a representação não sustenta.

**E um horizonte só CONTA se sozinho passaria no piso do PR-06.2**: pelo menos
quatro eixos, e pelo menos três quintos deles. Um horizonte com um eixo de
vinte existe estruturalmente e não descreve movimento — contá-lo transformaria
o piso de dois horizontes numa formalidade.

**Oito células é um MÍNIMO ABSOLUTO, e NÃO o piso.** Ele é o produto dos dois
mínimos, e não um número solto:

```
4 eixos (o piso do PR-06.2)  ×  2 horizontes  =  8 células
```

Mas **o piso que decide é o EFETIVO**, e ele é o maior entre o mínimo absoluto
e o piso racional sobre o espaço inteiro:

```
E_s = max( 8, ceil(3n/5) )        n = |H| · m
E_q = max( 8, ceil(3n/5) )
E_h = max( 4, ceil(3m/5) )
```

| `m` | `n` | absoluto | racional | **efetivo** | quem decide |
|---:|---:|---:|---:|---:|---|
| 3 | 9 | 8 | 6 | **8** | absoluto |
| 4 | 12 | 8 | 8 | **8** | empate |
| 5 | 15 | 8 | 9 | **9** | racional |
| 6 | 18 | 8 | 11 | **11** | racional |
| 15 | 45 | 8 | 27 | **27** | racional |

**Os dois mínimos juntos NÃO autorizam nada.** Dois horizontes minimamente
evidenciais dão `4 + 4 = 8` células — e com `m = 6` isso é recusado, porque oito
é menor que onze. Ler `minimum_shared_trajectory_cells = 8` como «oito bastam»
erraria por três células nesse perfil, e por dezenove no perfil real de quinze
eixos.

**E o mínimo absoluto quase nunca é o que decide.** `ceil(3n/5) < 8` exige
`n <= 12`, isto é `m <= 4`, e `minimum_profile_axes = 4` corta exatamente aí —
onde os dois EMPATAM. Para todo perfil admissível o piso racional alcança ou
supera o absoluto; ele nunca domina estritamente.

A derivação é feita em **aritmética inteira** — `-((-3n) // 5)` —, e não em
`ceil(0.6 * n)`. Não porque o float erre num perfil de futebol (foram medidos
dois milhões de valores sem uma divergência), mas porque a forma inteira é exata
por construção e a de ponto flutuante é correta só sob um argumento de
arredondamento que tem fim: em `n = 9_999_999_999_999_997` as duas diferem
por dois.

O construtor confere a coerência dos mínimos: uma política que exigisse três
horizontes e mantivesse oito células seria recusada, porque o mínimo mais frouxo
nunca teria efeito.

### 4. Ausência não é movimento zero

Uma célula ausente custa `1`, e não `0`. Preencher o extremo que falta com o
valor da âncora produziria `Δ = 0` — «este jogo não se moveu» —, que é
**estabilidade inventada**, e é o blocker mais perigoso deste PR: ela não falha,
ela mente com aparência de calma.

E os **dois extremos** são exigidos: `Δ_{h,i}` existe quando o eixo tem número
finito na âncora **e** em `t−h`. Um extremo só não produz meio deslocamento.

### 5. A ordem do top-K é uma QUÁDRUPLA

```
1. dissimilaridade         ASC     quão parecido é o movimento
2. células compartilhadas  DESC    sobre quanta evidência
3. horizontes compartilhados DESC  distribuída em quantas escalas de tempo
4. chave canônica          ASC     a reprodutibilidade
```

**O terceiro critério é novo.** Com `D_T` e contagem de células iguais, a
evidência espalhada em três horizontes descreve a forma melhor que a mesma
quantidade concentrada em dois: doze células em `1m` e `3m` dizem o que
aconteceu em três minutos; oito em `1m`, `3m` e `5m` dizem o que aconteceu em
cinco.

**E a cobertura continua não liderando.** Ela já está dentro do número pela
penalidade; usá-la como primeiro critério a contaria duas vezes.

### 6. **NÃO HÁ SCORE COMBINADO**

Esta é a decisão que define o PR.

```
D_state         PR-06.2     nível
D_trajectory    PR-06.3     movimento

D_total         NÃO EXISTE
```

Combiná-los exige escolher `alfa` e `beta`, e **não há rótulo de verdade com
que calibrá-los**. O que sairia de um otimizador hoje seria o par de pesos que
maximiza uma métrica inventada.

**A separação é estrutural, e não uma convenção.** Três tipos de vizinho
distintos — `HistoricalNeighbor`, `AvailabilityAwareNeighbor`,
`TrajectoryHistoricalNeighbor` — impedem que alguém some dois números que não
são a mesma grandeza:

```
D    = média de diferença de NÍVEL     sobre m eixos
D_T  = média de diferença de MOVIMENTO sobre n = 3m células
```

`CompareStateAndTrajectory` **apresenta** os dois lado a lado. Ele não soma, não
pondera e não devolve total. Há guarda arquitetural que lê o corpo dele
procurando `0.5`, `alpha`, `beta`, `weight` e `combined`.

## Consequências

**A separação é demonstrável, e foi demonstrada.** Sobre dados reais, no minuto
60 do segundo tempo, oito candidatos no mesmo instante produzem `D_T` de
`0,133` a `8,12` — uma razão de **61×** — com 46 células em reversão de direção.
O estado não os separa assim.

**A sobreposição com o estado é parcial, e isso é o sinal.** Medido: p50 de
70 %, mínimo de 40 %. Uma sobreposição baixa significa que os jogos mais
parecidos **agora** não são os que se moveram parecido — que é exatamente a
informação nova.

**A trajetória é mais cara, e o custo está medido.** p50 de 405 ms contra 37 ms
do estado, com amplificação de I/O de apenas 1,21×: o custo é de CPU na
montagem — `47 candidatos × 4 linhas × 15 eixos` por query —, e não de leitura.

**E ela lê `1 + |H|` linhas por candidato numa varredura só.** O padrão
`candidato × horizonte` — 141 leituras de Parquet por query — está proibido por
guarda arquitetural e medido: 218 objetos para 5.123 candidatos, 94 linhas por
objeto.

**O horizonte de cinco minutos domina o observado** (p50 de 52 %, contra 11 %
de `1m` e 4 % de `3m`). Isso é **evidência para um estudo futuro** de ponderação
temporal ou de velocidade, e não motivo para corrigir nada agora — corrigir
exigiria a medida de acerto que não existe.

**`D_T` não é métrica**, pelo mesmo motivo do PR-06.2: uma representação
incompleta comparada consigo mesma tem `D_T = u/n > 0`. `is_metric` devolve
`False`, e a desigualdade triangular não é afirmada nem testada.

## Alternativas descartadas

**Somar estado e trajetória.** Descrita em §6.

**Denominador na interseção.** A fraude aritmética do ADR-0044, transposta.

**Pesos por horizonte** (`1m` vale 3, `5m` vale 1). Não há avaliação que
justifique importância temporal diferente — e a medição de §199 é o insumo para
que um dia haja.

**Piso de um horizonte.** Descrito em §3: «movimento parecido» sobre um minuto
não é uma afirmação que a representação sustente. O construtor da política
recusa `minimum_usable_horizons = 1`.

**Preencher o extremo ausente.** Descrita em §4.
