# Baseline da recuperação de trajetória

Medido no **PR-06.3**, em **2026-08-27**. Este documento existe para que a
próxima execução tenha contra o que comparar, e **não** para declarar SLO.

---

## 1. O que estes números NÃO são

**Não são SLO** (§211). Força bruta exata não tem promessa de latência; ela é do
caminho indexado, que é do PR-06.4. Trajetória mais cara que estado **não é
blocker por si só** (§248).

**Não são o custo do insumo.** Corpus, dataset cru e normalização estão medidos
nos baselines do PR-05.

**Não são um resultado em escala de produção.** Noventa e seis partidas, uma
competição, uma temporada.

**E o estudo de horizontes não escolhe nada** (§201, §202). Ele percorre `{1,3}`
e `{1,3,5}` e **reporta**.

## O que eles afirmam

```
o universo é o MESMO do PR-06.2      mesma impressão, mesma política
a trajetória SEPARA                  razão de 61x entre o melhor e o pior D_T
não há N+1                           218 objetos para 5.123 candidatos
a memória segue o LOTE e o K         13,9 MB para 109 queries
o começo do período NÃO é utilizável e a atrição está medida
```

---

## 2. O cenário

```
partidas                96
times                    6
chutes por time      a cada 3 minutos, com xG em rampa
formas de curva      SUBINDO · DESCENDO · ESTAVEL, alternadas por partida
linhas do dataset    8.736  (4.277 referência)
perfil base             15 eixos  (12 de xG em janela móvel + 3 de contexto)
espaço de trajetória 3 x 15 = 45 células
universo por query      47 candidatos
```

### A densidade precisou subir, e o motivo saiu de medição

A janela de xG tem dez minutos. Com **quatro** chutes por tempo — a densidade
do PR-06.2 — o conteúdo dela é o **mesmo** em `t`, `t-1`, `t-3` e `t-5`, e todo
deslocamento sai zero:

```
primeira versão do cenário   24 células, todas com Δ = 0
```

As curvas existiam no jogo e **não existiam na trajetória**. Com chutes a cada
três minutos e xG em rampa, a janela troca de conteúdo entre um minuto e o
seguinte — e o deslocamento passa a existir: 155 células com movimento nos seis
primeiros candidatos.

**Os eixos de contexto continuam com `Δ = 0` dentro da partida**, e isso não é
defeito: `ctx_same_comp_prev_gap_hours_*` é um fato de pré-jogo, e vale o mesmo
em todo corte. Ter metade do perfil parada e metade se movendo é exatamente a
mistura de «estável» e «crescente/decrescente» que o §179 pede.

---

## 3. Ambiente

```
CPU               Intel Core i9-14900KF · 32 threads
RAM               31 GB
SO                Windows 11 Pro (10.0.26200)
Python            3.14.6 (venv local)
PostgreSQL        17, em contêiner (porta 5433)
object store      sistema de arquivos local
memória medida    `tracemalloc` — alocação PYTHON, e não RSS
```

## 4. Configuração medida

```
janela          SAME_PERIOD_FIXED_HORIZON_1_3_5_V1        b77b35c642bb3242
perfil          ROBUST_MULTI_HORIZON_DISPLACEMENT_TRAJECTORY_V1   f1f854d1489959c2
cobertura       MULTI_HORIZON_MINIMUM_EVIDENCE_COVERAGE_V1        4056969512f15935
distância       MULTI_HORIZON_DISPLACEMENT_FIXED_PROFILE_IQR_PENALTY_V1  4c6418fcdf648efa
penalidade      p = 1  (IQR²)
denominador     FIXED_PROFILE_DENOMINATOR_V1
float           IEEE754_FLOAT64_FSUM_V1
K               10
```

Ajuste: **15 FITTED**, 0 `DEGENERATE_SCALE`, 14 `INSUFFICIENT_SAMPLE`.

---

## 5. A aplicabilidade

```
queries                 120
  não aplicáveis          2   (PRE_MATCH)
  sem evidência           9   (começo de período)
  aplicáveis            109
```

**Onze por cento das queries não têm trajetória**, e as duas causas são
diferentes: `PRE_MATCH` não tem passado dentro da fase; o começo de cada período
tem passado insuficiente. Nenhuma das duas é defeito de dado.

## 6. A escada de minuto

