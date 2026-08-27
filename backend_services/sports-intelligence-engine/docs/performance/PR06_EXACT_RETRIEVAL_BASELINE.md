# Baseline da recuperação exata

Medido no **PR-06.1**, em **2026-08-26**. Este documento existe para que a
próxima execução tenha contra o que comparar, e **não** para declarar SLO.

Ele cobre o primeiro trecho do caminho de recuperação:

```
corpus publicado → HistoricalMatchState        PR-05.2    (baseline própria)
estado → MATCH_STATE_RAW_V2                    PR-05.4    (baseline própria)
V2 × grade × divisão → Parquet versionado      PR-05.5.1  (baseline própria)
Parquet cru → ajuste → Parquet normalizado     PR-05.5.2  (baseline própria)
query de AVALIAÇÃO → top-K exato               PR-06.1    (este documento)
```

---

## 1. O que estes números NÃO são

**Não são SLO.** Um oráculo de força bruta não tem promessa de latência a
cumprir. A promessa de latência é do caminho **indexado**, e ele é do PR-06.4.
Exigir `p95 < 50 ms` de uma varredura exaustiva seria exigir que ela deixasse de
ser exaustiva.

**Não são o custo do insumo.** A construção do corpus, do dataset cru e do
normalizado está medida nos baselines anteriores; misturá-la aqui faria o custo
da recuperação parecer trezentas vezes maior do que é.

**Não são um resultado em escala de produção.** O cenário são doze partidas —
ver §2. O que ele mede com fidelidade é a FORMA do custo; o que ele não mede é
como ela se comporta com dez mil partidas por liga.

## O que eles afirmam

```
o resultado é REPRODUTÍVEL      sob ordem, lote, layout e K
a memória segue o LOTE          e não o universo
zero leitura de fato canônico   medido por instrumentação, e não por leitura
                                de código
a atrição é medida              e é o insumo declarado do PR-06.2
o custo é de I/O                e não de distância — ver §5
```

---

## 2. O cenário, e por que ele é o que é

```
partidas               12   (5 na referência · 7 na avaliação)
chutes por time        10   por partida
competições             1   Premier League
temporadas              1   2024/25
linhas do dataset   1.092   (455 referência + 637 avaliação)
```

**DOZE PARTIDAS, E NÃO UMA.** O cenário do E2E do PR-05 tem **uma** partida, e a
divisão é atômica por partida: ele nunca produz as duas metades. A recuperação
precisa das duas — a query vem de uma, os candidatos da outra —, então o PR-06.1
traz o próprio cenário, pelo **mesmo caminho** (fonte pública, resolução, fusão,
qualidade, build, canonicalização de eventos, publicação).

**DEZ CHUTES POR TIME, E ISSO NÃO É FUTEBOL.** A densidade saiu de medição, e a
conta é curta:

```
`xg_home_5m` soma o xG dos últimos cinco minutos. Cada chute torna a janela
não nula por cerca de cinco cortes.

 4 chutes  →  ~22 % dos cortes não nulos  →  Q1 = Q3 = 0  →  DEGENERATE_SCALE
10 chutes  →  mais de metade não nulos    →  IQR > 0      →  FITTED
```

Com três gols por partida e nenhum chute, **todos os 29 eixos robustos saíam
`DEGENERATE_SCALE` ou `INSUFFICIENT_SAMPLE`**, o perfil resolvido ficava vazio, e
nenhuma query era comparável — o E2E passaria pulando tudo que importa.

Um corpus real não precisa disso: a dispersão vem de milhares de partidas numa
temporada, e não da densidade de uma delas. A densidade é como se compensa a
concentração de um cenário de doze partidas sem inventar mil dentro de um E2E.

**E `RollingFamily.XG` lê `EventType.SHOT`, e não `GOAL`.** As três famílias de
finalização — `SHOT`, `SHOT_ON_TARGET` e `XG` — leem o mesmo tipo; o que muda é
o que se extrai dele. Um cenário só com gols dá `xg_* = 0.0` em todo corte.

---

## 3. Ambiente

```
CPU               Intel Core i9-14900KF · 32 threads
RAM               31 GB
SO                Windows 11 Pro (10.0.26200)
Python            3.14.6 (venv local)
PostgreSQL        17, em contêiner (`sie-postgres`, porta 5433)
object store      sistema de arquivos local (o E2E aceita MinIO quando o
                  ambiente o oferece)
memória medida    `tracemalloc` — alocação PYTHON, e não RSS do processo
```

---

## 4. Configuração medida

```
política          SAME_COMPETITION_REFERENCE_EXACT_TIMEPOINT_V1
perfil            ROBUST_COMPLETE_CASE_EXACT_BASELINE_V1
distância         EXACT_SQUARED_L2_COMPLETE_CASE_V1
semântica float   IEEE754_FLOAT64_FSUM_V1
K                 10
lote de leitura   2.000 linhas
```

### O ajuste que o cenário produziu

```
artefatos robustos        29
  FITTED                   8   ← o perfil resolvido
  DEGENERATE_SCALE         5
  INSUFFICIENT_SAMPLE     16
```

