# Baseline da canonicalização de eventos históricos

Medido no **PR-04.4.1**, em **2026-08-18**. Este documento existe para que a
próxima execução tenha contra o que comparar, e **não** para declarar SLO.

---

## O que estes números afirmam e o que não afirmam

**Afirmam** que cem mil registros de evento viram cem mil eventos canônicos
gravados no PostgreSQL, com consultas que crescem por lote e memória que
cresce só pelo índice de revisão — e dizem quanto isso custa nesta máquina.

**Não afirmam** nada sobre outra máquina. O que sobrevive à troca de hardware
são as **propriedades**:

```
as consultas crescem por LOTE          6 por lote, e não por registro
o custo marginal por registro é do     263 B — a referência, não o evento
    índice de revisão
o tamanho do lote NÃO muda o resultado 250 e 5.000 produzem os mesmos eventos
a execução fecha as contagens          built+reused+skipped+review+failed = read
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
do baseline do PR-04.3: um baseline contra um banco ajustado à mão mede o
ajuste.

---

## O cenário

```
partidas             200, canônicas e elegíveis
times                20, resolvidos
jogadores            22 por time, resolvidos
registros de evento  100.000  (500 por partida — volume de jogo real)
tipos                mapeados pelo catálogo canônico
licença              PUBLIC_DOMAIN, escopo RESEARCH
```

Os registros passam pela cadeia completa: leitura, tradução de referências em
lote, elegibilidade, construção e escrita real no PostgreSQL — sem duplo, sem
mock de banco.

---

## 100.000 registros · lote 1.000

| métrica | valor |
|---------|-------|
| duração | **39,4 s** |
| throughput | **2.536 eventos/s** |
| pico de memória | **30 MB** |
| registros lidos | 100.000 |
| eventos construídos | 100.000 |
| reusados / pulados / em revisão / falhos | 0 / 0 / 0 / 0 |
| lotes | 100 |
| **consultas** | **602** — 6,0 por lote · 0,0060 por registro |
| execução | `COMPLETED` |

Distribuição das consultas:

```
provider_entity_mappings         300    3 por lote: partida, time, jogador
canonical_match_events           200    2 por lote: existentes + escrita em massa
canonical_event_build_records    100    1 por lote
canonical_event_build_runs         2    abertura e fechamento da execução
```

**Três consultas de tradução por lote, e não por registro.** É o que separa
este desenho de um N+1: com resolução por linha seriam 300.000 consultas.

---

## As consultas escalam por lote

| registros | consultas | por registro |
|-----------|-----------|--------------|
| 10.000 | 62 | 0,0062 |
| 100.000 | 602 | 0,0060 |

Dez vezes mais registros, dez vezes mais consultas — porque são dez vezes mais
**lotes**. A razão por registro **cai**, o que é a assinatura de custo por
lote; se as consultas crescessem com os registros, ela ficaria constante.

---

## Memória — o que cresce, e por quê

| registros | pico |
|-----------|------|
| 10.000 | 7,3 MB |
| 100.000 | 29,9 MB |
| **custo marginal** | **263 B por registro** (teto do teste: 400 B) |

**O pico não é constante no volume, e afirmar que seria estaria errado.** A
execução mantém um índice `chave de origem → (id, revisão)` que atravessa
lotes de propósito: uma correção pode referenciar qualquer evento anterior da
mesma execução, e resolvê-la indo ao banco por linha seria N+1. Esse índice é
O(chaves distintas), por construção.

O que o teste vigia é o **custo marginal por registro**, porque é ele que
distingue as duas situações que importam:

```
~200 a 300 B/registro   só a referência está retida          (correto)
>1 KB/registro          o CanonicalMatchEvent inteiro voltou (regressão)
```

Duas correções feitas neste PR reduziram o pico de **114 MB para 30 MB** no
cenário de cem mil:

1. o índice de revisão passou a guardar `(id, revisão)` em vez do evento
   canônico inteiro — com procedência, relógio, coordenadas e detalhe tipado;
2. a saída do caso de uso passou a devolver uma **amostra** de linhagem
   (5.000 linhas, com `records_truncated` explícito) em vez de acumular a
   linhagem inteira da execução. A linhagem completa está no repositório, que
   é onde ela é completa.

---

## Os três tamanhos de lote · 20.000 registros

| lote | duração | pico | consultas | eventos |
|------|---------|------|-----------|---------|
| 250 | 8,4 s | 8,1 MB | 482 | 20.000 |
| **1.000** | **8,1 s** | **9,6 MB** | **122** | 20.000 |
| 5.000 | 7,1 s | 21,1 MB | 50 | 20.000 |

**`DEFAULT_EVENT_BATCH = 1.000` sai desta tabela.** O lote de 5.000 é ~12%
mais rápido e custa **2,2× mais memória**; o de 250 quadruplica as consultas
sem ganhar nada. Mil é o ponto em que nenhum dos dois domina.

O tempo varia pouco entre os três porque o gargalo é a escrita no PostgreSQL,
não a canonicalização em memória.

---

## O lote não muda o resultado

Cinco mil registros processados com lote 250 e com lote 5.000 produzem **o
mesmo conjunto de eventos canônicos** — mesmos ids, mesmas sequências, mesmas
cadeias de revisão.

É a propriedade que justifica o índice de revisão atravessar lotes. Sem ele,
uma correção separada do seu predecessor por uma fronteira de lote viraria
`DANGLING_REVISION` por um motivo do arnês, não do dado — e o tamanho do lote
deixaria de ser detalhe de execução.

---

## Como reproduzir

```bash
SIE_TEST_POSTGRES_DSN=postgresql://engine:engine_local@127.0.0.1:5433/sports_intelligence \
SIE_TEST_OBJECT_STORE_ENDPOINT=http://127.0.0.1:9000 \
SIE_TEST_OBJECT_STORE_BUCKET=sports-intelligence-raw \
pytest tests/performance/test_event_canonicalization_scale.py -q -s
```

Cada teste imprime o quadro que originou as tabelas acima.

---

## Relacionados

- [Canonicalização de eventos históricos](../data/HISTORICAL_EVENT_CANONICALIZATION.md)
- [Baseline do corpus histórico canônico (PR-04.3)](PR04_CANONICAL_CORPUS_BASELINE.md)