Faixas *period-local* do segundo tempo, com a mediana de horizontes estruturais:

| faixa | n | horizontes p50 | min | max |
|---|---|---|---|---|
| 46–48 (1º ao 3º do período) | 3 | **1,0** | 0 | 1 |
| 49–50 (4º ao 5º) | 2 | **2,0** | 2 | 2 |
| 51–60 (6º ao 15º) | 10 | **3,0** | 3 | 3 |
| 61+ (16º em diante) | 30 | **3,0** | 3 | 3 |

**A trajetória fica plenamente utilizável a partir do sexto minuto de cada
período.** Esse é o número que o PR-06.4 e o PR-06.6 precisam para saber quando
o sinal existe.

## 7. Uma query

```
competição              PREMIER_LEAGUE
âncora                  FIRST_HALF:004
universo                     47 candidatos
elegíveis                    42  (89,4 %)
sem evidência                 5
K                          10/10
duração                   389,7 ms
memória                    13,6 MB
objetos lidos                 2
bytes lidos             892.300
linhas de origem            143
```

`143 = 47 candidatos × 3 linhas + 2` — a âncora e os dois horizontes que existem
no minuto 4 do primeiro tempo.

## 8. Cento e nove queries

```
p50                     404,7 ms
p95                     420,6 ms
p99                     426,9 ms
max                     427,9 ms
total                    44,20 s

memória do lote          13,9 MB
avaliações/s                115
objetos lidos               218
bytes lidos          97.260.700
linhas de origem         20.531
linhas por objeto          94,2
```

**A memória não cresce com o lote**: 13,6 MB para uma query, 13,9 MB para cento
e nove — sobre um universo de 47 candidatos × 4 linhas × 15 eixos por query.

## 9. Os pisos efetivos desta competição

**Oito células é um mínimo absoluto, e não o piso.** No perfil real da
competição o piso que decide é quase quatro vezes maior:

```
competicao              PREMIER_LEAGUE
eixos do perfil (m)     15
celulas (n = 3m)        45

minimo absoluto           8      <- 4 eixos x 2 horizontes
piso racional ceil(3n/5) 27
PISO EFETIVO E_s         27      (o racional decide)
piso de query E_q        27
piso por horizonte E_h    9      max(4, ceil(45/5))

algoritmo               MAX_ABSOLUTE_CEIL_RATIONAL_V1
```

**Ler `minimum_shared_trajectory_cells = 8` como «oito bastam» erraria por
dezenove células neste perfil.** Um candidato com dez células compartilhadas
tem `10/45 = 22 %` de cobertura e passaria pelo mínimo absoluto com folga — e é
recusado, porque três quintos de quarenta e cinco são vinte e sete.

E a composição não é hipotética: dois horizontes minimamente evidenciais dariam
`9 + 9 = 18` células aqui, e dezoito continua abaixo de vinte e sete.

### O mínimo absoluto nunca domina estritamente

```
ceil(3n/5) < 8   exige   n <= 12   isto é   m <= 4
minimum_profile_axes = 4          corta exatamente em m = 4
```

Em `m = 4` os dois pisos **empatam** em oito. Acima disso é sempre o racional.
Abaixo, o perfil não é admissível. **O mínimo absoluto é um chão que, sob a V1,
nunca é o teto de ninguém** — e isso é um achado, não um defeito: ele existe
para o caso em que a política mudar, e o golden que o prova está no harness.

### A derivação é inteira, e a razão não é a que parece

O piso usa `-((-3n) // 5)`, e não `math.ceil(0.6 * n)`. **Não porque o float
erre num perfil de futebol** — foram medidos os dois milhões de primeiros `n`
e não há uma divergência. É porque a forma inteira é exata *por construção*,
enquanto a de ponto flutuante é correta apenas sob um argumento de
arredondamento que teria de ser reestabelecido a cada mudança de numerador,
denominador ou faixa. E esse argumento tem fim:

```
n = 9_999_999_999_999_997     float  5_999_999_999_999_997
                              exato  5_999_999_999_999_999
```

### A recusa, por piso — medida

Os três pisos recusam por causas diferentes, e o relatório separa. **Neste
corpus um só deles age:**

