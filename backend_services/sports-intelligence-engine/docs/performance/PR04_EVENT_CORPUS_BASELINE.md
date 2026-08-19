# Baseline do corpus com eventos

Medido no **PR-04.4.2**, em **2026-08-19**. Este documento existe para que a
próxima execução tenha contra o que comparar, e **não** para declarar SLO.

Ele cobre as duas metades do caminho de evento:

```
registro bruto → CanonicalMatchEvent      PR-04.4.1  (baseline própria)
CanonicalMatchEvent → corpus publicado    PR-04.4.2  (este documento)
```

---

## O que estes números afirmam e o que não afirmam

**Afirmam** que dez mil partidas com cem mil eventos são compostas,
materializadas em Parquet e publicadas com consultas por LOTE e memória que
não segue o corpus — e dizem quanto isso custa nesta máquina.

**Não afirmam** nada sobre outra máquina. O que sobrevive à troca de hardware
são as **propriedades**:

```
o custo do evento é ISOLADO        compor com e sem eventos, e subtrair
as consultas crescem por LOTE      0,0045 por evento, e caindo com o volume
a memória segue o LOTE             dez vezes mais eventos, +0,8 MB de pico
o teto de evento não muda o        1.000 e 50.000 produzem a MESMA impressão
    conteúdo publicado
a publicação é O(1) em consultas   8 consultas para conferir 100.000 eventos
```

---

## Ambiente

```
CPU               Intel Core i9-14900KF · 32 threads
RAM               31 GB
SO                Windows 11 (10.0.26200)
Python            3.14.6 (venv local)
PostgreSQL        17.11, em contêiner (`sie-postgres`, porta 5433)
object store      MinIO, mesmo host (porta 9000)
```

PostgreSQL em **configuração de fábrica**, deliberadamente — pelo mesmo motivo
dos baselines anteriores: um número medido contra um banco ajustado à mão mede
o ajuste.

---

## O cenário

```
registros da fonte     12.500  → 10.000 partidas canônicas (resolução real)
eventos                100.000 → 10 por partida
tipos                  60% passe · 20% chute · 10% cartão · 10% gol
cartão SEM coordenada  para que o denominador espacial signifique algo
lote de composição     500 partidas
teto de evento         20.000 por pedaço
```

O caminho inteiro é exercido: intake, resolução, fusão, qualidade, build de
partida, canonicalização de evento e publicação — sem duplo, sem mock de
banco.

---

## O custo do evento, ISOLADO

A mesma versão composta **duas vezes** sobre o mesmo build: uma sem declarar
execução de evento, outra declarando. A diferença é a resposta.

| | sem eventos | com 100.000 eventos | diferença |
|---|---|---|---|
| duração | 18,8 s | 84,8 s | **+66,0 s** |
| pico de memória | 10 MB | 25 MB | +15 MB |
| consultas | 243 | 692 | **+449** |

```
throughput de publicação de evento    1.516 eventos/s
consultas por evento                  0,0045
```

**Por que medir assim.** «A composição levou 85 s» não diz quanto custou
publicar evento: a mesma composição também escreve partida, escalação e odds.
Compor duas vezes transforma a diferença em número.

---

## Publicação

| métrica | valor |
|---------|-------|
| duração | **0,09 s** |
| consultas | **8** |
| estado final | `READY` |

**O gate não varre o corpus.** Ele confere por agregação: um `count(*)` da
pertinência de evento, a soma das linhas declaradas nos objetos do manifesto e
a contagem do próprio manifesto. Um número que crescesse com o corpus
significaria que a conferência virou varredura.

---

## O arquivo

| métrica | valor |
|---------|-------|
| linhas de evento | 100.000 |
| bytes | **4,0 MB** (42 B por evento) |
| compressão | **1,8×** (zstd, medida no rodapé do Parquet) |
| pedaços | 166 arquivos · ~600 linhas por pedaço (10 a 930) |

