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
o que fica retido são `array('d')` e não objetos. E dizem quanto isso custa
nesta máquina.

**Afirmam** que a normalização é 1:1 medida, e não afirmada: as linhas lidas, as
escritas e as do dataset cru são o mesmo número.

**Afirmam** que reajustar sobre a mesma referência produz a **mesma impressão**
— a invariante central do PR, medida no caminho completo e em volume, e não só
sobre cenários sintéticos.

**Não afirmam** nada sobre outra máquina. O que sobrevive à troca de hardware
são as **propriedades**:

```
a memória do AJUSTE segue o LOTE            e não o tamanho da referência
o ajuste é EXATO                            quantis de tipo 7, população inteira
a normalização é 1:1                        lidas == escritas == cruas
o teto do escritor é respeitado             sem tolerância
a identidade é REPRODUTÍVEL                 dois ajustes, uma impressão
as três impressões são DISTINTAS            global, referência e avaliação
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

### Exclusividade do banco

A execução rodou **sozinha** contra o PostgreSQL, sob o mesmo lock consultivo do
PR-05.5.1 (`tests/support/db_exclusivity.py`).

---

## 3. Configuração medida

```
espaço              MATCH_STATE_RAW_V2 @ 2.0 · 105 definições
plano               MATCH_STATE_NORMALIZATION_PLAN_V1 @ 1.0
                    76 PASS_THROUGH_V1 · 29 ROBUST_MEDIAN_IQR_V1
normalizador        competition_median_iqr_reference @ 1.0
                    MEDIAN_IQR · COMPETITION · BEFORE_INSTANT(fronteira)
grade               LIVE_COMPARABLE_MINUTE_GRID_V1 · 91 cortes por partida
divisão             TEMPORAL_MATCH_ATOMIC_SPLIT_V1 · fronteira na mediana dos apitos
lote do ajuste      FIT_BATCH_ROWS
lote da construção  BUILD_BATCH_ROWS
pedaço              DEFAULT_PART_ROWS
teto do escritor    DEFAULT_MAX_PENDING_ROWS
```

---

<!-- MEDIDAS -->

---

## 9. O que este baseline NÃO mede

- **outra máquina.** Ver §1.
- **o custo do dataset cru.** Ele é o insumo, e está no baseline do PR-05.5.1.
- **a leitura ao vivo.** `bundle_of` existe e é exercitado pelo E2E; medi-lo é
  do PR-06, junto com o caminho que o consome.
- **similaridade, vizinhos, índice.** Não existem neste PR.
- **paralelização.** A construção é sequencial por decisão: paralelizar antes de
  medir o sequencial esconde onde o custo está.