Os oito eixos são de xG em janelas de 3, 5 e 10 minutos — casa, fora e
diferença. Os dezesseis `INSUFFICIENT_SAMPLE` são de contexto e de mercado: o
cenário não publica cotações, e o contexto de calendário tem poucas observações
disponíveis numa competição de doze partidas.

---

## 5. Uma query

```
competição              PREMIER_LEAGUE
instante                PRE_MATCH
universo                     5 candidatos
comparáveis                  5
K                          5/10
duração                   60,8 ms
memória                    2,3 MB
objetos lidos                2
bytes lidos            315.279
```

**O custo é de I/O, e não de distância.** Cinco candidatos em oito eixos são
quarenta subtrações e quarenta multiplicações — nanossegundos. Os 60,8 ms são
os dois objetos Parquet baixados e decodificados:

```
load_query          varre a metade de AVALIAÇÃO procurando a chave
stream_candidates   lê a partição de REFERÊNCIA daquela competição
```

**E os dois são relidos a cada query.** Não há cache — o §80 o proíbe
deliberadamente: primeiro o oráculo puro, depois a otimização com o número na
mão.

---

## 6. Cem queries

```
queries                    100
  comparáveis              100
  rejeitadas                 0
taxa de comparabilidade  100,0 %

p50                       57,6 ms
p95                       60,7 ms
p99                       65,4 ms
max                       65,4 ms
total                      5,79 s

memória do lote            2,4 MB
avaliações de distância      500
objetos lidos                200
bytes lidos           31.527.900
```

**A distribuição é apertada** — p50 e p99 diferem em 8 ms — porque o custo é
constante: toda query lê os mesmos dois objetos. Não há cauda porque não há
variação de trabalho.

**31,5 MB lidos para um dataset de 1.092 linhas.** Cem queries × 315 KB. A
amplificação de I/O é de duas ordens de grandeza, e ela é **inteiramente** do
padrão «reabrir o Parquet por query».

**A memória não cresce com o lote de queries**: 2,3 MB para uma, 2,4 MB para
cem. O oráculo mede e descarta; o que fica é `K`.

---

## 7. A atrição

```
universo somado          500
comparáveis somados      500
razão de comparáveis   100,0 %

queries comparáveis    100/100  (100,0 %)
```

**Cem por cento nas duas, e o número é do cenário — não do motor.** Os oito
eixos do perfil são todos de xG em janela móvel, e a janela é computável em todo
corte de toda partida: ela vale zero quando não houve chute, e zero é um valor
medido. Não há ausência para produzir.

**Isso NÃO se generaliza.** O PR-05.5.2 mediu, sobre 9,55 milhões de células de
um cenário de mil partidas, que **40,7 % das células dos eixos robustos saem sem
escala**. Naquele cenário o perfil resolvido incluiria eixos de mercado e de
contexto, e a razão de comparáveis seria muito menor.

**O que este baseline mede com fidelidade é o CAMINHO**: que a atrição é
contada, separada por motivo, e que `INCOMPLETE_PROFILE` não se mistura com os
motivos estruturais. O valor dela num corpus de produção é medição do PR-06.2.

---

## 8. A identidade

```
universo      72d61f8b215d5cea…
perfil        650f327c7fafe3da…
distância     129b9ad39b0994a4…
resultado     4f4eec9d23ac1269…
```

Duas execuções da mesma query produzem a mesma impressão de resultado — medido
no benchmark e no E2E.

E o resultado do PRE_MATCH mostra o desempate funcionando sobre dados reais:
cinco candidatos, **todos a `d² = 0.0`** — no pré-jogo toda janela de xG é zero —,
devolvidos em ordem crescente de chave canônica. Sem o desempate, esses cinco
trocariam de posição entre execuções conforme a ordem de leitura do bucket.

---

## 9. O que este baseline NÃO mede

- **escala de produção.** Doze partidas, uma competição, uma temporada.
- **outra máquina.** Ver §3.
- **o caminho indexado.** É do PR-06.4, e é ele que terá SLO.
- **o custo com cache.** Não há cache, por decisão (§80).
- **`Recall@K`.** Não há índice aproximado contra o que medir. Este resultado é
  a régua futura.

---

## 10. As dívidas de escala medidas

Duas, e as duas têm número:

**A releitura por query.** 315 KB e dois objetos por query, sem cache. Numa liga
com mil partidas de referência, a partição de referência seria maior e a
releitura pesaria proporcionalmente. As saídas possíveis — cache de partição,
reparticionamento por instante, índice — são todas do PR-06.4, e agora existe um
número contra o qual avaliá-las.

**A busca da query por varredura.** `load_query` varre a metade de avaliação
procurando `(match_key, grid_index)`, porque o caminho do objeto não carrega a
partida e não há prefixo que a alcance. O custo é de **uma** query; a alternativa
— um índice de chave para objeto — é persistência nova, e o §79 não a autoriza
sem necessidade demonstrada. Este número é o começo dessa demonstração.