```
pares avaliados                        940
  INSUFFICIENT_SHARED_TRAJECTORY_CELLS  10   (1,1 %)
  INSUFFICIENT_SHARED_HORIZONS           0
  INSUFFICIENT_PER_HORIZON_COVERAGE      0
  ADMITIDOS                            930

no lote inteiro (109 queries):
  INSUFFICIENT_SHARED_TRAJECTORY_CELLS  30   = a atrição temporal inteira
```

**A classificação é exclusiva e exaustiva.** `refusal_reason` devolve o
PRIMEIRO piso que falhou, na ordem relógio → feature, logo os números somam sem
sobreposição — e a soma dos três fecha com `trajectory_ineligible_count`, o que
é verificado no E2E.

**Os outros dois motivos valerem zero é um resultado, e não uma lacuna.** As
queries deste recorte alcançam três horizontes em 40 dos 45 minutos medidos, e
os eixos de um horizonte alcançado estão quase sempre disponíveis: o que sobra
é atrição de CÉLULA. O diagnóstico separado existe para o corpus em que isso
deixar de ser verdade — o começo do período —, e ali ele aparece como recusa da
QUERY, antes de qualquer par.

### A margem sobre o piso

```
margem sobre E_s    min 3   p10 18   p50 18   p90 18   max 18   (n=1.090)
```

**Todo vizinho do top-K satisfaz o piso efetivo**, e a mediana está dezoito
células acima dele — `27 + 18 = 45`, a trajetória completa. O mínimo de **3**
é o vizinho mais apertado que entrou: trinta células de quarenta e cinco, com
dois horizontes cheios.

---

## 10. A atrição

```
universo somado          5.123
  elegíveis              5.093
  sem evidência             30
  estruturais                0

vizinhos no piso         60 de 1.090   (5,5 %)
células em reversão            16
```

**A atrição por evidência é baixa neste cenário** (0,6 %), e o motivo é o
recorte: 99 das 109 queries aplicáveis estão em minutos com três horizontes. A
atrição real vive no começo do período, e ela aparece como **recusa da query**
(§5), não como recusa do candidato.

## 11. As coberturas e os horizontes

```
cobertura da query       min 0,667  p10 1,000  p50 1,000  max 1,000  (n=109)
cobertura dos pares      min 0,533  p10 0,800  p50 1,000  max 1,000  (n=940)
cobertura do top-K       min 0,667  p10 1,000  p50 1,000  max 1,000  (n=1.090)

horizontes da query      min 2  p50 3  max 3
horizontes dos pares     min 2  p50 3  max 3
horizontes do top-K      min 2  p50 3  max 3
```

O mínimo de **2** em toda linha é o piso funcionando: nada abaixo dele chega ao
top-K.

## 12. `D_T` e a incerteza

```
D_T                min 0,000  p10 0,000  p50 0,000  p90 0,181  max 5,077  (n=1.090)
fração incerta     min 0,000  p10 0,000  p50 0,000  p90 1,000  max 1,000  (n=285)
```

A mediana de `D_T` é **zero**: num corpus de seis times com três formas de
curva, muitos jogos se moveram igual. A cauda superior — `5,08` — é o par que se
moveu em direções opostas.

## 13. A contribuição por horizonte

```
1m     min 0,000  p10 0,000  p50 0,112  p90 0,686  max 0,707  (n=216)
3m     min 0,000  p10 0,000  p50 0,043  p90 0,500  max 0,869  (n=216)
5m     min 0,046  p10 0,250  p50 0,521  p90 1,000  max 1,000  (n=216)
```

**O horizonte de cinco minutos domina o observado**: p50 de 52 %, contra 11 % de
`1m` e 4 % de `3m`. É o resultado esperado da aritmética — `Δ_5` é o maior dos
três deslocamentos numa curva monótona, e o quadrado amplifica —, mas **isso é
uma medição, e não uma dedução**.

**E é evidência para um estudo futuro, não motivo para corrigir agora** (§200).
Ponderar horizontes exigiria uma medida de acerto, e não há rótulo de verdade
com que construí-la antes do PR-06.5. O número existe para que essa discussão
comece com um dado.

## 14. Estado contra movimento

```
sobreposição do top-K   min 0,400  p10 0,600  p50 0,700  p90 0,800  max 0,800  (n=60)

p50 do estado            37,3 ms
p50 da trajetória       404,7 ms
amplificação de objetos   1,21x
```

