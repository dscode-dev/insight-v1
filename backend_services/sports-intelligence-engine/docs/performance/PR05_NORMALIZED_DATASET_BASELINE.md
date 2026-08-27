# Baseline do ajuste causal e do dataset normalizado

Medido no **PR-05.5.2**, em **2026-08-25**. Este documento existe para que a
próxima execução tenha contra o que comparar, e **não** para declarar SLO.

Ele cobre o fecho do caminho de feature:

```
corpus publicado → HistoricalMatchState        PR-05.2    (baseline própria)
estado → MATCH_STATE_RAW_V2                    PR-05.4    (baseline própria)
V2 × grade × divisão → Parquet versionado      PR-05.5.1  (baseline própria)
Parquet cru → ajuste → Parquet normalizado     PR-05.5.2  (este documento)
```

---

## 1. O que estes números afirmam, e o que não afirmam

**Afirmam** que o ajuste exato — mediana e IQR em `Decimal`, sobre a população
inteira, sem quantil aproximado — cabe na memória na escala de produção, porque
o que fica retido são `array('d')` e não objetos.

**Afirmam** que a normalização é 1:1 **medida**, e não afirmada: linhas lidas,
linhas escritas e linhas do dataset cru são o mesmo número, e a soma das células
por estado fecha exatamente com a grade.

**Afirmam** que reajustar sobre a mesma referência produz a **mesma impressão**,
e que as impressões de conteúdo **não dependem do layout físico** — duas
execuções com tetos de memória diferentes escreveram números diferentes de
objetos e produziram as mesmas quatro impressões.

**Não afirmam** nada sobre outra máquina. O que sobrevive à troca de hardware
são as **propriedades**:

```
a memória do AJUSTE segue o LOTE            e não o tamanho da referência
o ajuste é EXATO                            quantis de tipo 7, população inteira
a normalização é 1:1                        lidas == escritas == cruas
a memória da CONSTRUÇÃO segue o teto        e o coeficiente está medido
a impressão é REPRODUTÍVEL                  sob teto, layout e execução diferentes
não há fallback                             40,7 % das células ROBUST saíram
                                            vazias, e nenhuma trouxe o valor cru
```

**O custo do insumo não entra em número nenhum daqui.** A construção do dataset
cru está medida no baseline do PR-05.5.1; misturá-la aqui faria o custo da
normalização parecer uma ordem de grandeza maior do que é.

---

## 2. Ambiente

```
CPU               Intel Core i9-14900KF · 32 threads
RAM               31 GB
SO                Windows 11 Pro (10.0.26200)
Python            3.14.6 (venv local)
PostgreSQL        17, em contêiner (`sie-postgres`, porta 5433)
object store      MinIO, mesmo host (porta 9000)
execução          local, sem concorrência com outra suíte
memória medida    `tracemalloc` — alocação PYTHON, e não RSS do processo
```

PostgreSQL em **configuração de fábrica**, deliberadamente — pelo mesmo motivo
dos baselines anteriores: um número medido contra um banco ajustado à mão mede
o ajuste.

A execução rodou **sozinha** contra o PostgreSQL, sob o mesmo lock consultivo do
PR-05.5.1 (`tests/support/db_exclusivity.py`).

---

## 3. Configuração medida

```
espaço              MATCH_STATE_RAW_V2 @ 2.0 · 105 definições
plano               MATCH_STATE_NORMALIZATION_PLAN_V1 @ 1.0
                    76 PASS_THROUGH_V1 · 29 ROBUST_MEDIAN_IQR_V1
                    impressão 26b80aa1c7a3143a…
normalizador        competition_median_iqr_reference @ 1.0
                    MEDIAN_IQR · COMPETITION · BEFORE_INSTANT(fronteira)
grade               LIVE_COMPARABLE_MINUTE_GRID_V1 · 91 cortes por partida
divisão             TEMPORAL_MATCH_ATOMIC_SPLIT_V1 · fronteira na mediana dos apitos

FIT_BATCH_ROWS               20.000
BUILD_BATCH_ROWS              2.000
DEFAULT_PART_ROWS            10.000
DEFAULT_MAX_PENDING_ROWS     15.000
```

---

## 4. O ajuste

```
linhas de referência lidas   44.317   (de 91.000 cruas; 46.683 na avaliação)
competições                       3
artefatos                        87   = 29 eixos ROBUST × 3 competições
  FITTED                          9
  INSUFFICIENT_SAMPLE            42
  DEGENERATE_SCALE               36

tempo                        13,65 s
vazão                         3.246 linhas de referência/s
pico de memória               21,1 MB
  por linha de referência        500 B
consultas de metadado            18
conferência do ajuste         0,06 s
```

**O número que este PR existe para produzir é o pico: 21,1 MB.**

