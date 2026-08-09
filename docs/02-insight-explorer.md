# Parte 2 — Insight Explorer

> **Papel em uma frase:** descobre dados esportivos em fontes externas,
> normaliza para um formato canônico e entrega ao Atlas.
>
> **Linguagem:** Python · **Framework:** FastAPI · **Porta:** 8090
> **Persistência:** arquivos JSONL em disco (não usa Postgres)

---

## 1. Por que este serviço existe

O Atlas é bom em inteligência e ruim em lidar com o mundo real: cada
provedor tem um formato, uma taxa de erro, uma janela de indisponibilidade
e uma forma diferente de escrever o nome do mesmo time.

O Explorer absorve esse caos. Ele é a única parte da plataforma que
conhece ESPN, FBref e Football-Data. O que sai dele é um **envelope
canônico** — e o Atlas nunca precisa saber de onde veio.

**Não é responsável por:** inteligência, similaridade, publicação, rede
social. Se você se pegar escrevendo lógica de "o que esse dado
significa" aqui, ela pertence ao Atlas.

---

## 2. Estrutura do código

```
explorer/
├── adapters/      ← fala com cada provedor (ESPN, FBref, Football-Data, Wikipedia)
├── normalizers/   ← converte o formato de cada provedor no envelope canônico
├── validators/    ← decide se um registro é confiável
├── ai/            ← camada de qualidade assistida por IA (CrewAI + Qwen local)
├── jobs/          ← executa uma coleta: (fonte × competição × temporada)
├── pipelines/     ← agrupa jobs; agenda execuções recorrentes
├── realtime/      ← coleta contínua de sinais (framework, sem provedor real ainda)
├── datalake/      ← escrita em camadas no disco
├── tickets/       ← registro de problemas operacionais
├── ops/           ← controles administrativos (fila de curadoria, config em runtime)
└── api/           ← superfície HTTP consumida pelo Control Plane
```

Os dois maiores pacotes (`api` com ~1.200 linhas e `pipelines` com ~935)
são também os mais recentes: a superfície operacional cresceu depois que
o console passou a precisar dela.

---

## 3. O conceito central: o lake em camadas

Tudo no Explorer gira em torno de gravar em **camadas**, e a ordem
importa.

```python
# explorer/config.py
LAKE_LAYERS = ("raw", "normalized", "validated", "training",
               "exports", "reports", "signals")
```

O caminho no disco é sempre o mesmo:

```
{layer}/{competition}/{season}/{source}/{entity_type}/
```

| Camada | O que guarda | Quem lê |
|---|---|---|
| `raw` | A resposta **crua** do provedor, sem transformação | Ninguém em produção — é a rede de segurança |
| `normalized` | Já no envelope canônico, mas ainda não confiável | Etapas internas |
| `validated` | **Autoritativa.** Passou pelos validadores | **O Atlas** |
| `reports` | Rejeitados, fila de revisão, tickets, histórico de jobs | Operador, via console |
| `signals` | Sinais em tempo real | Framework de realtime |

### Por que preservar o `raw`

Custa disco e não é lido por ninguém. Vale mesmo assim: quando um
normalizador tem bug, você reprocessa o `raw` em vez de recoletar do
provedor — que pode ter mudado, ter rate limit, ou simplesmente não
servir mais aquela temporada.

### A armadilha do `validated`

**Só `validated` é autoritativa.** Isso já causou bug real: o watcher do
Atlas que sincroniza resultados apontava para a **raiz** do lake, onde
`raw` e `normalized` ficam ao lado. Corrigido para apontar
explicitamente à camada validada, e documentado nos dois scripts que
usam esse caminho.

### Deduplicação e segurança de replay

```python
# explorer/datalake/lake.py
def checksum(obj: Any) -> str:
    """Stable sha256 over canonical JSON. Used for dedup + replay safety."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
```

`sort_keys=True` e separadores fixos são o que tornam o hash **estável**:
o mesmo objeto sempre produz o mesmo checksum, independentemente da
ordem em que as chaves apareceram. Sem isso, rodar a coleta duas vezes
duplicaria tudo.

> **Melhoria já aplicada:** o `DataLake.append()` relia a partição
> inteira a cada chamada para calcular checksums. Como a partição cresce
> sem limite e nunca é podada, isso ficava mais lento a cada registro.
> Hoje existe um cache de checksums por partição em memória.

---

## 4. O fluxo de um job — passo a passo

Um **job** é a unidade de trabalho: uma fonte, uma competição, uma
temporada. O código está em `explorer/jobs/runner.py`, e vale seguir na
ordem porque cada etapa tem um porquê.

