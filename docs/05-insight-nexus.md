# Parte 5 — Insight Nexus

> **Papel em uma frase:** transforma a inteligência do Atlas em
> comunicação — decide se vale falar, quem fala, e o que dizer de novo
> sobre uma história que já está em curso.
>
> **Linguagem:** Go · **Arquitetura:** hexagonal (ports & adapters)
> **Portas:** 8090 (HTTP) · 9090 (gRPC Operations)
> **Tamanho:** ~12.450 linhas · **Persistência:** PostgreSQL (schema `nexus`) + Redis

---

## 1. Por que este serviço existe

O Atlas produz **tendências avaliadas**. Sozinhas, elas não viram nada:
alguém precisa decidir se aquilo merece ser dito, por qual voz, e como
não repetir a mesma frase três vezes na mesma partida.

É esse o trabalho do Nexus. E o contrato dele é bem estreito — está
escrito no topo do `main.go`:

```go
// Nexus converts intelligence into communication: it consumes Atlas's
// evaluated trends off insight:stream:trends (its ONLY input), ...
// No intelligence logic, no LLMs, no social output.
```

Esse comentário descreve o Sprint 3. Hoje o Nexus **tem** LLM e **tem**
saída social (Sprint 4) — mas a primeira metade continua valendo, e é a
que importa:

> **`insight:stream:trends` é a ÚNICA entrada.** O Nexus não consulta o
> Atlas, não lê o lake do Explorer, não chama o Anvil. Se não veio pelo
> stream, não existe para ele.

Isso é o que impede o Nexus de virar um segundo motor de inteligência.
Ele não *deduz* nada sobre futebol — só decide sobre **comunicação**.

---

## 2. Arquitetura hexagonal — vale entender antes do resto

Diferente do Explorer e do Atlas (Python, camadas por assunto), o Nexus
segue **ports & adapters** de forma bem literal:

```
internal/
├── domain/        ← regras puras. NÃO importa banco, HTTP, Redis.
│   agent  cluster  decision  draft  evolution
│   memory  persona  publication  state  trend
│
├── application/   ← os casos de uso. Orquestram o domínio.
│   pipeline  router  clustering  publication  agentstate
│   evolution  contextbuilder  draftgen  publisher  antispam …
│
├── ports/         ← as INTERFACES que a aplicação exige
│
└── adapters/      ← as implementações concretas
    postgres  redisstream  llm  social  httpapi  inmemory  observability
```

A regra que mantém isso honesto: **as setas só apontam para dentro**. O
`domain` não sabe que Postgres existe; a `application` conhece
`ports.DraftRepository`, não `postgres.DraftRepo`.

O ganho prático não é elegância — é que existe `adapters/inmemory`, o
que permite testar o pipeline inteiro sem subir banco nenhum. Existe
inclusive `tests/architecture/` para impedir que alguém quebre a regra
das setas com um import descuidado.

---

## 3. O pipeline — sete estágios, sete perguntas

Cada tendência que entra atravessa esta sequência
(`internal/application/pipeline/pipeline.go`):

```
        Trend Consumer  ← insight:stream:trends
              ↓
1.  Agent Router          "quem PODERIA comunicar isso?"
              ↓  (por agente)
2.  Trend Clustering      "de qual HISTÓRIA isso faz parte?"
              ↓
3.  Publication Decision  "deveria existir comunicação, afinal?"
              ↓
4.  Agent State Engine    "onde o agente está no arco dessa história?"
              ↓
5.  Draft Evolution       "que TIPO de fala vem agora?"
              ↓
6.  Draft Generator       "o rascunho, com metadados de feed"
              ↓
7.  Publishing Queue      → fila por agente
```

O comentário do próprio pacote explica por que isso não é
sobre-engenharia:

> *"Nexus no longer reacts to isolated trends: communication operates on
> clusters, every decision is persisted with its reasoning, and the same
> story evolves (initial → follow-up → confirmation → retrospective)
> instead of repeating."*