O piso teórico da acumulação é `29 eixos × 44.317 linhas × 8 bytes` = **9,8 MB**.
O pico medido é **2,15× o piso** — o que sobra é o lote de leitura em trânsito,
os acumuladores de SHA-256 e o interpretador.

Isso confirma a decisão do `array('d')`. Guardar as mesmas observações como
`FeatureObservation` — objeto com `MatchId`, `FeatureAsOf`, `Decimal` e
impressão de corpus — custaria **centenas de megabytes** para responder às cinco
perguntas que o ajustador faz. E o ajuste continua **exato**: quantis de tipo 7
sobre a população inteira, em `Decimal`. O que foi comprimido é o
armazenamento, e não o método.

**Só 9 dos 87 artefatos ajustaram, e isso é o cenário e não o motor.** O corpus
do benchmark é sintético e tem três competições; a maioria dos eixos `ROBUST`
não junta trinta observações disponíveis por competição, ou junta e não tem
dispersão. O que importa medir aqui é que os três estados aparecem, são
persistidos, e produzem células vazias com o motivo certo — não que a
distribuição deles se pareça com a de futebol de verdade.

---

## 5. A construção normalizada

```
linhas lidas                 91.000
linhas escritas              91.000     ← o contrato 1:1, medido
células                   9.555.000     = 91.000 × 105

tempo                       943,35 s
vazão                            96 linhas/s
                             10.129 células/s
pico de memória              506,6 MB
pico em espera               14.926 / 15.000
partições abertas                 7
consultas de metadado            13
```

### A memória segue o teto, e o teto foi dimensionado por medição

Duas execuções, dois tetos, dois pontos:

```
teto 40.000   pico em espera 35.858   →  854,5 MB
teto 15.000   pico em espera 14.926   →  506,6 MB

M(P) ≈ 17,0 KB × P  +  259 MB
```

O **incremento** é o que uma linha normalizada em espera de fato retém: cento e
cinco `NormalizedCell`, cada uma com um objeto `float` próprio, mais o digesto
memoizado. O **componente fixo** é o caminho de leitura — os lotes decodificados
do PyArrow e os bytes transitórios do digesto.

A primeira versão trazia 40.000 **por analogia com o dataset cru**, e a analogia
estava errada: 40.000 implicam ~920 MB, contra os 370 MB da construção que
*produziu* aquelas linhas. Quinze mil põem o pico no mesmo envelope, e o custo
disso é nulo — o pedaço fecha em 10.000 de qualquer jeito, e o tempo não mudou
(962 s → 943 s, dentro do ruído).

**Baixar mais tem retorno decrescente.** O componente fixo de 259 MB é do
caminho de leitura, e não do escritor: um teto de 5.000 daria ~342 MB, e não
~85 MB. Reduzi-lo é mexer em `BUILD_BATCH_ROWS` e no modelo de linha — outro
trabalho, e nenhum benchmark o declarou bloqueado.

### O tempo, e o que ele é

96 linhas/s é da mesma ordem das 84 linhas/s da extração de features do
PR-05.5.1 — e a normalização não extrai nada, só divide. O custo está em criar
**9,55 milhões de `NormalizedCell`** e enquadrar os bytes IEEE-754 de cada uma
no digesto da linha.

Isto está **medido e não otimizado**, e a decisão é deliberada: o caminho é
offline, a memória é limitada, e otimizar o modelo de linha antes de existir um
consumidor que sofra com o tempo seria escolher onde economizar sem saber o que
custa. O número está aqui para que essa escolha seja feita com dado.

---

## 6. As duas famílias de disponibilidade

```
AVAILABLE                    6.185.659   64,7 %
SOURCE_VALUE_UNAVAILABLE     2.294.768   24,0 %
ARTIFACT_DEGENERATE_SCALE    1.074.573   11,2 %
                             ─────────
                             9.555.000   = 91.000 × 105
```

**A soma fecha exatamente com a grade.** Nenhuma célula some: o contrato 1:1
vale por linha e vale por célula.

Os 64,7 % de `AVAILABLE` são explicados pelo plano, e não por sorte: **76 dos
105 eixos são `PASS_THROUGH`** (72,4 %), e eles ficam disponíveis sempre que a
origem tem valor. Entre as células dos 29 eixos `ROBUST`, **40,7 % saíram sem
escala** — e nenhuma delas trouxe o valor cru disfarçado.

`ARTIFACT_INSUFFICIENT_SAMPLES` não aparece na contagem, e a ausência tem
explicação: onde o artefato ficou sem amostra, o valor cru também costumava
faltar — e a **pergunta da origem vem primeiro**. Atribuir esse caso ao artefato
mandaria alguém procurar dispersão numa feature que nunca teve valor.

---

## 7. A validação e a publicação

```
validação        1,30 s   ·   69.837 linhas/s   ·   34,2 MB   ·   18 objetos
publicação       0,02 s
```