### Etapa 1 — o adapter suporta essa competição?

```python
if not adapter.supports(competition):
    rec.status = "skipped"
    rec.error = "adapter does not support competition"
```

`skipped` **não** é `failed`. Nem toda fonte cobre todo campeonato, e
tratar isso como erro encheria a fila de tickets de ruído.

### Etapa 2 — a fonte está no ar?

```python
online = _safe_health(adapter)
if not online:
    self.tickets.open(error_type="source_offline", ..., severity="high")
    rec.status = "failed"
```

Abre um **ticket** em vez de só logar. A diferença é operacional: um
ticket aparece no console para alguém agir.

### Etapa 3 — coleta, isolando falha por fonte

```python
except Exception as exc:  # noqa: BLE001 - crawler crash → ticket, keep partial
    self.tickets.open(error_type="collector_crash", ...)
    log.error("collector_crash", error=str(exc))
```

O `except` amplo é **intencional e comentado**. Um crawler que quebra no
meio não pode derrubar o job inteiro: o que já foi coletado é preservado
e o problema vira ticket. Repare que o `rec.records_collected` é contado
depois, sobre o que sobreviveu.

### Etapa 4 — o pipeline de qualidade

```python
pipeline = QualityPipeline(self.tickets, crew=self.crew, use_ai=self.use_ai)
state = pipeline.run(artifacts, competition, season, adapter.name)
rec.records_validated = len(state.validated)
rec.records_review    = len(state.review)
rec.records_rejected  = len(state.rejected)
```

Cada registro sai classificado em uma de três pilhas:

| Pilha | Significa | Destino |
|---|---|---|
| `validated` | Confiável | Camada `validated` → lido pelo Atlas |
| `review` | Duvidoso — precisa de humano | Fila de curadoria |
| `rejected` | Reprovado | Relatório em `reports/rejected` |

O limiar é configurável:

```python
# explorer/config.py
QUALITY_APPROVE_THRESHOLD = 0.70
```

Abaixo disso o registro vai para revisão humana — **não é descartado em
silêncio**. Essa é a regra que dá origem à tela de Curadoria no console.

### Etapa 5 — grava, e nunca joga fora

```python
# 5. write validated + preserve rejected/review (never drop)
if state.validated:
    self.lake.append("validated", ...)
if state.rejected:
    self.lake.append_report_lines("rejected", ...)
if state.review:
    self.lake.append_report_lines("review", ..., "queue.jsonl", records=[...])
```

O comentário `never drop` é a política: mesmo o rejeitado fica gravado.
Se amanhã o validador estiver errado, os dados ainda existem.

Repare que a fila de revisão guarda o **envelope completo**, não só um
identificador. É isso que permite ao operador promover o registro
direto da fila, sem recoletar.

---

## 5. Pipelines e execuções

Um **job** é uma coleta. Um **pipeline** agrupa jobs e define quando
rodam. Dois tipos:

| Tipo | O que faz |
|---|---|
| `historical` | Coleta um intervalo de temporadas, de uma vez ou agendado |
| `realtime` | Mantém coletores vivos consumindo sinais continuamente |

O motor está em `explorer/pipelines/engine.py`:

- **`ExecutionSupervisor`** — uma thread por execução, com
  `start_execution` / `pause` / `resume` / `stop`. É o que permite ao
  operador pausar uma coleta pela interface.
- **`RecurringDispatcher`** — substituiu o loop infinito do `Scheduler`
  legado.

> **Armadilha real, de produção:** `ExecutionControls.pipeline_execute()`
> só capturava `PipelineNotFound`, não o `ValueError` que
> `start_execution()` lança para um pipeline do tipo errado. Chamar
> `/execute` num pipeline realtime devolvia **500** em vez de um 409
> limpo. Corrigido e coberto por teste.

---

## 6. A superfície HTTP

Tudo em `explorer/api/app.py`, sob `/explorer/*`. Cerca de 70 endpoints,
agrupados assim:

| Grupo | Exemplos | Para quê |
|---|---|---|
| Estado | `/status`, `/runtime`, `/scheduler`, `/storage` | Painel operacional |
| Jobs | `/jobs`, `/jobs/active`, `/jobs/history`, `/jobs/{id}` | Ver o trabalho |
| Controle de jobs | `POST /jobs/start\|restart\|pause\|resume\|cancel` | Steering |
| Pipelines | CRUD + `execute`, `duplicate`, `start/stop/restart` | Mission Center |
| Curadoria | `/review`, `POST /review/promote\|reject\|replay` | Revisão humana |
| Qualidade | `/quality`, `/quality/datasets`, `/entity-resolution`, `/duplicates` | Saúde do dado |
| Tickets | `/tickets`, `POST /tickets/reprocess\|annotate` | Problemas |

