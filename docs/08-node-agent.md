# Parte 8 — Node Agent (Robozão)

> **Papel em uma frase:** é o agente da **máquina** — reporta o estado
> do nó, agrega a saúde dos serviços por gRPC e mantém o registro
> operacional local.
>
> **Repositório:** `backend_services/insight-robozao-gateway`
> **Linguagem:** Go · **Porta:** 8095 · **Persistência:** PostgreSQL
> **Tamanho:** ~3.500 linhas

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

Guarde essa frase. A seção 6 conta como o código passou a cumpri-la —
até a Fase C ele não cumpria.

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
		permissions := splitPermissions(r.Header.Get("X-Operator-Permissions"))
		if len(permissions) == 0 {
			writeJSON(w, http.StatusForbidden,
				map[string]string{"detail": "missing_operator_permissions"})
			return controlplane.Operator{}, false
		}
		return controlplane.Operator{
			ID:          r.Header.Get("X-Operator-Id"),
			Username:    r.Header.Get("X-Operator"),
			Role:        r.Header.Get("X-Operator-Role"),
			Permissions: permissions,
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

## 6. O `HTTPExecutor` — removido (Fase C)

Esta era a pendência que contradizia o documento de arquitetura de forma
direta. Foi fechada.

### O que existia

`internal/operations/commands.go` tinha um executor que fazia chamadas
HTTP autenticadas para o Explorer **e para o Gateway da nuvem**:

```go
type HTTPExecutor struct {
	ExplorerURL   string
	ExplorerToken string
	GatewayURL    string
	GatewayToken  string
	Client        *http.Client
}
```

Treze ações no catálogo, das quais **nove** eram encaminhamento:
`explorer.pipeline.pause/resume`, `explorer.job.retry`,
`platform.dlq.replay`, `identity.session.revoke`, `social.agent.*`,
`social.content.*`.

Isso é proxy HTTP — o que o `insight-context.md` v2.0 diz que o Node
Agent **nunca deve oferecer**.

### Por que era um problema concreto

1. **Duplicava autoridade.** O Control Plane já tem classificadores de
   path com allow-list default-deny. O `HTTPExecutor` era um segundo
   caminho até os mesmos serviços, com regras próprias escritas num
   `switch`.
2. **Espalhava credencial.** Os tokens do Explorer e do Gateway existiam
   em dois lugares. A Fase B tinha acabado de concentrá-los.
3. **`identity.session.revoke` é ação de identidade** — que pertence ao
   Control Plane por definição.

### O que a remoção encontrou pelo caminho

Duas coisas que só apareceram ao olhar de perto:

**Nenhum comando jamais rodou.** `select count(*) from
public.operations_commands` devolvia zero. As nove ações de proxy
estavam bloqueadas pelo `GATEWAY_OPS_TOKEN` ser o literal
`__required__` — todas dariam 401.

**As quatro ações de incidente não tinham executor.** Elas estavam no
catálogo, e o `HTTPExecutor` não tinha `case` para nenhuma: caíam no
`default: ErrExecutorUnavailable`. Criar uma era aceito e então falhava.

> Anunciar uma ação que ninguém consegue rodar é pior do que não
> anunciar. O catálogo prometia treze coisas e entregava zero.

### O que ficou no lugar

`internal/operations/executor.go` — um `LocalExecutor` que faz o que o
Node Agent legitimamente pode fazer: **incidentes**. São estado local
do nó, linhas num banco que este serviço é dono, descrevendo o que está
acontecendo nesta máquina. Nada é encaminhado a lugar nenhum.

O catálogo caiu de 13 para 4 ações, e as quatro **funcionam**:

```
POST /console/api/v1/control/operations
  {"action_id":"operations.incident.create", ...}
    → status: succeeded
    → result: {"incident_id":"8eed370b...","status":"open"}
```

As nove capacidades foram para o Control Plane, que já tem token,
allow-list de path e espinha de auditoria. O prefixo
`/v1/internal/operations/` entrou em `gateway-path-policy.ts`. **Elas
seguem bloqueadas** pelo mesmo `ADMIN_API_INTERNAL_TOKEN` placeholder
que mantém as telas de Social fora do menu — a rota existe para a
capacidade ter casa, e passa a funcionar quando o token for preenchido,
sem mudança de código.

### O que impede a volta

`internal/operations/no_proxy_test.go`, com três verificações:

| Teste | O que impede |
|---|---|
| `TestOperationsPackageBuildsNoHTTPClient` | Um `http.Client` no pacote de comandos |
| `TestNoUpstreamServiceCredentialsAreRead` | As quatro variáveis voltarem |
| `TestActionCatalogHoldsOnlyNodeLocalActions` | Uma ação de proxy voltar pelo JSON |

Verificados falhando com o proxy reintroduzido. E o segundo casa
**literais de string na AST**, não texto cru — um comentário explicando
que as variáveis foram removidas é documentação, e um checador que
falha na própria explicação é apagado em vez de obedecido.

> O gRPC de saída **fica**. Agregar saúde de serviços registrados não é
> o que a regra proíbe: é contrato tipado, registry declarado, e não
> carrega autoridade de operador junto. A forma proibida é a chamada
> HTTP autenticada que age **por** alguém.

---

## 6.1 O console também falava direto com o Node Agent

Descoberto ao verificar a Fase C no ar: `lib/robozao.ts`, no console,
tinha o endereço do Node Agent embutido.

```typescript
const ROBOZAO_GATEWAY_URL =
  process.env.ROBOZAO_GATEWAY_URL ?? "http://robozao-gateway:8095";
```

Sete rotas de API usavam. Era o último adapter direto vivo depois que a
Fase B moveu os outros doze.

**Por que passou despercebido.** Ele encaminhava a sessão do próprio
operador, não uma credencial de serviço — então a checagem usual
("o console tem token desse serviço?") respondia não. Ele guardava o
**endereço**. E um default compilado é uma rota: remover a variável do
deploy não mudava nada, e o ambiente limpo do container fazia o console
**parecer** isolado.

Hoje passa pelo Control Plane (`/node-agent/*`), com allow-list própria
em `node-agent-path-policy.ts`. O teste
`tests/no-direct-service-access.test.ts` procura **endereços**, não
credenciais — e distingue um host dentro de uma URL de um mesmo nome
usado como identificador de serviço no registry, que é dado legítimo.

---

## 6.2 As permissões não viajavam

Ao ligar o caminho novo, todo comando devolvia **403**.

`authenticateCaller` montava o operador a partir dos headers do Control
Plane — id, username, papel — e **não as permissões**. `op.Permissions`
chegava `nil` em `CreateCommand`, que exige `incident.manage`.

> A identidade passava e a autorização não. A recusa lia-se como "este
> operador não pode" quando, na verdade, ninguém tinha perguntado.

Corrigido nos dois lados, com a mesma divisão do Nexus: o Control Plane
resolve papel → permissão e envia `X-Operator-Permissions`; o Node Agent
decide o que as **próprias** rotas exigem. Header ausente **nega** —
derivar do papel aqui bifurcaria a tabela de RBAC, e assumir "sem header
= pode tudo" transformaria um esquecimento em autoridade ilimitada.

---

## 6.3 Uma coerção silenciosa de severidade

Também encontrada no teste ponta a ponta: criar um incidente com
`"severity": "warning"` gravava **ERROR**.

As constantes são maiúsculas (`WARNING`), a validação era
`if !severity.Valid() { severity = SevError }`, e a palavra certa com o
caso errado virava a severidade mais alta.

Escalar o aviso de alguém para erro é pior que recusar: a recusa é
visível e corrigível, a escalação aciona quem está de plantão por um
problema que ninguém reportou. Hoje o caso é normalizado e um valor
irreconhecível é recusado; vazio ainda usa o padrão, porque aí ninguém
pediu nada.

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

`EXPLORER_URL`, `EXPLORER_OPS_TOKEN`, `GATEWAY_OPS_URL` e
`GATEWAY_OPS_TOKEN` **foram removidas** com o `HTTPExecutor` (seção 6).
O container em execução não tem nenhuma credencial de outro serviço —
só os endereços gRPC do registry, que não são credenciais.

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
| Imagem | `konohalabs/insight-robozao-gateway:0.2.2`, `healthy` |
| Serviços no registro | 5 — atlas, explorer, nexus, sport-hub, qwen |
| Auth via Control Plane | Funcionando, com permissões |
| `HTTPExecutor` | **Removido** — com teste de fronteira |
| Credenciais de outro serviço | **Zero** |
| Ações no catálogo | 4, todas com executor real e verificadas no ar |
| Console → Node Agent | **Pelo Control Plane** |
| `/operations/history` | **200** — voltou a funcionar |

---

## Próximo passo

**[Parte 9 — Insight Gateway](09-insight-gateway.md)**: o plano de
produto, e o que ele deixou de ser responsável.