A validação **relê os dezoito Parquet**, confere `sha256`, tamanho e contagem de
cada um, e **reconstrói as três impressões** a partir do que está gravado. Ela é
725× mais rápida que a construção porque lê **quatro colunas de trezentas e
trinta** — é para isso que o formato é colunar.

A memória dela é `O(linhas)` em tuplas compactas — 34,2 MB para 91.000 linhas,
ou ~394 B por linha —, e não segue o orçamento da construção. Isso é declarado
aqui pelo mesmo motivo do PR-05.5.1: dizer «o pipeline é limitado» seria
impreciso.

---

## 8. A identidade, e a prova que apareceu de graça

```
representação    e630e402141f7cbb…
normalizada      63bd2b7cbe83802b…
referência       0d613154a21d6e7d…
avaliação        5e2dc0da5116dbea…

reajuste independente   14,38 s   →   MESMA impressão de conjunto
```

Duas coisas estão provadas aqui, e a segunda não estava planejada.

**A primeira**: reajustar sobre a mesma referência produz um conjunto com id
diferente e **impressão idêntica** — a invariante central do PR, medida no
caminho completo e em volume, e não só sobre cenários sintéticos.

**A segunda**: as duas execuções deste baseline rodaram com **tetos de memória
diferentes**, e o teto muda o layout físico — 16 objetos contra 18, mediana de
3.276 linhas por objeto contra 4.277, fronteiras de descarga em lugares
distintos. **As quatro impressões saíram idênticas nas duas.**

Isso valida a ordem canônica em dois níveis: a impressão é sobre
`(partição, chave)`, e não sobre onde o escritor decidiu fechar um arquivo. Uma
impressão que dependesse do layout tornaria «este é o mesmo dataset?»
irrespondível toda vez que alguém mexesse num parâmetro de memória.

---

## 9. Os objetos

```
objetos                    18
bytes                     8,4 MB
por linha                   97 B
linhas por objeto          min 819 · mediana 4.277 · max 10.736
```

**97 bytes por linha para 105 valores e 210 máscaras** — o zstd sobre colunas de
texto repetido (`AVAILABLE`, `SOURCE_UNAVAILABLE`) comprime quase inteiramente
as duas famílias de máscara. O dataset cru mediu 120 B/linha para 105 valores e
105 máscaras.

O máximo (10.736) passa de `DEFAULT_PART_ROWS` porque um lote inteiro entra
antes de o pedaço fechar; o mínimo (819) é uma partição que acabou.

---

## 10. As consultas

```
ajuste          18 de metadado
construção      13 de metadado
```

**Nenhuma consulta de FATO**, e a ausência é o desenho: este PR não volta ao
corpus. O que ele lê são Parquet — do bucket, e não do banco. As consultas de
metadado seguem a EXECUÇÃO (transições, objetos, manifesto, trilha) e não o
conteúdo, exatamente como no PR-05.5.1.

Fora da conta de metadado ficaram leituras de linhagem — a versão crua e a
versão de corpus, uma vez cada — e elas são reportadas em vez de ignoradas: um
alvo novo sem classificação sairia da regra sem que ninguém notasse.

---

## 11. As execuções descartadas

**Três**, e nenhum número delas está nas seções acima:

1. **Ordem canônica falsa.** A primeira versão exigia chave globalmente
   crescente, e o benchmark recusou um fluxo correto de três competições. O
   defeito era do motor, e está corrigido (`ordering.py`).
2. **Relatório perdido na última linha.** O pipeline inteiro rodou e o `print`
   da moldura levantou `UnicodeEncodeError` num `stdout` `cp1252`. Nenhum número
   sobreviveu. `_relatar` agora cai para ASCII quando o console não aceita a
   moldura de traço.
3. **Teto superdimensionado.** Esta rodou até o fim e mediu 854,5 MB — e é dela
   que saiu o coeficiente que dimensionou o teto. Ela é citada no §5 e no §8
   como MEDIÇÃO, e não como baseline.

O baseline publicado é a **quarta** execução, `EXIT=0`, sozinha contra o banco.

---

## 12. O que este baseline NÃO mede

- **outra máquina.** Ver §1.
- **o custo do dataset cru.** Ele é o insumo, e está no baseline do PR-05.5.1.
- **a leitura ao vivo.** `bundle_of` existe e é exercitado pelo E2E; medi-lo é
  do PR-06, junto com o caminho que o consome.
- **similaridade, vizinhos, índice.** Não existem neste PR.
- **paralelização.** A construção é sequencial por decisão: paralelizar antes de
  medir o sequencial esconde onde o custo está.
- **uma distribuição realista de artefatos.** Nove `FITTED` em oitenta e sete é
  do cenário sintético. O que está medido é que os três estados existem e
  produzem o comportamento certo — ver §4.