**O tamanho do pedaço é consequência, e não um número escolhido** (§92). Cada
chamada de materialização escreve UM pedaço com as linhas daquele recorte de
página para aquela partição:

```
pedaço = eventos das partidas de uma página, de UMA partição
       ← lote de composição (500 partidas)
       ← teto de evento (20.000 linhas)
       ← quantas partições a página tocou
```

No cenário sintético as partidas se espalham por muitas competições e
temporadas, então uma página de 500 partidas vira vários pedaços pequenos. Num
corpus real — uma liga, uma temporada por partição — a mesma página produziria
um pedaço grande. **É por isso que o número reportado é a distribuição, e não a
média sozinha.**

---

## Memória — ela segue o LOTE, não o corpus

| eventos publicados | pico |
|--------------------|------|
| 10.000 | 24,4 MB |
| 100.000 | **25,2 MB** |

Dez vezes mais eventos custaram **0,8 MB** a mais. É a afirmação mais forte
deste documento, e a mais fácil de perder: um `list(events_of(...))` sobre a
versão inteira, ou uma página que trouxesse os eventos de todas as partidas de
uma vez, passariam em todos os outros testes daqui.

**O que garante isso** é o fatiamento por volume de evento: a página de
composição é contada ANTES de ser lida — um agregado barato — e cortada em
pedaços com teto de eventos. Uma partida nunca é partida ao meio: a impressão
do conteúdo dela precisa de todos os eventos dela ao mesmo tempo.

---

## Consultas — elas escalam por lote

| eventos | consultas | por evento |
|---------|-----------|------------|
| 10.000 | 332 | 0,0332 |
| 100.000 | 692 | **0,0069** |

A razão por evento **cai** ao multiplicar o volume por dez — a assinatura de
custo por lote. Com N+1 ela ficaria constante e próxima de 1.

Onde as consultas de evento vão:

```
historical_canonical_event_member_builds   201   escritas em massa (500/lote)
historical_canonical_event_members         201   idem
canonical_match_events                      42   leitura por lote: contar, ler
```

As duas primeiras são **escritas**, e crescem com o número de blocos de
gravação — 100.000 eventos ÷ 500 por `executemany`. A terceira é a leitura, e
são duas por pedaço: a contagem que permite fatiar, e a leitura em si.

---

## Determinismo

Publicar os mesmos eventos com tetos de 1.000 e de 50.000 produz **a mesma
impressão de corpus**. O tamanho do pedaço é detalhe de execução, e por isso
ele pode ser escolhido por memória sem mudar o que é publicado.

O mesmo vale para o lote de composição (1 e 500 partidas por página) e para a
ordem em que os eventos voltam do banco: a ordem canônica é imposta na
serialização, e não herdada do `ORDER BY`.

---

## Como reproduzir

```bash
SIE_TEST_POSTGRES_DSN=postgresql://engine:engine_local@127.0.0.1:5433/sports_intelligence \
SIE_TEST_OBJECT_STORE_ENDPOINT=http://127.0.0.1:9000 \
SIE_TEST_OBJECT_STORE_BUCKET=sports-intelligence-raw \
pytest tests/performance/test_event_corpus_scale.py -q -s
```

Cada teste imprime o quadro que originou as tabelas acima. A execução completa
leva cerca de uma hora: cada teste refaz o caminho inteiro, do arquivo bruto à
publicação, porque um benchmark que atalha o caminho mede o atalho.

---

## Relacionados

- [Baseline da canonicalização de eventos (PR-04.4.1)](PR0441_EVENT_CANONICALIZATION_BASELINE.md)
  — 100.000 registros → eventos canônicos, 39,4 s
- [Baseline do corpus histórico canônico (PR-04.3)](PR04_CANONICAL_CORPUS_BASELINE.md)
  — 12.500 registros → 10.000 partidas publicadas
- [O corpus histórico canônico](../data/HISTORICAL_CANONICAL_CORPUS.md)
