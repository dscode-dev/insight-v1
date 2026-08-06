# Parte 8 — Node Agent (Robozão)

> **Papel em uma frase:** é o agente da **máquina** — reporta o estado
> do nó, agrega a saúde dos serviços por gRPC e mantém o registro
> operacional local.
>
> **Repositório:** `backend_services/insight-robozao-gateway`
> **Linguagem:** Go · **Porta:** 8095 · **Persistência:** PostgreSQL
> **Tamanho:** ~3.377 linhas

---

## 1. O nome está errado, e isso importa

O diretório e o binário se chamam `robozao-gateway`. **Ele não é um
gateway.** O `insight-context.md` v2.0 é explícito sobre o que este
componente é:

> *Node Agent (Robozão) — estado da máquina. **Nunca deve oferecer proxy
> HTTP.***

"Gateway" é o nome de quando ele fazia proxy dos serviços do Robozão
para fora. Essa responsabilidade migrou para o Control Plane. O nome
ficou.

Guarde essa frase — a seção 6 mostra que ela ainda não é verdade no
código.

---

## 2. O que ele legitimamente faz

### 2.1 Agrega saúde por gRPC

O Node Agent não faz polling HTTP nos serviços. Ele fala **gRPC
Operations**, um contrato compartilhado (`insight-protos`) que cada
serviço implementa:

```go
type Client interface {
	Ping(context.Context, ServiceRef) (*operationsv1.PingResponse, int64, error)
	Health(context.Context, ServiceRef) (*operationsv1.HealthResponse, error)
	Status(context.Context, ServiceRef) (*operationsv1.StatusResponse, error)
	Capabilities(context.Context, ServiceRef) (*operationsv1.CapabilitiesResponse, error)
	Metrics(context.Context, ServiceRef) (*operationsv1.MetricsResponse, error)
}
```

O registro é declarativo, em `internal/controlplane/service_registry.json`:

```json
{"id":"atlas","operations":{"transport":"grpc",
  "endpoint_env":"ATLAS_OPERATIONS_GRPC_ADDR",
  "default_endpoint":"atlas:9081",
  "enabled_env":"ATLAS_OPERATIONS_ENABLED","default_enabled":true}}
```

Cinco serviços registrados hoje: `atlas`, `explorer`, `nexus`,
`sport-hub`, `qwen`. Cada um com endpoint **e** flag de habilitação
próprios — um serviço pode ser desligado da agregação sem editar código.

Confirmado no ar:

```
{"msg":"robozao_gateway_listen","addr":":8095","registry_services":5}
```

### 2.2 Guarda o histórico operacional

Eventos, tickets, runs, datasets, treinos, incidentes e comandos vão
para Postgres (`migrations/0001_operations.sql`). Serviços **ingerem**
(`POST /operations/events`, `/tickets`, `/runs`, `/datasets`) com o
`OPS_INGEST_TOKEN`; o Control Plane **lê**.

### 2.3 Executa comandos com aprovação dupla

Comandos sensíveis não executam direto:

```go
command.Status = "waiting_approval"
```

E aprovar o próprio comando é recusado:

```go
if command.RequestedBy == actor.ID {
	return Command{}, errors.New("self_approval_forbidden")
}
```

Traduzido para HTTP como **403** (`self_approval_forbidden`) e **409**
(`operation_not_waiting_approval`) — códigos distintos, porque "você não
pode" e "não é o momento" são problemas diferentes e o operador precisa
saber qual.

Um comando que ficou `running` quando o processo caiu é marcado
`failed` com `execution_interrupted` no boot seguinte. Ficar `running`
para sempre é pior: sugere trabalho em curso que não existe.

### 2.4 Auditoria de tudo

```json
{"msg":"operations_audit","operator_id":"791839cf-…",
 "action":"operations.status","target_service":"all","outcome":"accepted"}
```

Toda chamada autenticada gera linha de auditoria com operador, ação,
alvo e desfecho.

---

## 3. A autenticação — e o 401 que travou tudo

### O problema

