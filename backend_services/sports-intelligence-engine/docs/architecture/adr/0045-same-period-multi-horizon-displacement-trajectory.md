# ADR-0045 — A trajetória é deslocamento multi-horizonte, dentro do período

**Status:** aceito · **Data:** 2026-08-27

## Contexto

Até o PR-06.2 a recuperação compara `X_t` — o estado atual. Dois jogos podem
estar próximos em `X_t` e ter chegado ali de formas opostas:

```
partida A     baixo   →  médio  →  alto
partida B     altíssimo → alto  →  médio
```

O estado final é parecido. O movimento que o produziu não é. A pergunta que
falta é:

> Dois jogos em estados atuais parecidos chegaram até aqui de forma
> parecida, ou estão seguindo movimentos recentes diferentes?

Responder isso exige três decisões, e cada uma tem uma resposta óbvia e errada.

## Decisão

```
SAME_PERIOD_FIXED_HORIZON_1_3_5_V1        a janela
ROBUST_MULTI_HORIZON_DISPLACEMENT_TRAJECTORY_V1   o perfil
```

### 1. Três horizontes fixos: `H = {1, 3, 5}`

```
1 min    o movimento MUITO recente
3 min    o movimento curto
5 min    a tendência local
```

**Não é uma janela deslizante.** Carregar `t-1, t-2, t-3, t-4, t-5` traria
cinco instantes fortemente correlacionados e multiplicaria o custo por cinco
para acrescentar quase nada.

**E o conjunto não é otimizado aqui.** Escolher horizontes por otimização
exigiria uma medida de acerto, e não há rótulo de verdade com que construí-la
antes do PR-06.5. O benchmark percorre `{1,3}` e `{1,3,5}` e **reporta**.

### 2. O lookback NÃO atravessa o período

Esta é a decisão que o ADR existe para registrar. A grade conta os minutos do
segundo tempo **continuando** os do primeiro:

```
âncora SECOND_HALF 49
    t-1  →  48   segundo tempo
    t-3  →  46   segundo tempo
    t-5  →  44   PRIMEIRO TEMPO   →  OUTSIDE_PERIOD_LOOKBACK
```

O intervalo não tem duração esportiva equivalente a um minuto de jogo. Tratar
`45 → 46` como minutos adjacentes de dinâmica diria que a pressão subiu ou caiu
durante quinze minutos de vestiário — e a trajetória mediria o vestiário.

**Os limites vêm da `SnapshotGridPolicy`**, e não de constantes locais: uma
segunda tabela divergiria dela no dia em que alguém mudasse os limites, e a
trajetória passaria a atravessar o intervalo sem que nada denunciasse.

**E não há relógio de parede.** Nada de `kickoff + minuto`, nada de inferir a
duração do intervalo. O tempo é o da grade esportiva, e ele é *period-local* —
a mesma filosofia do PR-05.3.

### 3. A representação é DESLOCAMENTO, e não concatenação

A representação óbvia seria a errada:

```
[ x(t-5), x(t-3), x(t-1), x(t) ]
```

Quatro cópias quase iguais do mesmo **nível**. Três quartos do vetor repetem o
que o estado já mede, e a distância resultante seria dominada pelo nível — o
PR-06.2 outra vez, com quatro vezes o custo.

```
Δ_{h,i}(x) = x_i(t) − x_i(t−h)
```

«Quanto aquela dimensão se moveu nos últimos `h` minutos». **A ortogonalidade é
por construção, e é o ponto do PR:**

```
A:  10 → 12        B:  20 → 22
níveis diferentes  ·  movimento IDÊNTICO (Δ = +2)
```

O estado separa os dois; a trajetória os reconhece como a mesma forma. As duas
coisas estão certas, e medem perguntas diferentes.

### 4. Sem velocidade, e a decisão é deliberada

**Não dividimos por `h`.** O deslocamento preserva a unidade do espaço — desvios
em unidades de IQR da competição —, e é isso que mantém a penalidade `p = 1` do
PR-06.2 interpretável: uma célula ausente custa «um IQR de incerteza».

