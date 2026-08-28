# `MULTI_HORIZON_DISPLACEMENT_FIXED_PROFILE_IQR_PENALTY_V1` — a distância

**PR:** 06.3 · **ADR:** [0046](../architecture/adr/0046-availability-aware-trajectory-dissimilarity.md)

## A fórmula

```
              Σ_{(h,i)∈S_T} (Δ^q_{h,i} − Δ^c_{h,i})²  +  p·(n − s)
D_T(q,c) =  ────────────────────────────────────────────────────      p = 1
                                  n = |H| · m
```

Ela **reusa a forma do PR-06.2** de propósito: denominador fixo, penalidade
uniforme, pesos iguais. As três decisões já foram justificadas no ADR-0044, e
mudá-las aqui faria a comparação entre estado e trajetória medir duas coisas.

**O que muda é a unidade da célula, e o que ela contém:**

```
estado        célula = eixo                (q_i − c_i)²    diferença de NÍVEL
trajetória    célula = (horizonte, eixo)   (Δ^q − Δ^c)²    diferença de MOVIMENTO
```

## A penalidade continua valendo `1`, e a unidade continua fazendo sentido

`Δ` é a diferença entre dois valores normalizados pelo IQR da competição, logo
`Δ` vive em **unidades de IQR** — as mesmas do estado. É por isso que não
dividimos por `h`: `Δ/h` viveria em «IQR por minuto», e uma penalidade de `1`
ali seria um número sem relação com o do PR-06.2.

## A reversão custa o dobro ao quadrado

```
Δ^q = +2   e   Δ^c = −2      →   (Δ^q − Δ^c)² = (2·Δ^q)² = 16
```

Dois jogos no mesmo estado atual, um subindo e outro descendo, ficam a
**dezesseis** unidades numa célula em que dois jogos subindo juntos ficam a
**zero**. É esse contraste que o PR existe para produzir.

## O piso ganhou uma dimensão

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

**Um horizonte não é evidência.** Um candidato com o horizonte de um minuto
perfeito e os outros dois vazios teria, num perfil de vinte eixos, vinte células
de sessenta — e zero informação sobre tendência.

**E um horizonte só CONTA se sozinho passaria no piso do PR-06.2**: pelo menos
quatro eixos, e pelo menos três quintos deles. Um horizonte com um eixo de vinte
existe estruturalmente e não descreve movimento.

## **Oito células é um MÍNIMO ABSOLUTO, e não o piso**

`4 eixos × 2 horizontes = 8 células` é o produto dos dois mínimos. **Ele não
autoriza nada sozinho.** O piso que decide um par é o **efetivo**:

```
E_s = max( 8, ceil(3n/5) )        n = |H| · m     piso de células do par
E_q = max( 8, ceil(3n/5) )                        piso de células da query
E_h = max( 4, ceil(3m/5) )                        piso de eixos por horizonte
```

| `m` | `n` | absoluto | racional | **efetivo** | quem decide |
|---:|---:|---:|---:|---:|---|
| 3 | 9 | 8 | 6 | **8** | absoluto |
| 4 | 12 | 8 | 8 | **8** | empate |
| 5 | 15 | 8 | 9 | **9** | racional |
| 6 | 18 | 8 | 11 | **11** | racional |
| 15 | 45 | 8 | 27 | **27** | racional |

**Dois horizontes minimamente evidenciais dão exatamente oito células — e com
`m = 6` isso é RECUSADO**, porque oito é menor que onze. Os dois pisos não se
substituem.

E o mínimo absoluto **nunca domina estritamente** num perfil admissível:
`ceil(3n/5) < 8` exige `m <= 4`, e `minimum_profile_axes = 4` corta onde os dois
empatam.

A derivação é **inteira** (`-((-3n) // 5)`), e a política carrega a versão dela
— `MAX_ABSOLUTE_CEIL_RATIONAL_V1` — na própria impressão: a fórmula é parte do
contrato, e não só os números que ela consome.

O construtor confere a coerência dos mínimos: três horizontes exigidos com oito
células é recusado, porque o mínimo mais frouxo nunca teria efeito.

### A fronteira, com `m = 15` e `n = 45`

```
piso efetivo de células   E_s = max(8, ceil(135/5)) = 27
piso de horizontes        >= 2 evidenciais
piso por horizonte        E_h = max(4, ceil(45/5))  = 9

3 horizontes cheios   s = 45   completo
2 horizontes cheios   s = 30   admitido      (30 >= 27)
1 horizonte cheio     s = 15   RECUSADO      nem 27, nem 2 horizontes
```

