# PR-06.5 — Linha de base da agregação de vizinhos

> Todos os números deste documento vêm de execução medida. Nenhum deles foi
> produzido lendo desfecho: não houve rótulo de resultado, evento futuro,
> acurácia de previsão otimizada, lente de inteligência avaliada, nem ajuste
> supervisionado de espécie alguma.

Corpus: cenário com movimento, `partidas=96`, PostgreSQL e object store reais.

---

## 1. A escolha de `λ` — metodologia

`λ` foi escolhido **só pela geometria do retrieval**, por duas linhas de
evidência independentes que convergiram.

### Evidência A — o espalhamento local do top-K

Para que o vizinho mais distante do top-K receba `1/r` da massa do mais próximo:

```
w_max / w_min = exp(λ (d_max - d_min))     ⟹     λ = ln(r) / espalhamento
```

Com `r = 10`, sobre 40 consultas de estado e 36 de trajetória, `K = 20`:

```
                     p10       p50       p90
ESTADO
  d_min            0,0000    0,0000    0,0000
  d_max            0,0510    0,2710    0,6345
  espalhamento     0,0510    0,2710    0,6345
  λ para 10:1        3,98      8,50     50,98

TRAJETÓRIA
  d_min            0,0000    0,0000    0,0000
  d_max            0,0794    0,1434    0,4814
  espalhamento     0,0794    0,1434    0,3529
  λ para 10:1        6,52     16,06     28,99
```

### Evidência B — a concentração sobre a população real

```
ESTADO, K = 20
   λ      N_eff p10/p50/p90     peso máx p50   massa top-3 p50
  0,25     ~20 / ~20 / ~20          0,051           0,152
  8,00    8,24 /12,34 /19,79        0,115           0,333

TRAJETÓRIA, K = 20
   λ      N_eff p10/p50/p90     peso máx p50   massa top-3 p50
 16,00    8,25 /13,66 /16,97        0,092           0,277
```

Referência uniforme em `K = 20`: peso `0,05`, massa top-3 `0,15`.

### Selecionados

```
STATE_DISTANCE_WEIGHTING_V1        λ = 8,0     (evidência A: 8,50)
TRAJECTORY_DISTANCE_WEIGHTING_V1   λ = 16,0    (evidência A: 16,06)
```

Os dois evitam os dois extremos que o contrato manda evitar: nem quase uniforme
(`λ = 0,25` deixa `N_eff` em 19,99 de 20), nem dominado por um vizinho (`p10`
fica em 8,24 e 8,25, muito acima de 1).

### O contrafactual

```
λ = 8 aplicado à TRAJETÓRIA   →   N_eff p50 = 16,50 / 20
```

O mesmo número produziria concentrações diferentes nos dois caminhos por
acidente de escala. É esta a evidência empírica do ADR-0051.

### Como a primeira grade quase deu a resposta errada

A grade inicial ia de `0,25` a `4,0` e mostrava `N_eff ≈ K` em toda ela — o que
lia como «nenhum `λ` diferencia». Medir o **espalhamento** mostrou que o `λ`
necessário era `8,50`, mais que o dobro do maior valor da grade. A grade é que
não alcançava a resposta; escolher `4,0` por ser o maior valor presente teria
sido escolher pelo formato da grade, e não pelos dados.

---

## 2. Concentração no pipeline real

Agregação sobre o top-K exato produzido pelo caminho projetado do PR-06.4:

```
                consultas   k devolvido   N_eff p50    N_eff min/max
ESTADO              24         20            11,79      6,22 / 19,85
TRAJETÓRIA          20         20            13,20      7,28 / 16,40
```

Compatível com a varredura de sensibilidade (12,34 e 13,66), sobre um conjunto
de consultas menor.

---

## 3. `TRAJECTORY_TOP5_GEOMETRIC_FLATNESS` — o achado, e o seu alcance

A varredura mostrou `N_eff ≈ 5,00` no top-5 de trajetória para **todo** `λ`
testado. Duas explicações eram possíveis, e elas levam a conclusões opostas:

- **arredondamento** — as distâncias diferem e `float64` engoliu a diferença.
  Seria um defeito do codec de projeção ou da distância.
- **geometria** — as distâncias chegam iguais. Nada a consertar.

### A prova, em `decimal` de 60 dígitos

Recalculando `N_eff` a partir das **mesmas** distâncias `float64`:

```
   λ       N_eff (float64)      N_eff (decimal-60)    peso máx / peso mín
   8,0    4,999999999999999    5,000000000000000           1,000000
  16,0    4,999999999999999    5,000000000000000           1,000000
  32,0    4,999999999999999    5,000000000000000           1,000000
 128,0    4,999999999999999    5,000000000000000           1,000000
1024,0    4,999999999999999    5,000000000000000           1,000000
```

```
vetores com d_max == d_min   36 de 36
valores distintos por vetor  min 1, max 1
```

**Não é arredondamento.** As cinco distâncias chegam **idênticas bit a bit**, e
nenhuma precisão separa números iguais. A razão peso-máximo / peso-mínimo
permanece exatamente `1,000000` mesmo em `λ = 1024`.

Classificação: **geometria medida — não bloqueador**. A ponderação amplifica
diferenças que existem; ela não fabrica diferenças que não existem, e aumentar
`λ` para forçar discriminação seria exatamente fabricá-las.