O Node Agent validava operador chamando o **Gateway da nuvem** em
`/v1/operator/auth/me`. Quando o Control Plane assumiu a identidade
administrativa, o Control Plane passou a chamar o Node Agent com um
token que o Gateway não conhecia — **401 em tudo**.

Mesmo problema conceitual do Nexus ([Parte 5](05-insight-nexus.md),
seção 6.1). A diferença é que aqui foi corrigido.

### A correção

```go
func (cfg config) authenticateCaller(w http.ResponseWriter, r *http.Request) (controlplane.Operator, bool) {
	if cfg.ControlPlaneToken != "" {
		got := r.Header.Get("X-Control-Plane-Token")
		if got == "" || subtle.ConstantTimeCompare(
			[]byte(got), []byte(cfg.ControlPlaneToken)) != 1 {
			writeJSON(w, http.StatusUnauthorized,
				map[string]string{"detail": "invalid_control_plane_token"})
			return controlplane.Operator{}, false
		}
		return controlplane.Operator{
			ID:       r.Header.Get("X-Operator-Id"),
			Username: r.Header.Get("X-Operator"),
			Role:     r.Header.Get("X-Operator-Role"),
		}, true
	}
	return cfg.validateOperatorViaGateway(w, r)  // fallback legado
}
```

Três decisões dentro desse trecho:

**`subtle.ConstantTimeCompare`, não `==`.** Comparação de string sai no
primeiro byte diferente. O tempo de resposta vaza quantos bytes estavam
certos, e um atacante descobre o token byte a byte.

**A identidade vem por header, sem revalidação.** Quando o
`CONTROL_PLANE_TOKEN` confere, o Node Agent **confia** no Control Plane
sobre quem é o operador. Isso é correto: o Control Plane *é* a autoridade
de identidade. Revalidar seria duplicar a autoridade — e foi exatamente
o que causou o 401.

**O fallback legado só roda se o token não estiver configurado.** A
migração acontece por configuração, não por deploy coordenado.

### O teste que prova a ausência de chamada

```go
// aponta InsightGatewayURL para uma porta morta
```

Se o código chamasse o Gateway mesmo com o token do Control Plane
válido, o teste falharia com erro de conexão. Ele prova uma
**ausência** — que é o tipo de coisa mais difícil de testar e a mais
fácil de regredir.

---

## 4. Superfície HTTP

| Rota | O que faz |
|---|---|
| `GET /healthz` `/readyz` | Liveness / readiness |
| `GET /v1/registry`, `/operations/services` | Serviços registrados |
| `GET /operations/health` `/status` `/capabilities` `/metrics` | Agregação gRPC |
| `GET /operations/actions` | Catálogo de ações |
| `POST /operations/{events,tickets,runs,datasets}` | Ingestão |
| `GET /operations/{events,tickets,runs,datasets,training,history,incidents}` | Consulta |
| `POST /operations/incidents`, `/{id}/{action}` | Ciclo de incidente |
| `GET/POST /operations/commands`, `/{id}/approve` | Comandos |
| `POST /v1/telemetry/events` | Telemetria |
| `GET /vpn/status` | Conectividade |

Além disso, `ROBOZAO_ALLOWED_CIDRS` restringe por origem de rede — uma
segunda camada abaixo do token.

---

## 5. O que o Control Plane consome

Antes, o console fazia **quatro sondagens** separadas. Foram consolidadas
em uma:

```
GET /platform/health   →   Control Plane   →   Node Agent
                                            →   agregação gRPC dos 5 serviços
```

Quatro round-trips viraram um, e o painel deixou de conseguir mostrar
quatro estados inconsistentes entre si.

---

## 6. O que ainda está errado: o `HTTPExecutor`

Esta é a pendência que a Fase C deixou aberta, e ela contradiz o
documento de arquitetura de forma direta.

`internal/operations/commands.go` contém:

```go
// HTTPExecutor is intentionally narrow: an action must be both present
// in the action catalog and implemented in this switch before any
// upstream call occurs.
type HTTPExecutor struct {
	ExplorerURL   string
	ExplorerToken string
	GatewayURL    string
	GatewayToken  string
	Client        *http.Client
}
```