**No perfil real da competição o piso é 27, e não 8.** A diferença é de
dezenove células.

### Três motivos de recusa, e não um

```
INSUFFICIENT_SHARED_HORIZONS         o par não alcança dois horizontes
INSUFFICIENT_PER_HORIZON_COVERAGE    alcança, e nenhum tem E_h eixos
INSUFFICIENT_SHARED_TRAJECTORY_CELLS os horizontes bastam, e s < E_s
```

O diagnóstico vai **do relógio para a feature**: um par no começo do período
também não alcança células bastante, e reportá-lo como «poucas células»
apontaria para a atrição quando a causa é o minuto. Nenhum dos três é
`is_structural` — todos medem ausência de dado.

## O que ela NÃO é

### Não é métrica

```
vale        D_T >= 0 · D_T(q,c) = D_T(c,q) · D_T(x,x) = 0 quando x é COMPLETO
NÃO vale    D_T(x,x) = 0 quando x é INCOMPLETO
```

`D_T(x,x) = u/n > 0`: as células que faltam continuam custando. `is_metric`
devolve `False`, e a desigualdade triangular não é afirmada nem testada.

### Não tem pesos por horizonte

Nem `1m` valendo 3 e `5m` valendo 1, nem pesos por família. Não há avaliação que
justifique importância temporal diferente — e a medição do §199 é o insumo para
que um dia haja.

> **Medido:** `5m` contribui com p50 de **52 %** do observado, contra 11 % de
> `1m` e 4 % de `3m`. Isso é evidência para um estudo futuro, e **não** motivo
> para corrigir nada agora.

### Não preenche ausência

Uma célula ausente custa `1`, e não `0`. Preencher o extremo que falta com o
valor da âncora produziria `Δ = 0` — estabilidade inventada, e o blocker mais
perigoso deste PR: ela não falha, ela mente com aparência de calma.

Dois ausentes na mesma célula continuam ausentes: dois desconhecidos não são
evidência de movimento igual.

### **Não se soma ao estado**

```
D_state         PR-06.2     nível
D_trajectory    PR-06.3     movimento
D_total         NÃO EXISTE
```

`D = 0,2` e `D_T = 0,2` **não são a mesma grandeza**: o primeiro é média de
diferença de nível sobre `m` eixos, o segundo é média de diferença de movimento
sobre `n = 3m` células.

Tipos separados — `AvailabilityAwareNeighbor` e `TrajectoryHistoricalNeighbor` —
impedem que alguém os some por acidente. `CompareStateAndTrajectory`
**apresenta** os dois; ele não combina, e há guarda arquitetural que lê o corpo
dele procurando `0.5`, `alpha`, `beta`, `weight` e `combined`.

## A ordem do top-K

```
1. dissimilaridade           ASC
2. células compartilhadas    DESC
3. horizontes compartilhados DESC    ← novo neste PR
4. chave canônica            ASC
```

**O terceiro critério.** Com `D_T` e contagem de células iguais, a evidência
espalhada em três horizontes descreve a forma melhor que a mesma quantidade
concentrada em dois: doze células em `1m` e `3m` dizem o que aconteceu em três
minutos; oito em `1m`, `3m` e `5m` dizem o que aconteceu em cinco.

**A cobertura continua não liderando** — ela já está dentro do número pela
penalidade.

O heap inverte a quádrupla **inteira**, posição a posição. Há testes de prefixo
com empate deliberado em cada um dos três primeiros critérios.

## A evidência reconstrói o número — e o momento

```
D_T = (Observed_T + Missing_T) / n
```

E também **de onde ele veio no tempo**. Dois vizinhos com o mesmo `D_T` podem
significar coisas opostas:

```
todo o observado em `1m`    eles divergiram AGORA
todo o observado em `5m`    eles vinham divergindo
```

Por isso a evidência carrega a contribuição por horizonte — eixos
compartilhados, observado, incerteza e cobertura de cada um — e a contagem de
**reversões**: em quantas células os dois se moveram em direções opostas.

## Determinismo

| variação | teste |
|---|---|
| ordem dos candidatos | 10 permutações + inversa |
| tamanho do lote | 1, 7, 128, 512, 2048, 4096 |
| ordem das linhas de lookback | indexadas por instante, não por chegada |
| layout do Parquet | duas execuções sobre o dataset real |
| `K` | prefixo, com empate nos três primeiros critérios |
