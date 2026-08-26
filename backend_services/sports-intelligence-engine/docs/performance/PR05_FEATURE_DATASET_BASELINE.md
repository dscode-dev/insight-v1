# Baseline do dataset histórico de features

Medido no **PR-05.5.1**, em **2026-08-25**. Este documento existe para que a
próxima execução tenha contra o que comparar, e **não** para declarar SLO.

Ele cobre o último trecho do caminho de feature:

```
corpus publicado → HistoricalMatchState        PR-05.2  (baseline própria)
estado → MATCH_STATE_RAW_V2                    PR-05.4  (baseline própria)
V2 × grade × divisão → Parquet versionado      PR-05.5.1  (este documento)
```

---

## 1. O que estes números afirmam, e o que não afirmam

**Afirmam** que noventa e um cortes por partida são materializados em Parquet
com um custo de leitura que **não depende do número de cortes**, e com memória
de construção que segue o orçamento em vez do dataset — e dizem quanto isso
custa nesta máquina.

**Afirmam também**, e com igual clareza, que a **validação não tem a mesma
complexidade da construção**: ela é `O(linhas)` em memória. O coeficiente está
medido, e a extrapolação está marcada como extrapolação.

**Não afirmam** nada sobre outra máquina. O que sobrevive à troca de hardware
são as **propriedades**:

```
a leitura de FATO é POR LOTE DE PARTIDA    91 cortes e 5 cortes custam a MESMA
                                           consulta
a memória de CONSTRUÇÃO segue o orçamento  ×10 linhas, ×1,2 de pico
o limite do escritor é EXATO               sem tolerância; o único piso é uma
                                           partida indivisível
a memória de VALIDAÇÃO segue as LINHAS     e o coeficiente está medido
a impressão é REPRODUTÍVEL                 sob lote, orçamento e fronteira de
                                           descarga diferentes
```

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

**`tracemalloc` e não RSS**, deliberadamente: a pergunta deste PR é «o lote
mantém a memória limitada?», e o que cresceria num vazamento de lote são
objetos Python. RSS incluiria o pool do asyncpg, os buffers do PyArrow e o
alocador do sistema, e o número diria menos sobre o nosso código.

### Exclusividade do banco

A execução final rodou **sozinha** contra o PostgreSQL. **Três** execuções
anteriores foram descartadas — duas por mudança de código durante a medição, e
uma por interferência de arnês. Ver §11.

---

## 3. Configuração medida

```
espaço              MATCH_STATE_RAW_V2 @ 2.0 · 105 definições
grade cheia         LIVE_COMPARABLE_MINUTE_GRID_V1 · 91 cortes por partida
grade reduzida      BENCHMARK_FIVE_CUT_GRID_V1 · 5 cortes por partida
divisão             TEMPORAL_MATCH_ATOMIC_SPLIT_V1 · fronteira na mediana dos apitos
lote de partidas    500
pedaço do escritor  5.000 linhas   (`part_rows`)
teto global         10.000 linhas  (`max_pending_rows`)
compressão          ZSTD
colunas do arquivo  233 (23 de identidade + 105 valores + 105 disponibilidades)
```

---

## 4. Grade inteira — 1.000 partidas em 91 cortes

O corpus da versão tem **10.000 partidas**; a medição recorta as **1.000
primeiras** na ordem da chave. Dez mil partidas na grade cheia seriam 910 mil
linhas — o dataset de produção, e não algo que caiba numa suíte.

### Forma

| | |
| --- | --- |
| partidas na versão | 10.000 |
| partidas materializadas | **1.000** |
| partidas ignoradas | 0 |
| cortes por partida | **91** (1 pré-jogo + 45 + 45) |
| linhas | **91.000** |
| definições por linha | 105 |
| valores de feature | **9.555.000** |

### Tempo, por FASE

| fase | duração |
| --- | --- |
| build | **1.082,37 s** |
| validate | **5,54 s** |
| publish | **0,01 s** |
| **total** | **1.087,92 s** |

```
build        84 snapshots/s   ·   8.828 valores de feature/s
validate     16.426 linhas/s  ·   9,6 objetos/s
publish      metadado puro — não escala com linhas
```

**A publicação é 0,01 s para 91 mil linhas**, e é o número que confirma o
desenho: publicar grava o `manifest.json` e move o estado. Um `publish` que
crescesse com a contagem de linhas significaria que ele estava relendo o
dataset.

