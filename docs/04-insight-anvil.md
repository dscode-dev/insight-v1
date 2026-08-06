# Parte 4 — Insight Anvil

> **Papel em uma frase:** consome os eventos derivados que o Atlas emite
> e os persiste no ClickHouse como histórico analítico consultável.
>
> **Linguagem:** Python · **Persistência:** ClickHouse · **Porta:** 8081
> **Tamanho:** ~2.700 linhas — o menor serviço da camada de inteligência

---

## 1. Por que este serviço existe

O caminho quente do Atlas é para inteligência **em tempo real**. Ele
recalcula estado de partida e emite eventos derivados a cada mudança.
Esses eventos são um insumo perfeito para uma camada **histórica**:

- **Backtesting** — "como estavam as odds de consenso no state_version V
  da partida M?" vira uma busca por índice.
- **Recuperação de features para ML** — `metric_ticks` é uma tabela
  larga onde cada feature é uma coluna própria. Sem desempacotar JSON.
- **Forense operacional** — replay, auditoria de retenção, linhagem.

O Atlas produz. O Anvil guarda. E depois o Atlas **consulta de volta**
para contextualizar o presente — o ciclo descrito na
[Parte 1](01-conceitos-e-fluxos.md).

---

## 2. Onde ele roda (e por que mudou)

O documento de arquitetura original coloca o Anvil no **Product Plane**,
no Google Cloud. Ele foi **movido para o Robozão**, ao lado do Atlas.

O motivo é concreto: o Anvil consome `insight:stream:derived:p0..p7` do
Redis que o **Atlas alimenta**. Colocado ao lado, cada evento derivado
deixa de atravessar a rede.

Isso teve uma consequência que ninguém previu — ver a seção 6.

---

## 3. Um processo, dois papéis

Isso confunde, então vale explicitar: **o Anvil é um único processo que
serve duas funções**, ambas na porta 8081.

```
┌──────────────────────────────────────────────────────┐
│  anvil.worker.anvil_worker                           │
│                                                      │
│  ┌────────────────────┐    ┌──────────────────────┐  │
│  │ MultiStreamConsumer│ ─► │ DerivedEventHandler  │  │
│  │ (Redis, 8 shards)  │    │  · roteia por tipo   │  │
│  └────────────────────┘    │  · mapeia p/ linha   │  │
│                            └──────────┬───────────┘  │
│                                       ▼              │
│                              ┌────────────────┐      │
│                              │ BatchInserter  │ ──► ClickHouse
│                              └────────────────┘      │
│                                                      │
│  HealthServer (porta 8081):                          │
│    /live  /ready  /metrics                           │
│    /internal/features/matches/{id}   ◄── o Atlas lê  │
└──────────────────────────────────────────────────────┘
```

O `HealthServer` não serve só health: ele também expõe a **API de
leitura de features** que o Atlas consome, protegida por
`ANVIL_FEATURE_API_KEY`.

---

## 4. O caminho Atlas → Anvil, e as duas armadilhas

Na topologia original o Atlas fala com o Anvil **através do gateway da
nuvem**, e o gateway faz duas traduções que ninguém tinha percebido:

| | O Atlas envia | O Anvil espera |
|---|---|---|
| **Path** | `/internal/anvil/features/matches/{id}` | `/internal/features/matches/{id}` |
| **Header** | `X-Atlas-Anvil-Key` | `x-anvil-api-key` |

Com o Anvil local, não há gateway para traduzir. E as duas falhas
**parecem coisas diferentes**:

- Path errado → **404**
- Header errado → **401**, que se lê exatamente como *chave errada*

O segundo custou tempo de verdade: a chave estava correta e a resposta
era 401.

Hoje os dois são configuráveis no Atlas:

```python
# atlas/config/settings.py
anvil_features_path_prefix: str = Field(
    default="/internal/anvil/features", alias="ATLAS_ANVIL_FEATURES_PATH_PREFIX"
)
anvil_api_key_header: str = Field(
    default="X-Atlas-Anvil-Key", alias="ATLAS_ANVIL_API_KEY_HEADER"
)
```