Ele faz chamadas HTTP autenticadas para o Explorer **e para o Gateway da
nuvem**:

```go
case "explorer.pipeline.pause":  path = "/explorer/jobs/pause"
case "platform.dlq.replay":      baseURL, token = e.GatewayURL, e.GatewayToken
case "identity.session.revoke":  path = "/v1/internal/operations/users/…/sessions/revoke"
case "social.agent.deactivate", "social.agent.reactivate":
```

**Isso é proxy HTTP** — precisamente o que o `insight-context.md` diz que
o Node Agent nunca deve oferecer. E não é código morto: as credenciais
estão configuradas no container em execução.

```
$ docker exec insight-robozao-gateway printenv | grep -E 'EXPLORER|GATEWAY'
EXPLORER_URL=<set>
EXPLORER_OPS_TOKEN=<set>
GATEWAY_OPS_URL=<set>
GATEWAY_OPS_TOKEN=<set>
```

### Por que isso é um problema concreto

1. **Duplica autoridade.** O Control Plane já tem classificadores de path
   com allow-list default-deny ([Parte 6](06-insight-control-plane.md),
   seção 5). O `HTTPExecutor` é um segundo caminho até os mesmos
   serviços, com regras próprias, escritas em um `switch`.
2. **Espalha credencial.** Tokens do Explorer e do Gateway existem em dois
   lugares. O trabalho da Fase B foi justamente concentrá-los.
3. **`identity.session.revoke` é ação de identidade** — que pertence ao
   Control Plane por definição.

### O que salva por enquanto

O comentário não é vazio: uma ação precisa estar **no catálogo E no
`switch`** para chegar a qualquer upstream. Não é proxy genérico, é uma
lista fechada de 13 ações com validação de payload. Não é um buraco
aberto — é uma porta que não deveria existir.

### O caminho da remoção

Mover cada ação para o Control Plane, que já tem capability, autorização
e audit spine para governá-las; depois remover o `HTTPExecutor` e as
quatro variáveis de ambiente. As ações de incidente (`operations.incident.*`)
**ficam** — essas são estado local do nó, e é disso que o Node Agent é
dono.

---

## 7. Configuração

| Variável | Observação |
|---|---|
| `HTTP_ADDR` | `:8095` |
| `OPERATIONS_DATABASE_URL` | Histórico operacional |
| `CONTROL_PLANE_TOKEN` | **Preenchido ⇒ confia no Control Plane** |
| `OPS_INGEST_TOKEN` | Ingestão pelos serviços |
| `ROBOZAO_ALLOWED_CIDRS` | Restrição por origem |
| `*_OPERATIONS_GRPC_ADDR` | Um por serviço registrado |
| `INSIGHT_GATEWAY_URL` | **Legado** — só o fallback usa |
| `EXPLORER_URL` / `EXPLORER_OPS_TOKEN` | **A remover** (seção 6) |
| `GATEWAY_OPS_URL` / `GATEWAY_OPS_TOKEN` | **A remover** (seção 6) |

---

## 8. Uma nota de build

O `Dockerfile` referenciava `robozao-gateway/` enquanto o diretório no
monorepo é `insight-robozao-gateway/`. O build quebrava com "path not
found" — sintoma que não aponta para a causa. Alinhado à convenção do
monorepo (todo serviço é `insight-*`).

---

## 9. Estado atual

| Item | Estado |
|---|---|
| Imagem | `konohalabs/insight-robozao-gateway:0.1.0`, `healthy` |
| Serviços no registro | 5 — atlas, explorer, nexus, sport-hub, qwen |
| Auth via Control Plane | **Funcionando** — verificado no ar |
| Auditoria | Gravando |
| `HTTPExecutor` | **Presente e credenciado** — a remover |
| `/operations/history` | 500 — a tela do console segue fora do menu |

---

## Próximo passo

**[Parte 9 — Insight Gateway](09-insight-gateway.md)**: o plano de
produto, e o que ele deixou de ser responsável.