### A estrutura de empates — e o limite do que o achado prova

```
                    consultas   valores distintos p50   vizinhos a d=0 p50 (máx)
ESTADO K=5              40           3,0 (min 3)                2 (2)
ESTADO K=20             40          14,0 (min 11)               2 (2)
TRAJETÓRIA K=5          36           1,0 (min 1, max 1)         5 (5)
TRAJETÓRIA K=20         36           3,0 (min 2, max 4)         7 (14)
```

Os cinco vizinhos não são «quase equidistantes»: são **idênticos, a `d = 0`**,
em 34 das 36 consultas.

**A causa está no cenário, e não no motor.** `trajectory_scenario` gera as
partidas alternando entre três formas de movimento — subindo, descendo e
estável. Duas partidas da mesma forma, no mesmo minuto, têm a mesma trajetória
bit a bit; com 96 partidas e três formas, cada consulta encontra dezenas de
duplicatas exatas antes da primeira vizinha de verdade.

```
O QUE O ACHADO PROVA    a planura não é arredondamento, e a ponderação
                        se comporta corretamente sobre distâncias iguais

O QUE ELE NÃO PROVA     nada sobre a geometria de trajetória em PRODUÇÃO,
                        onde as trajetórias não saem de três moldes
```

### Débito registrado — `TRAJECTORY_CORPUS_DUPLICATE_DEGENERACY`

O `λ` de trajetória repousa sobre uma população mais fraca que o de estado: 3
valores de distância distintos por top-20 contra 14. O espalhamento de `0,1434`
é, na prática, a distância entre o aglomerado em `d = 0` e o aglomerado
seguinte — uma distribuição de dois ou três pontos, e não um contínuo.

A aritmética que produziu `λ = 16` está correta sobre a população medida. O que
não se pode afirmar é que a população represente produção.

**Não é bloqueador e não reabre a escolha** — `λ = 16` está congelado para a V1.
É a delimitação honesta do que a medição sustenta, e o gatilho para revalidar
quando houver corpus representativo. O `λ` de estado não sofre da mesma
limitação.

---

## 4. Desempenho da agregação pura

Medido **depois** que o resultado exato já existe. O retrieval não entra nestes
números, que é onde o contrato manda medir.

### Escala do núcleo

```
     K      p50        p95        p99      por vizinho    pico de memória
     5    0,0095     0,0103     0,0194 ms    1,90 us     1,9 KiB (384 B/viz)
    10    0,0140     0,0172     0,0276 ms    1,40 us     2,4 KiB (246 B/viz)
    20    0,0229     0,0266     0,0309 ms    1,14 us     5,1 KiB (262 B/viz)
    50    0,0490     0,0582     0,0921 ms    0,98 us     8,4 KiB (171 B/viz)
   100    0,0950     0,1176     0,1729 ms    0,95 us    23,4 KiB (239 B/viz)
  1000    0,9158     1,0239     1,0718 ms    0,92 us   169,7 KiB (174 B/viz)
```

### Complexidade

O custo **por vizinho** cai de `1,90 µs` para `0,92 µs` conforme `K` cresce —
amortização de sobrecarga fixa, que é a assinatura de `O(K)` com termo
constante. A razão máx/mín de `2,07×` é dirigida pelo `K` pequeno, e não por
crescimento.

Um comportamento `O(K²)` faria o custo por vizinho **crescer** com `K`; de `K=5`
a `K=1000` (200× os vizinhos) o tempo cresce `96×`, e não `40 000×`.

Memória: `~174–384 B` por vizinho, estável. `O(K)`, sem acumulação entre
agregações repetidas.

### Os gates (`K` ≤ 20 → p95 ≤ 2 ms; `K` ≤ 100 → p95 ≤ 5 ms)

```
K <= 20    p95 = 0,0266 ms   contra 2 ms    margem  75×
K <= 100   p95 = 0,1176 ms   contra 5 ms    margem  42×
```

### No pipeline real

```
                consultas    p50 / p95 / p99 (ms)
ESTADO              24      0,4458 / 0,5150 / 0,5630
TRAJETÓRIA          20      0,9173 / 1,0350 / 1,0350
```

Mais caro que o núcleo puro em `K = 20` (`0,0229 ms`) porque inclui a montagem
do resumo de evidência sobre os objetos reais de vizinho — travessia do
detalhamento por horizonte, na trajetória. Ainda assim, dentro do gate de 2 ms
com margem de 4× e 2×.

---

## 5. Leituras de armazenamento durante a agregação

```
PostgreSQL           0
Parquet              0
MinIO                0
fato canônico        0
```

Medido no E2E com três contadores independentes, sobre o bloco que começa
**depois** que o resultado exato existe — e com todas as leituras derivadas do
agregado dentro do bloco, para que um acesso preguiçoso não passasse.

Um teste companheiro roda a recuperação *dentro* do bloco e exige que o contador
acuse: sem ele, um instrumento cego daria zero por não estar olhando.

---

## 6. O que a agregação continua não fazendo

Nenhuma migração nova — `0014` continua sendo a última. Nenhum acesso a
desfecho. Nenhuma fusão de estado com trajetória. Nenhum limiar sobre `N_eff`.
Nenhuma afirmação sobre o que os vizinhos implicam para a partida consultada.