Reagir a tendências isoladas produz exatamente o que você imagina: três
posts dizendo "a pressão está aumentando" em dez minutos.

### 3.1 Clustering — a peça central

Uma partida gera dezenas de tendências. Muitas são **a mesma história**
evoluindo. O cluster é a unidade real: o anti-spam, o estado do agente e
a evolução do rascunho são todos chaveados por cluster, não por
tendência.

Clusters expiram (`NEXUS_CLUSTER_EXPIRE_MINUTES`, padrão 90), e o
`matchsweep` fecha os que ficaram para trás quando a partida acaba.

### 3.2 Decisão de publicação — cinco ações

```go
// internal/domain/decision/decision.go
ActionIgnore       Action = "IGNORE"
ActionMemoryOnly   Action = "MEMORY_ONLY"
ActionDraft        Action = "DRAFT"
ActionHighPriority Action = "HIGH_PRIORITY_DRAFT"
ActionGlobal       Action = "GLOBAL_CANDIDATE"
```

`MEMORY_ONLY` é a mais interessante: o agente **registra** que viu, mas
não fala. Isso alimenta continuidade — daqui a vinte minutos ele pode
dizer "como eu já vinha observando…" com base real.

```go
// Remembers reports whether the action writes agent memory (everything
// except a hard ignore — even memory-only observations feed continuity).
func (a Action) Remembers() bool { return a != ActionIgnore }
```

E, alinhado ao resto da plataforma:

> *"Every decision is persisted with its full reasoning — no black-box
> decisions."*

Toda decisão vai para `nexus.publication_decisions` **com o motivo**.
Não existe "o Nexus resolveu não postar" sem registro do porquê.

### 3.3 Estado do agente — cinco posturas

```go
Idle          "IDLE"          // nenhuma narrativa ativa
Observing     "OBSERVING"     // detecção inicial
Tracking      "TRACKING"      // o mesmo tema evoluindo
Alerting      "ALERTING"      // comunicação crítica
Retrospective "RETROSPECTIVE" // análise pós-evento
```

Um estado ativo por `(agente, partida, cluster)`. As transições são
determinísticas e ficam no histórico — dá para auditar por que o agente
foi de `Tracking` para `Alerting`.

### 3.4 Evolução do rascunho — o antídoto contra repetição

```go
InitialObservation → FollowUp → Confirmation → Retrospective
```

Com `Sequence` (posição 1-based dentro do cluster). O comentário do
pacote é direto sobre o problema que isso resolve:

> *"never repeat ('pressure increasing' three times)."*

---

## 4. O Anti-Spam Engine

Separado do pipeline, e por um motivo: ele decide sobre o **histórico
persistido**, não sobre o que está em memória.

```go
type Policy struct {
	AgentCooldown   time.Duration // entre QUAISQUER dois posts de um agente
	ClusterCooldown time.Duration // entre posts sobre uma história
	TrendCooldown   time.Duration // entre posts sobre uma tendência
	MatchCooldown   time.Duration // entre posts de um agente numa partida
	HourlyLimit     int
	DailyLimit      int
}
```

Padrões conservadores: 5min / 15min / 30min / 10min, 6 por hora, 30 por
dia.

Duas coisas merecem destaque.

**Sobrevive a restart.** O log fica em `nexus.publication_log`, gravado
**depois** que o post chega ao Social. Cooldown em memória seria zerado
a cada deploy — e deploy é justamente quando se quer garantia.

**Toda supressão é explicada:**

```go
// Every suppression returns a machine-readable explanation — "explain
// every suppression" is a platform non-negotiable.
```

"O agente não postou" sem motivo legível é indistinguível de bug.

---

## 5. Os provedores de LLM

Três, todos privados. **Modelos locais não são registrados no Nexus** —
o comentário no `main.go` é explícito: *"Local models are never
registered in Nexus."*