Os defaults continuam apontando para o gateway, para não quebrar quem já
usa aquele caminho. Para Anvil local, configure **os dois**:

```
ATLAS_ANVIL_FEATURES_PATH_PREFIX=/internal/features
ATLAS_ANVIL_API_KEY_HEADER=x-anvil-api-key
```

> **São um par.** Configurar um e esquecer o outro falha, e a falha
> aponta para o lugar errado.

---

## 5. O ClickHouse

Três tabelas, todas `ReplacingMergeTree`:

| Tabela | O que guarda | ORDER BY |
|---|---|---|
| `market_snapshots` | Odds de consenso, dispersão, melhores preços | `(match_id, market_type, state_version)` |
| `metric_ticks` | Features largas — cada uma uma coluna | `(match_id, market_type, state_version)` |
| `human_signals` | Sinais humanos | `(match_id, signal_type, ts_event, event_id)` |

O Anvil aplica o próprio DDL no boot (`AUTO_APPLY_MIGRATIONS=true`,
todo `CREATE ... IF NOT EXISTS`). **Não existe serviço de migrate
separado.**

### O que ReplacingMergeTree garante — e o que não garante

Ele deduplica linhas com a mesma chave de ORDER BY, **no merge de
fundo**. Isso significa:

- Reprocessar um evento é seguro a longo prazo.
- Mas **entre a inserção duplicada e o merge, a duplicata é visível.**

E as queries de feature usam `avg()`, `count()`, `stddevPop()` — **sem
`FINAL`**. Duplicata nessa janela distorce todas elas, silenciosamente.
Isso deixa de ser teoria na seção 7.

---

## 6. A API de features nunca tinha funcionado

Exercitar o caminho ponta a ponta pela primeira vez revelou **três bugs
encadeados**, cada um escondido pelo anterior.

### Bug 1 — coluna que não existe

```sql
SELECT stddevPop(home_consensus_odd) AS volatility, ...
  FROM market_snapshots
 WHERE ... AND ts_ingest <= {as_of}
```

`market_snapshots` **não tem** `ts_ingest`. A DDL chama
`watermark_ingest_ts`. Parecia certo porque `metric_ticks` e
`human_signals` **genuinamente têm** `ts_ingest` — a inconsistência
estava na DDL, não na query.

### Bug 2 — alias que sombreia a própria coluna

```sql
SELECT anyLast(minute) AS minute FROM metric_ticks
```

O analyzer do ClickHouse 24.8 resolve o alias **antes** da coluna, então
a expressão referencia a si mesma e morre com `UNKNOWN_IDENTIFIER` —
sugerindo, sem ajudar, *"Maybe you meant: ['minute']"*.

ClickHouse mais antigo aceitava essa forma. **Ela quebra no upgrade.**

### Bug 3 — a coluna não existe em lugar nenhum

Corrigido o alias, apareceu o real: `minute` **não está na DDL nem no
mapper**. Nada nunca escreveu esse campo.

Isso não é typo — é lacuna de modelo de dados. A query foi removida e o
campo reporta `None`. Restaurar a feature exige coluna na DDL e mapper
que a preencha; **está pendente de decisão do produto.**

### Por que nada disso foi pego

```python
# tests/test_feature_service.py — o stub antigo
if "ORDER BY ts_ingest DESC" in sql: return Result([...])
return Result([{"minute": 73}])   # ← devolvia o que a query pedisse
```

O teste stubava o cliente ClickHouse e **respondia o que a query
pedisse**, inclusive uma coluna que a tabela real nunca teve. Stub não
enxerga drift de schema.

A cobertura nova (`tests/test_feature_query_columns.py`) **parseia a
DDL e a SQL** e compara — sem precisar de ClickHouse vivo. Verificada
falhando quando cada bug é reintroduzido.

> **Consequência prática:** como uma query ruim derrubava o snapshot
> inteiro, as **cinco** features retornavam 500. Hoje quatro funcionam.
> `signal_count` é sempre 0 (nada escreve `human_signals` — a tabela é
> declarada "reserved") e `minute` é sempre `None`.

---

## 7. Dois bugs de correção no pipeline de escrita

Estes são mais sérios que os de schema, porque afetavam **dados**, não
disponibilidade.