**Sobreposição de 70 % na mediana, e nunca 100 %.** Os dois rankings compartilham
a maior parte do top-K e discordam consistentemente numa parte dele — que é
exatamente o sinal novo: os jogos mais parecidos **agora** não são sempre os que
se moveram parecido.

**DIAGNÓSTICO, e não métrica de correção** (§196). Uma sobreposição baixa pode
ser o comportamento desejado.

**A latência é 11× a do estado, e a I/O é só 1,21×.** O custo **não** é de
leitura: é de CPU na montagem — `47 candidatos × 4 linhas × 15 eixos` por query,
contra `47 × 1 × 15` do estado. Ver §16.

## 15. A discriminação de direção, sobre dados reais

Âncora `SECOND_HALF:060`, oito candidatos no mesmo instante:

```
D_T mínimo         0,1333
D_T mediano        0,8793
D_T máximo         8,1214
razão max/min      60,9x

células em reversão      46
sobreposição do top-K   100 %
```

| candidato | `D_T` | reversões |
|---|---|---|
| `4acc10d4` | 0,1333 | 0 |
| `08130fcd` | 0,2001 | 0 |
| `0619e6e9` | 0,8005 | **17** |
| `00ce6d4d` | 0,8248 | 0 |
| `c989f5e3` | 0,9339 | **17** |
| `1537b93c` | 1,0250 | 0 |
| `f027a7ea` | 3,5720 | 0 |
| `4f422c05` | **8,1214** | **12** |

**Oito jogos no mesmo minuto da mesma competição, e uma razão de 61× entre o
mais e o menos parecido em movimento.** Os três candidatos com reversão de
direção estão entre os mais distantes.

> A sobreposição de 100 % nesta âncora específica é do tamanho do universo: com
> oito candidatos e `K = 50`, os dois rankings devolvem os mesmos oito. O que
> difere é a **ORDEM**, e é ela que a dispersão de `D_T` mede.

## 16. O estudo de horizontes

| conjunto | queries | células | elegíveis p10 | p50 | zeradas |
|---|---|---|---|---|---|
| `{1,3}` | 30/30 | 30 | 47,0 | 47,0 | 0 |
| **`{1,3,5}` ← V1** | 30/30 | 45 | 47,0 | 47,0 | 0 |

`{1}` **não entra na tabela**: a política exige dois horizontes, e um conjunto
de um só é recusado no construtor.

Neste recorte — queries já aplicáveis, em minutos com três horizontes — os dois
conjuntos admitem os mesmos candidatos. A diferença entre eles está no
**alcance da aplicabilidade**, e essa é a escada da §6: com `{1,3}` a trajetória
seria utilizável a partir do minuto 49 em vez do 51.

**A decisão fica em `{1,3,5}`** (§201). Não há evidência de blocker, e o alcance
extra de dois minutos não justifica perder a escala de cinco.

---

## 17. As dívidas de escala medidas

**A latência é de CPU, e não de I/O.** 405 ms de p50 com amplificação de objetos
de 1,21×. A montagem faz `47 × 4 × 15 = 2.820` avaliações de máscara e
subtração por query, em Python. O caminho indexado do PR-06.4 é onde isso se
resolve — e agora existe um número contra o qual medir.

**A releitura por query continua** (herdada do PR-06.1). 97 MB para 109 queries,
sem cache, por decisão (§138).

**A busca da query por varredura continua** (herdada do PR-06.1), agora
retendo `|H|` linhas em vez de uma — na **mesma** varredura.

**A atrição de começo de período é estrutural, e não uma dívida.** Ela não se
resolve com índice nem com cache: o começo do período não tem passado dentro
dele. O que o número da §6 informa é **quando** o sinal de trajetória existe.

## 18. O que este baseline NÃO mede

- **escala de produção.** 96 partidas, 1 competição, 1 temporada.
- **múltiplas competições.** O §149 pede as cinco quando o corpus as tiver.
- **prorrogação.** O cenário não a produz; a aritmética dela tem teste de
  unidade.
- **o caminho indexado.** É do PR-06.4, e é ele que terá SLO.
- **`Recall@K`.** Não há índice aproximado contra o que medir.
- **qual horizonte «deveria» pesar mais.** Ver §12: há a medição, e não há a
  medida de acerto que permitiria decidir.