### Memória, por FASE

| | pico (`tracemalloc`) |
| --- | --- |
| build | **370 MB** |
| validate | **34 MB** |

Nunca um número combinado: as duas fases têm complexidades diferentes, e
somá-las esconderia justamente isso.

### O orçamento do escritor

```
teto configurado (max_pending_rows)     10.000 linhas
piso atômico (largest_atomic_match)         91 linhas
pico em espera observado                 9.919 linhas
limite exato = max(teto, piso)          10.000 linhas
partições abertas no pico                   10
```

`9.919 <= 10.000`. **Sem tolerância declarada**: o escritor abre espaço ANTES de
admitir a partida, então não existe transbordo transitório. O único caso acima
do teto seria uma grade maior que ele — e aí o pico é do tamanho da grade, que é
o piso atômico, não um transbordo.

### Memória de construção em DUAS escalas — o gate

| partidas | linhas | pico build |
| --- | --- | --- |
| 100 | 9.100 | 304 MB |
| 1.000 | 91.000 | **370 MB** |

```
linhas   x10
memória  x1,22
```

**É a afirmação mais forte deste documento.** Dez vezes mais linhas custaram 22%
mais memória. Um acumulador do tamanho do dataset teria dado x10; um buffer por
partição aberta teria dado x(partições). O que se vê é o orçamento.

### Consultas

| categoria | contagem |
| --- | --- |
| de FATO | **16** |
| de METADADO / ciclo de vida | 10 |
| não classificadas | 0 |
| **total** | **26** |

```
fato / linha        0,00018
fato / partida      0,016
fato / lote         8,0
```

Por alvo:

```
historical_canonical_members          8    (2 estado + 4 contexto + 2 varredura)
lineups                               2
historical_canonical_event_members    2
canonical_odds_observations           2
match_results                         2
----------------------------------- FATO 16

historical_feature_dataset_versions   5
historical_feature_dataset_build_runs 2
historical_feature_objects            1
historical_feature_dataset_manifests  1
dataset_audit_log                     1
---------------------------------- META 10
```

**Dezesseis leituras de fato para 91.000 snapshots.** O custo é do LOTE de
partidas, e não dos cortes:

| partidas | lotes | consultas de fato |
| --- | --- | --- |
| 100 | 1 | 9 = 1x(7+1) + 1 cobertura |
| 1.000 | 2 | 16 = 2x(7+1) |

A cobertura de contexto é paga **uma vez por fonte**, e não por execução:
`PostgresHistoricalContextSource` a memoiza por versão do corpus, e as duas
construções compartilharam a instância. A regra é mais forte que o enunciado.

### Objetos

| | |
| --- | --- |
| objetos | 53 |
| linhas min/mediana/máx | 91 / 1.820 / 2.548 |
| bytes min/mediana/máx | 86.327 / 214.159 / 268.992 |
| bytes totais | **10,5 MB** |
| bytes por linha | **120** |
| pedaço configurado | 5.000 linhas |

**Nada de «uma partida, um objeto»**: a mediana é de 1.820 linhas — vinte
partidas por arquivo. O mínimo de 91 é o resto de uma partição pequena.

**Compressão.** A razão declarada é **22,6x** contra uma estimativa LÓGICA de
`linhas x (105x8 + 105x16 + 200)` bytes — valor, rótulo de disponibilidade e
identidade. É uma **convenção declarada**, e não uma medida: o Arrow não expõe
um «descomprimido» de largura fixa. O número que não depende de convenção é
**120 bytes por linha de 105 features**, e ele é baixo porque as 105 colunas de
disponibilidade são altamente repetitivas e o ZSTD as dicionariza.

### Metades

```
referência   487 partidas · 44.317 linhas
avaliação    513 partidas · 46.683 linhas
```

A fronteira foi a mediana dos apitos. As duas metades somam exatamente 1.000
partidas e 91.000 linhas.

---

## 5. Volume de partidas — 10.000 partidas em 5 cortes

### Forma

| | |
| --- | --- |
| partidas | **10.000** |
| cortes por partida | 5 (`BENCHMARK_FIVE_CUT_GRID_V1`) |
| linhas | **50.000** |
| valores de feature | **5.250.000** |

### Tempo e memória