### Mensagens confirmadas antes de existirem

O consumer dava ACK assim que o handler retornava. Mas o handler do
Anvil só **bufferiza** — a linha vira durável num flush posterior.

```python
# consumer_multi.py — o comentário ANTIGO, que era falso aqui
# ACK only here (handler guaranteed CAS + publish before returning).
```

Esse comentário é verdadeiro no consumer do Atlas, de onde este foi
copiado. Aqui não era. Uma queda ou **um redeploy comum** entre o ACK e
o flush perdia até `max_rows` (500) linhas **permanentemente**, com o
stream reportando-as consumidas.

A correção passa o ACK adiante:

```python
await self.inserter.add(TABLE, COLUMNS, row, on_flushed=ack)
```

Ele só dispara depois do insert que carregou aquela linha. Mensagem não
confirmada fica pending e o Redis reentrega via XAUTOCLAIM —
**at-least-once**, que o ReplacingMergeTree reconcilia. Falhar em
confirmar é a direção segura.

Eventos que não bufferizam nada (tipos não suportados) confirmam
**imediatamente**, ou ficariam sendo reentregues para sempre.

### Flush parcial reinserindo o que já entrou

O `_flush_locked` insere tabela por tabela. Se a tabela B falhava, o
`except` restaurava **todas** — incluindo as linhas de A que o
ClickHouse já tinha.

Como visto na seção 5, ReplacingMergeTree só remove duplicata no merge, e
as queries de feature não usam `FINAL`. Até lá, elas leem **contagens
infladas e médias distorcidas**, sem nada indicando.

Hoje só as tabelas que **não** inseriram são restauradas — e linhas e
ACKs viajam juntos, para uma linha restaurada continuar não-confirmada.

---

## 8. Configuração

| Variável | Obrigatória | Observação |
|---|---|---|
| `REDIS_URL` | sim | O mesmo Redis do Atlas |
| `CLICKHOUSE_HOST` | sim | |
| `CLICKHOUSE_USER` / `PASSWORD` / `DATABASE` | — | default `default` / vazio / `insight` |
| `DERIVED_STREAM_BASE_KEY` | — | `insight:stream:derived` |
| `STREAM_PARTITIONS` | — | **8 — tem que bater com o Atlas** |
| `ANVIL_FEATURE_API_KEY` | — | Vazio desliga a API de features |
| `AUTO_APPLY_MIGRATIONS` | — | `true` |
| `BATCH_MAX_ROWS` / `MAX_AGE_MS` | — | 500 / 1000 |

> **`STREAM_PARTITIONS` precisa ser idêntico nos dois lados.** Se o
> Atlas publica em 8 shards e o Anvil consome 4, metade dos eventos
> nunca é lida — e ninguém avisa.

---

## 9. Relacionamentos

```
   ┌─────────┐  publica  ┌────────────────────────┐  consome  ┌────────┐
   │  ATLAS  │ ────────► │ insight:stream:derived │ ────────► │ ANVIL  │
   └────┬────┘           │        :p0..p7         │           └───┬────┘
        │                └────────────────────────┘               │
        │                                                         ▼
        │  GET /internal/features/matches/{id}              ┌────────────┐
        └────────────────────────────────────────────────── │ ClickHouse │
                          (x-anvil-api-key)                 └────────────┘
```

O Control Plane sonda `/live` para o painel. Nada mais fala com o Anvil.

---

## 10. Estado atual, sem maquiagem

| Item | Estado |
|---|---|
| Worker (Redis → ClickHouse) | Funcionando. Consumer group ativo, 0 pending |
| DDL | Aplicada — as 3 tabelas existem |
| `pressure_means`, `consensus_movement`, `pressure_series` | Funcionando |
| `signal_count` | **Sempre 0** — nada escreve `human_signals` |
| `match_minute` | **Sempre `None`** — coluna ausente do schema |

As duas últimas não são bugs pendentes: são **funcionalidade ausente**,
esperando decisão sobre o modelo de dados.

---

## Próximo passo

**[Parte 5 — Insight Nexus](05-insight-nexus.md)**: os agentes que
transformam esse conhecimento em publicação.