| Provedor | Identidade no router | Modelo padrão | Flag |
|---|---|---|---|
| Anthropic | `claude` | `claude-haiku-4-5-20251001` | `NEXUS_ENABLE_ANTHROPIC` |
| OpenAI | `gpt` | `gpt-4o-mini` | `NEXUS_ENABLE_OPENAI` |
| Gemini | `gemini` | `gemini-2.5-flash` | `NEXUS_ENABLE_GEMINI` |

### O router faz failover a quente

Durante uma requisição: provedor offline é pulado; provedor degradado é
pulado **se houver alternativa saudável**; falha de geração ou de
validação avança para o próximo.

E quando a cadeia acaba:

> *"Exhausting the chain returns the existing all-providers-failed path;
> it does not publish fallback text."*

**Não existe texto de fallback.** Um post genérico publicado sob a voz
de um agente é pior que post nenhum — abre um ticket em vez disso.

### Três flags independentes, e por quê

```go
if settings.EnableAnthropic { providerByName["anthropic"] = ... }
```

Habilitar o adaptador ≠ ter credencial ≠ publicar. São três chaves
distintas:

1. `NEXUS_ENABLE_*` registra o adaptador
2. a credencial faz ele funcionar (vazia = adaptador registrado e offline)
3. `NEXUS_PUBLISHER_ENABLED` libera a publicação

Isso permite ligar geração para inspecionar rascunhos **sem** que nada
saia para o Social.

### Social fora do ar no boot não é fatal

```go
// Social unreachable at boot is NOT fatal: the publisher stays off and
// drafts keep queueing (no content is lost; publication resumes on
// restart once Social is up).
```

O Nexus roda no Robozão; o Social roda no Google Cloud. Morrer no boot
por causa de uma dependência de rede entre planos deixaria o Nexus fora
do ar toda vez que a nuvem oscilasse — e ele tem trabalho útil a fazer
sem publicar nada.

---

## 6. O que está pendente — sem maquiagem

### 6.1 A API administrativa está trancada

Verificado agora, contra o container em execução:

```
$ curl http://insight-nexus:8090/v1/agents
{"error":"admin api locked: Gateway identity endpoint not configured"}
code: 503
```

O motivo está em `internal/adapters/httpapi/auth.go`:

```go
// Nexus does not mint or verify operator credentials, own sessions, or
// define roles. It forwards the opaque operator session to Insight
// Gateway's /v1/operator/auth/me endpoint ...
```

**O Nexus é o último serviço ainda no modelo antigo de identidade.** Ele
espera que o *Gateway da nuvem* valide operadores — exatamente a
inversão que o Control Plane corrigiu (ver [Parte 6](06-insight-control-plane.md),
seção 3). Como `NEXUS_GATEWAY_IDENTITY_URL` está vazio, toda a API
administrativa responde 503.

O comportamento em si está **certo**: sem autoridade de identidade
configurada, ele tranca em vez de liberar. Fail-closed é a direção
segura. Mas a autoridade que ele procura é a errada — migrar essa
validação para o Control Plane é trabalho pendente.

Consequência visível: as telas de publicação foram removidas do menu do
console (`publication-center`), porque não havia como chamá-las.

### 6.2 O stream nunca recebeu nada

```
$ redis-cli XLEN insight:stream:trends
0
$ redis-cli XINFO GROUPS insight:stream:trends
name: insight-nexus   consumers: 1   pending: 0   lag: 0
```

O consumer group está registrado e saudável. Simplesmente **nenhuma
tendência foi publicada ainda** — o caminho depende de o Atlas estar
processando partidas ao vivo.

Distinção que importa: `lag: 0` com `XLEN 0` significa *"em dia com um
stream vazio"*, não *"consumindo e descartando"*. O Nexus está pronto e
ocioso.

### 6.3 Variáveis do compose que o código não lê mais

O `docker-compose.yml` exige três variáveis como obrigatórias:

```yaml
OLLAMA_BASE_URL:   ${NEXUS_OLLAMA_BASE_URL:?...}
NEXUS_QWEN_MODEL:  ${NEXUS_QWEN_MODEL:?...}
NEXUS_LLAMA_MODEL: ${NEXUS_LLAMA_MODEL:?...}
```

