# Parte 5 — Insight Nexus

> **Papel em uma frase:** transforma a inteligência do Atlas em
> comunicação — decide se vale falar, quem fala, e o que dizer de novo
> sobre uma história que já está em curso.
>
> **Linguagem:** Go · **Arquitetura:** hexagonal (ports & adapters)
> **Portas:** 8090 (HTTP) · 9090 (gRPC Operations)
> **Tamanho:** ~12.800 linhas · **Persistência:** PostgreSQL (schema `nexus`) + Redis

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
//
// What it still does NOT do: any intelligence of its own. It never computes
// similarity, never collects data, never serves a public API. Atlas decided;
// Nexus only chooses whether and how to say it.
```

> Esse comentário terminava com *"no intelligence logic, no LLMs, no
> social output"*. Descrevia o Sprint 3 e deixou de ser verdade no
> Sprint 4 — o Nexus tem LLM e tem saída social. Ficou lá tempo
> suficiente para enganar, e por isso a correção diz isso
> explicitamente em vez de só apagar.

A metade que continua valendo é a que importa:

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

## 6. Os dois laços — e por que são separados

Esta é a correção mais estrutural que o serviço recebeu.

### Como era

`HandleTrend` chamava o motor de publicação **inline**, logo depois de
enfileirar o rascunho. Duas consequências:

1. **Nada nunca lia as filas.** O port `DraftQueue` tinha `Enqueue` e
   `Depth` — e nenhum `Dequeue`. As filas cresciam até o `MaxLen` cortar
   as entradas **mais antigas**, que numa fila de publicação são
   exatamente os rascunhos que esperavam há mais tempo. E o `ActiveJobs`
   do gRPC Operations reportava a profundidade como "jobs ativos": um
   número que só subia e nunca completava.
2. **Uma chamada de LLM lenta travava o stream inteiro.** O pior caso é
   um timeout por provedor, por agente, por tendência — com a próxima
   tendência esperando atrás de tudo isso.

### Como é

```
consumer de trends → pipeline → fila por agente        (rápido)
publish worker     ← fila     → LLM → valida → Social  (lento)
```

O handler de tendência retorna assim que o rascunho está durável e
enfileirado. Cada agente drena a própria fila em uma goroutine — um
agente cuja persona sempre estoura o timeout atrasa só o próprio
backlog.

**O que a entrega garante:** a tendência só é confirmada depois que a
linha do rascunho, a linha do candidato e a entrada da fila estão todas
duráveis. Uma queda entre o enfileiramento e a publicação não perde
nada: a entrada fica não-confirmada e é reentregue.

E a fila **deixou de ser limitada**. Backlog é coisa para alarmar
(`nexus_queue_depth`), não para esconder apagando a cabeça.

---

## 6.1 A identidade migrou para o Control Plane

O Nexus autenticava operadores contra o **gateway público** — que, pelo
`insight-context.md` v2.0, não responde por operadores. Com
`NEXUS_GATEWAY_IDENTITY_URL` vazio, **toda a API administrativa
respondia 503** e o console não tinha tela nenhuma do Nexus.

Hoje ele fala o mesmo salto que o Node Agent
([Parte 8](08-node-agent.md), seção 3): token de serviço com
`subtle.ConstantTimeCompare`, mais os headers do operador que o Control
Plane repassa.

```
{"authority":"control-plane","event":"admin_api_unlocked"}
```

### A divisão de autoridade

> **O Control Plane decide quem você é e o que você tem. O Nexus decide
> o que as rotas dele exigem.**

Nenhum dos dois reimplementa a metade do outro. Resolver papel →
permissão dentro do Nexus bifurcaria a tabela de RBAC; colocar os
requisitos das rotas no Control Plane faria de cada endpoint novo do
Nexus uma mudança em dois serviços.

E o header de permissões ausente **nega**:

```go
if len(permissions) == 0 {
	authError(w, http.StatusForbidden,
		"control plane sent no "+headerOperatorPerms)
	return Claims{}, false
}
```

Um header esquecido não pode virar autoridade ilimitada.

O caminho antigo pelo Gateway continua existindo, escolhido por
configuração — a migração é uma variável, não um deploy coordenado.

---

## 6.2 O que passou a falhar no boot

Três configurações subiam bem e falhavam uma requisição por vez:

| Configuração | Antes | Agora |
|---|---|---|
| Publisher ligado, zero provedores | Um ticket por rascunho, para sempre | Recusa no boot |
| Publisher ligado, sem endereço do Social | Publicação falhava sem explicar | Recusa no boot |
| `MIN_IDLE` < duração máxima do handler | Duas réplicas publicariam o mesmo post | Derivado, ou recusado se explícito |

O terceiro merece detalhe. O claimer entrega uma entrada pendente a um
**segundo** consumer depois de N segundos ociosa. Se isso puder
acontecer enquanto o primeiro ainda está dentro de uma chamada de LLM,
**os dois publicam**. O piso é `NEXUS_LLM_TIMEOUT × nº de provedores` —
e é **derivado**, não uma constante, porque aumentar o timeout sem
perceber que invalidou um MinIdle escolhido à mão é exatamente como
isso vira incidente.

Não configurado, ele é elevado ao piso (e o boot diz que elevou).
Configurado abaixo, o serviço recusa subir: alguém digitou aquele
número e precisa saber por que ele não pode valer.

---

## 6.3 Escrituração pós-publicação

Duas escritas rodam **depois** que o post já está no Social: o log do
anti-spam e a memória de publicação. A primeira descartava o erro
direto (`_ =`); a segunda só logava.

As duas alimentam guardrails — a memória é contra o que o validador de
repetição compara, e o log do anti-spam é o que faz valer os cooldowns.
Perder qualquer uma em silêncio faz o agente se repetir ou postar de
novo imediatamente.

Elas também **não podem propagar erro**: a entrada da fila ficaria
não-confirmada, o worker reentregaria, e o agente postaria uma
**segunda vez**.

O tratamento: retentar poucas vezes (são inserts simples), e então
registrar a perda num contador
(`nexus_post_publish_bookkeeping_failures_total`) e na própria linha do
candidato — que passa a ser salva **por último**, para carregar o
desfecho. A tela de Publicações mostra isso explicitamente.

---

## 6.4 O que ainda está pendente

**O stream nunca recebeu nada.**

```
$ redis-cli XLEN insight:stream:trends
0
$ redis-cli XINFO GROUPS insight:stream:trends
name: insight-nexus   consumers: 1   pending: 0   lag: 0
```

`lag: 0` com `XLEN 0` significa *"em dia com um stream vazio"*, não
*"consumindo e descartando"*. O Nexus está pronto e ocioso — depende de
o Atlas estar processando partidas ao vivo.

**A publicação continua desligada.** Os três provedores e o publisher
estão `false`. O worker não sobe, e o log diz isso:
`publish_worker_not_started_publisher_disabled`.

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
| `NEXUS_CONTROL_PLANE_TOKEN` | — | vazio | **Preenchido ⇒ API admin destrancada** |
| `NEXUS_GATEWAY_IDENTITY_URL` | — | vazio | Legado; só vale se o token acima estiver vazio |
| `NEXUS_PUBLISH_CONSUMER_GROUP` | — | `insight-nexus-publish` | Grupo próprio das filas |
| `NEXUS_CLUSTER_EXPIRE_MINUTES` | — | `90` | |
| `NEXUS_SPAM_*` | — | 5/15/30/10 min, 6/h, 30/dia | |
| `NEXUS_CLAIMER_MIN_IDLE` | — | **derivado** | `LLM_TIMEOUT × provedores` quando o publisher está ligado |
| `NEXUS_DLQ_STREAM` | — | `insight:dlq:nexus` | |

> A configuração é lida **uma vez, no start**. Não há hot-reload — nem
> de provedores, nem de política de spam. Mudança exige restart.
>
> As variáveis `OLLAMA_BASE_URL`, `NEXUS_QWEN_MODEL` e `NEXUS_LLAMA_MODEL`
> **foram removidas**: eram obrigatórias no compose e lidas por ninguém,
> restos de quando havia modelos locais. E o compose passava
> `SOCIAL_GRPC_ADDR` enquanto o código lê `NEXUS_SOCIAL_GRPC_ADDR`, então
> o endereço do Social nunca chegava — invisível com o publisher
> desligado.

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
| Imagem | `konohalabs/insight-nexus:0.1.0`, `healthy` |
| Consumer group | Registrado, 0 pending, 0 lag |
| Tendências processadas | **0** — o stream nunca recebeu nada |
| API administrativa | **Destrancada** via Control Plane, verificado no ar |
| Provedores de LLM | Os três desligados por configuração |
| Publisher / publish worker | Desligados por configuração |
| Telas no console | **2** — Agentes e Publicações, ambas em 200 |
| Agentes / personas | 5 e 5, populados, com restrições próprias |

O Nexus continua sendo o serviço mais completo em código e o menos
exercitado em produção. O caminho administrativo agora está validado
ponta a ponta (console → Control Plane → Nexus); o caminho de
publicação **não** — ele depende de tendências do Atlas e de provedores
de LLM que ainda não foram ligados.

---

## Próximo passo

**[Parte 6 — Insight Control Plane](06-insight-control-plane.md)**: a
autoridade administrativa, e a inversão que ela corrigiu.