### Autenticação

Header `X-Ops-Token` em **todos** os endpoints — inclusive os de leitura.

> Nem sempre foi assim. Só os `POST` exigiam token; toda a telemetria de
> auditoria, jobs e tickets era legível por qualquer um na rede. Foi
> corrigido no review de produção.

### Atribuição

Header `X-Operator`, preenchido pelo **Control Plane** a partir da sessão
que ele já resolveu. O console não envia mais ator nenhum — não existe
campo para falsificar.

> **Nota honesta:** o Explorer **não verifica** o `X-Operator`. É
> metadado de atribuição, não autenticação. A garantia hoje é que o valor
> é derivado no servidor; verificação do lado do Explorer está anotada
> como dívida.

---

## 7. Uma distinção que o console precisa respeitar

Os cinco endpoints de controle de job **não** são cinco variantes da
mesma coisa:

| Endpoint | Escopo | Corpo |
|---|---|---|
| `POST /jobs/start` | **Uma** (competição, temporada) | `{competition, season}` |
| `POST /jobs/restart` | **Uma** (competição, temporada) | `{competition, season}` |
| `POST /jobs/pause` | **O scheduler inteiro** | nenhum |
| `POST /jobs/resume` | **O scheduler inteiro** | nenhum |
| `POST /jobs/cancel` | **O scheduler inteiro** | nenhum |

Juntar os cinco num método só é exatamente como um botão "cancel"
acaba renderizado ao lado de **um** job cancelando **todos**. No Control
Plane isso é forçado pelo tipo — `taskAction` e `schedulerAction` são
métodos e rotas separados.

---

## 8. A camada de IA

`explorer/ai/` usa CrewAI + LangGraph sobre um Qwen local (Ollama).

Isso parece contradizer o princípio "o Explorer não é responsável por
IA" — e foi questionado. A resposta é que são categorias diferentes: a
IA aqui serve à **qualidade do dado** (detectar inconsistência, resolver
entidade), não à inteligência esportiva, que é do Atlas.

**Restrição de infraestrutura:** este Qwen roda na **CPU** do Robozão. A
GPU está reservada para os agentes do Nexus.

`EXPLORER_USE_AI=0` desliga a camada; o pipeline continua funcionando
com os validadores determinísticos.

---

## 9. Configuração

| Variável | Para quê |
|---|---|
| `EXPLORER_OPS_TOKEN` | Autentica **toda** chamada à API |
| `EXPLORER_RUN_SCHEDULER` | `1` liga o dispatcher recorrente |
| `EXPLORER_USE_AI` | `1` liga a camada de IA |
| `EXPLORER_OLLAMA_HOST` | Onde está o Qwen |
| `EXPLORER_QWEN_MODEL` | Ex.: `qwen2.5:7b` |
| `EXPLORER_REDIS_URL` | **Opcional.** Vazio = grava só no lake |

O Redis ser opcional é deliberado: o coletor de realtime precisa
continuar funcionando quando não há Redis configurado. A gravação no
lake é autoritativa; publicar no Redis é *best-effort*.

---

## 10. Relacionamentos

```
    provedores externos
           │
           ▼
    ┌─────────────┐
    │  EXPLORER   │
    └──┬───────┬──┘
       │       │
       │       └──► Redis (opcional) ──► sinais
       │
       ▼ lake validated (disco)
    ┌─────────────┐
    │    ATLAS    │  monta /home/insight/data/explorer como
    └─────────────┘  /var/atlas/explorer:ro
```

E do lado operacional:

```
   Console ──► Control Plane ──► Explorer
                              (X-Ops-Token + X-Operator)
```

**O Atlas lê o lake por volume montado, não por HTTP.** O `docker-compose`
monta o diretório do Explorer dentro do container do Atlas em modo
somente-leitura. Isso já foi origem de bug: o volume não existia no
compose de produção, e o `StrengthSyncWatcher` do Atlas lia um diretório
vazio em silêncio.

---

## 11. Curiosidade de ambiente que vale saber

O Windows (não o Linux, que é o alvo real) apresenta `PermissionError`
transitório em rename atômico + leitura concorrente do mesmo JSON —
interferência de antivírus. Existe um `_retry_on_transient_os_error`
nos stores de pipeline e execução. Não é gambiarra de teste: é
resiliência legítima, só que motivada por um ambiente de
desenvolvimento.

---

## Próximo passo

**[Parte 3 — Insight Atlas](03-insight-atlas.md)**: o que a plataforma
faz com esses dados.