`Δ/h` viveria em «IQR por minuto», e uma penalidade de `1` ali seria um número
sem relação com o do estado. `Δ/h` é uma derivação futura possível; ela não
decide ranking aqui. Aceleração — que exigiria três instantes por célula e uma
decisão sobre o que fazer quando um deles falta — também não.

O catálogo `TrajectoryRepresentationMethod` tem **um** membro, e os que faltam
são a decisão.

### 5. Nada do futuro, e nada inventado

```
futuro         todo horizonte é POSITIVO e vira lookback.
               `TrajectoryDirection` tem um membro: `BACKWARD`
tolerância     nada de ±1 minuto, vizinho mais próximo, DTW, interpolação
fabricação     uma grade que não anda de minuto em minuto produz
               UNSUPPORTED_TRAJECTORY_GRID, e não slots inventados
preenchimento  um slot fora do período é AUSÊNCIA ESTRUTURAL, e não um
               convite a usar o minuto vizinho
```

### 6. Dois níveis de disponibilidade

```
SlotStatus                   o INSTANTE existe? (fora do período?)
NormalizationAvailability    o EIXO tem número naquela linha?
```

Confundi-los apagaria a diferença entre «não havia minuto 44 no segundo tempo»
e «havia a linha e o eixo estava vazio». E uma linha que a grade declara e o
Parquet não entrega é **corrupção** (`TRAJECTORY_SOURCE_ROW_MISSING`), não
ausência de feature: tratá-la como ausência faria a corrupção sair como uma
penalidade plausível.

### 7. Os eixos são os do estado

```
Axes_trajectory = Axes_state-AA
```

Não é economia de digitação: é a condição para que a comparação entre o PR-06.2
e o PR-06.3 signifique alguma coisa. Se os eixos também mudassem, a diferença
entre os dois resultados mediria a mudança de espaço **e** a mudança de
pergunta, e não haveria como separá-las.

## Consequências

**O universo não mudou.** `CandidateUniverse_06.3 = CandidateUniverse_06.2` —
mesma política, mesma âncora exata, mesma impressão. A trajetória muda **como**
os candidatos são comparados, e não **quem** é candidato.

**A trajetória não se aplica a todo instante, e isso é estrutural.** No começo
de cada período não há passado dentro dele:

```
minuto 46 do 2º tempo    zero horizontes
minuto 47                um
minuto 49                dois
minuto 51 em diante      três
```

Medido no benchmark: de 120 queries, 2 são `PRE_MATCH` (não aplicáveis) e 9
caem por evidência insuficiente. **Isso não é defeito de dado** — é o começo do
período não ter passado —, e a alternativa seria atravessar o intervalo.

**A imunidade ao futuro é verificável, e é verificada.** Alterar `t+1`, `t+3` ou
`t+5` não muda trajetória, impressão nem ranking: há teste que entrega essas
linhas ao montador com valores absurdos e compara as impressões.

**E a invariância de nível também.** Somar a mesma constante a todos os extremos
não muda deslocamento nenhum — exatamente, quando as somas são exatas em
`binary64`; a menos do arredondamento, quando não são. Os dois casos têm teste,
e a distinção está escrita.

## Alternativas descartadas

**Concatenar os níveis.** Descrita em §3: seria o estado outra vez, com quatro
vezes o custo.

**Janela deslizante de todos os minutos.** Cinco instantes correlacionados,
cinco vezes o custo.

**Atravessar o intervalo.** Mediria o vestiário como dinâmica de jogo.

**Interpolar o slot que falta.** Fabricaria um instante que a grade não produz.

**Velocidade (`Δ/h`) como autoridade de ranking.** Mudaria a unidade e tornaria
a penalidade do PR-06.2 incomparável.

**Tolerância temporal (±1 min, vizinho mais próximo, DTW).** Traria de volta a
pergunta que o alinhamento exato evita — quanto vale o deslocamento de relógio
—, agora multiplicada por três horizontes.