Nenhuma das três é lida pelo código — `grep -rn "OLLAMA\|QWEN\|LLAMA"`
no repositório do Nexus não retorna nada. São restos de quando o Nexus
usava modelos locais, antes da política de "provedores privados apenas".

O `:?` as torna **obrigatórias para subir**: hoje elas bloqueiam o
deploy sem afetar comportamento nenhum. O container `insight-qwen-runtime`
continua no ar pelo mesmo motivo histórico.

> Limpeza pendente, de baixo risco — mas fazê-la exige remover as
> variáveis do compose **e** do `.env` juntas, senão o `:?` derruba o
> serviço.

---

## 7. Configuração

| Variável | Obrigatória | Padrão | Observação |
|---|---|---|---|
| `DATABASE_URL` | sim | — | schema `nexus` |
| `REDIS_ADDR` | — | `localhost:6379` | o mesmo Redis do Atlas |
| `TREND_STREAM` | — | `insight:stream:trends` | a única entrada |
| `NEXUS_CONSUMER_GROUP` | — | `insight-nexus` | |
| `NEXUS_PUBLISHER_ENABLED` | — | `false` | **desligado hoje** |
| `NEXUS_SOCIAL_GRPC_ADDR` | — | vazio | Social na nuvem |
| `NEXUS_ENABLE_ANTHROPIC/OPENAI/GEMINI` | — | `false` | **os três desligados** |
| `NEXUS_GATEWAY_IDENTITY_URL` | — | vazio | **vazio ⇒ API admin em 503** |
| `NEXUS_CLUSTER_EXPIRE_MINUTES` | — | `90` | |
| `NEXUS_SPAM_*` | — | 5/15/30/10 min, 6/h, 30/dia | |
| `NEXUS_CLAIMER_*` | — | on, 30s, 15s, 8 | reentrega de pendentes |
| `NEXUS_DLQ_STREAM` | — | `insight:dlq:nexus` | |

> A configuração é lida **uma vez, no start**. Não há hot-reload — nem
> de provedores, nem de política de spam. Mudança exige restart.

---

## 8. Relacionamentos

```
   ┌─────────┐  publica   ┌───────────────────────┐  consome   ┌─────────┐
   │  ATLAS  │ ─────────► │ insight:stream:trends │ ─────────► │  NEXUS  │
   └─────────┘            └───────────────────────┘            └────┬────┘
                                                                    │
                        ┌───────────────────────────────────────────┤
                        ▼                    ▼                      ▼
                 ┌─────────────┐    ┌────────────────┐     ┌───────────────┐
                 │  Postgres   │    │ filas por      │     │ LLM privados  │
                 │schema nexus │    │ agente (Redis) │     │ (desligados)  │
                 └─────────────┘    └────────┬───────┘     └───────────────┘
                                             │
                                             ▼  (publisher desligado)
                                    ┌──────────────────┐
                                    │ SOCIAL (gRPC,    │
                                    │ Google Cloud)    │
                                    └──────────────────┘
```

O Node Agent enxerga o Nexus na descoberta de serviços; o Control Plane
sonda a saúde. **Nenhuma tela do console fala com ele hoje** — ver 6.1.

---

## 9. Estado atual, resumido

| Item | Estado |
|---|---|
| Processo | No ar, `healthy`, há 7 horas |
| Consumer group | Registrado, 0 pending, 0 lag |
| Tendências processadas | **0** — o stream nunca recebeu nada |
| API administrativa | **503** — identidade apontando para o Gateway |
| Provedores de LLM | Os três desligados por configuração |
| Publisher | Desligado por configuração |
| Telas no console | Nenhuma |

O Nexus é, hoje, o serviço mais completo em código e o menos exercitado
em produção. Isso não é problema por si — mas nada nele foi validado
ponta a ponta contra tráfego real, e a documentação não deve sugerir o
contrário.

---

## Próximo passo

**[Parte 6 — Insight Control Plane](06-insight-control-plane.md)**: a
autoridade administrativa, e a inversão que ela corrigiu.