```
build        617,66 s   ·   81 linhas/s   ·   16 partidas/s   ·   8.500 valores/s
validate       1,05 s   ·   47.491 linhas/s   ·   30,4 objetos/s

pico build       363 MB
pico validate   18,3 MB   (384 B/linha)
```

**Dez mil partidas custaram 363 MB — praticamente o mesmo que mil.** O pico
segue o orçamento, e não a cardinalidade de partidas.

### O orçamento

```
teto configurado           10.000 linhas
piso atômico (5 cortes)         5 linhas
pico em espera             10.000 linhas   (exatamente no teto)
partições abertas no pico       10
```

### Consultas

| categoria | contagem |
| --- | --- |
| de FATO | **162** |
| de METADADO | 10 |
| **total** | **172** |

```
fato / partida    0,0162
fato / linha      0,00324
```

`162 = 20 lotes x (7 + 1) + 1 página vazia final + 1 cobertura`.

**O custo por partida é idêntico ao da grade cheia** — 0,016 nas duas —, e é a
prova pedida: a leitura de fato depende do LOTE DE PARTIDAS, e não de quantos
cortes cada partida contribui.

### Objetos

```
objetos    32
linhas     min 65 · mediana 1.755 · máx 2.275
bytes      6,4 MB no total · 135 por linha
```

---

## 6. Determinismo do conteúdo

Quatro construções das MESMAS mil partidas sob a mesma grade e a mesma divisão,
variando só o que é execução:

| lote | pedaço | teto | `raw_content_fingerprint` |
| --- | --- | --- | --- |
| 250 | 5.000 | 10.000 | `b41b7b86d645faf9…` |
| 500 | 5.000 | 10.000 | `b41b7b86d645faf9…` |
| 1.000 | 5.000 | 10.000 | `b41b7b86d645faf9…` |
| 500 | **200** | **400** | `b41b7b86d645faf9…` |

O relatório imprime os **dezesseis primeiros caracteres** do SHA-256, e não a
impressão inteira: o que se afirma é a IGUALDADE entre as quatro, e a
comparação de igualdade é feita no teste sobre o valor completo
(`len(set(impressoes.values())) == 1`). Um prefixo de dezesseis hex já torna a
coincidência acidental impossível na prática, e mantém o bloco legível.

**Uma impressão.** O tamanho do lote, o tamanho do pedaço e o teto do escritor
mudam quantos arquivos saem e quais bytes eles têm — e **não** mudam o conteúdo.
A identidade oficial do dataset é a impressão, e nunca a identidade de bytes do
Parquet.

---

## 7. Memória da validação — a curva medida

A construção mantém um orçamento; a **validação não**. Ela reúne os pares
`(chave, digesto)` de partições que se intercalam e os ordena globalmente:

```
Memória_validação   = O(linhas)   em tuplas compactas
Tempo_validação     = O(N log N)  na etapa de ordenação
```

Três pontos medidos:

| linhas | duração | linhas/s | pico | B/linha |
| --- | --- | --- | --- | --- |
| 9.100 | 4,82 s | 1.888 | 6,0 MB | 697 |
| 50.000 | 1,05 s | 47.491 | 18,3 MB | 384 |
| 91.000 | 5,54 s | 16.426 | 33,9 MB | 391 |

A duração da menor escala é dominada pela **reconstrução semântica** — cinco
partidas refeitas do corpus, que é custo fixo por execução e não por linha. É
por isso que 9.100 linhas levam quase o mesmo que 91.000.

### Modelo

```
M(N) ~ a·N + b        a = 357 B/linha        b ~ 2,9 MiB
```

Dois pontos e uma reta — **não** é regressão estatística, e não pretende ser.
Serve a planejamento de capacidade: «a que escala isto vira problema?».

O `b` é o custo fixo do processo mais o buffer de leitura de um objeto por vez;
é ele que explica os 697 B/linha da menor escala, onde o fixo domina.

### Extrapolação — **ESTIMATIVAS**, e não medições

| linhas | memória estimada de validação |
| --- | --- |
| 910.000 | ~313 MiB `ESTIMATE` |
| 1.000.000 | ~344 MiB `ESTIMATE` |
| 5.000.000 | ~1,67 GiB `ESTIMATE` |
| 10.000.000 | ~3,33 GiB `ESTIMATE` |

---

## 8. A escala V1, e a decisão

A única contagem de partidas justificada pelo repositório é a do próprio
benchmark — `PARTIDAS_MINIMAS = 10_000`, em
`tests/performance/test_historical_corpus_scale.py`. Não há outra no projeto, e
inventar uma seria pior que usar esta.

```
linhas_V1 = partidas x cortes_por_partida
          = 10.000   x 91
          = 910.000 linhas
```

| | valor |
| --- | --- |
| memória de construção | ~370 MB (**medida**, e independente da escala) |
| memória de validação | ~313 MiB `ESTIMATE` |
| tempo de construção | ~3,0 h `ESTIMATE` (extrapolado de 84 snapshots/s) |
| tempo de validação | ~1 min `ESTIMATE` |

> **A validação atual é aceitável na escala V1 pretendida: SIM.**

Trezentos e treze mebibytes num processo de construção offline é um envelope
confortável em qualquer contêiner razoável. A ordenação global da validação é
classificada como **dívida de escala MEDIDA**, e não como bloqueador.

O ponto em que ela passa a merecer trabalho é por volta de **5 milhões de
linhas** (~1,7 GiB) — cerca de 55 mil partidas na grade cheia. Aí um ordenamento
externo, em disco ou por fusão `k`-vias sobre iteradores por objeto, volta à
mesa **com um número que o justifique**.

---

## 9. Custo por linha em espera — construção

```
26.974 B / linha em buffer     (medido isoladamente, sobre 1.001 linhas)
```

Com o teto de 10.000 linhas, a parcela do pico atribuível aos buffers é
**~257 MiB** — coerente com o pico total medido de 370 MB, que inclui também o
lote de fatos em memória e a construção da tabela Arrow.

O `~39.096 B/linha` que o relatório do benchmark imprime é
`pico_total / pico_em_espera`: ele **atribui todo o pico às linhas em espera** e
portanto superestima. O número honesto para dimensionar o orçamento é o medido
em isolamento.

---

## 10. Limites medidos

```
construção          ~84 snapshots/s nesta máquina; 910 mil linhas ~ 3,0 h
                    ESTIMATE — o caminho é offline e em lote
validação           O(linhas) em memória; ~357 B/linha
                    confortável até ~1M linhas, atenção a partir de ~5M
objetos             53 arquivos para 91 mil linhas; mediana de 1.820 linhas
                    nenhum problema de arquivo miúdo nesta configuração
```

---

## 11. Três execuções descartadas, e por quê

Nenhum número deste documento vem delas.

**Descarte 1 e 2 — código alterado durante a execução.** O escritor mudou de
assinatura (a conferência do orçamento passou a acontecer ANTES da admissão) e
depois ganhou o campo `largest_atomic_match_rows`. O processo em curso tinha
importado a versão anterior, então media outro código.

**Descarte 3 — interferência de arnês.** A suíte de integração rodou durante o
benchmark. O `database` da integração dá `TRUNCATE datasets ... CASCADE` a cada
teste, e o benchmark — no meio da composição de dez mil partidas — recebeu:

```
ForeignKeyViolationError: dataset_validation_runs.dataset_id não existe
```

O motor estava certo. O arnês é que tinha estado mutável compartilhado: o lock
consultivo que protegia `perf ↔ perf` morava no `conftest` da performance e
**não** cobria `perf ↔ integração`.

**A correção está no repositório**, e não na disciplina de quem roda:
`tests/support/db_exclusivity.py` guarda o lock com **uma** chave, e as duas
suítes o tomam. Quem chegar depois espera, com uma mensagem que diz que o
conflito é do arnês.

---

## 12. O que medir da próxima vez

```
a razão consultas de FATO / linha    ela precisa CAIR quando o volume sobe
o pico contra o `max_pending_rows`   dobrar o teto deve dobrar o pico, e nada
                                     mais
bytes/linha no Parquet               ele mede a compressão das 210 colunas de
                                     feature, majoritariamente repetitivas
o coeficiente da validação           é o número que decide quando o
                                     ordenamento global precisa sair da memória
```

---

## Referências

- ADR-0036 — a grade e a divisão
- ADR-0037 — onde as linhas moram
- `docs/features/HISTORICAL_FEATURE_DATASET_V1.md`
- `tests/performance/test_feature_dataset_scale.py`
- `tests/support/db_exclusivity.py`
