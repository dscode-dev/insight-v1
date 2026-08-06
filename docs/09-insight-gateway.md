# Parte 9 — Insight Gateway

> **Papel em uma frase:** é a porta de entrada pública da plataforma —
> autenticação de usuário final, BFF do app e SSE de tempo real.
>
> **Repositório:** `backend_services/insight-gateway`
> **Linguagem:** Go · **Arquitetura:** hexagonal · **Roteador:** chi
> **Tamanho:** ~17.812 linhas — o maior serviço da plataforma
> **Onde roda:** Google Cloud, em `https://insight-api.konohalabs.com.br`

---

## 1. Leia isto antes: o que ele deixou de ser

O Gateway é o serviço mais antigo e o que mais mudou de escopo. Segundo
o `insight-context.md` v2.0, ele **não é responsável por**:

- administração da plataforma
- operadores
- o console
- auditoria administrativa

Tudo isso migrou para o Control Plane ([Parte 6](06-insight-control-plane.md)).

Só que o código ainda tem as rotas:

```
POST /v1/operator/auth/login
GET  /v1/operator/auth/me
POST /v1/operator/auth/refresh
POST /v1/operator/auth/logout
GET  /v1/console/admin/operators
GET  /v1/console/audit
POST /v1/console/identity/delegations
…
```

Elas são o **modelo antigo**, ainda presente porque dois serviços
continuam dependendo delas — o Nexus ([Parte 5](05-insight-nexus.md),
seção 6.1) e o fallback legado do Node Agent
([Parte 8](08-node-agent.md), seção 3).

> **Regra para trabalho novo:** nada que seja administrativo entra aqui.
> Se a pergunta é "quem é este operador e o que ele pode fazer", a
> resposta vem do Control Plane. O `/v1/operator/*` do Gateway é
> superfície a ser desligada, não estendida.

---

## 2. O que ele legitimamente é

O Gateway atende o **usuário final** — o app, não o operador.

### 2.1 Autenticação por OTP (telefone)

```
POST /v1/auth/phone/request
POST /v1/auth/phone/verify
POST /v1/auth/logout
```

A cadeia completa vive em `internal/infrastructure/`: normalização E.164
(`phone/`), geração de código + hash HMAC (`otp/`), janela de reenvio em
Redis (`redis/`), provedores de SMS (`sms/` — Null, Zenvia, Twilio) e
emissão de JWT (`jwt/`).

O provedor `Null` merece nota: permite exercitar o fluxo inteiro sem
gastar SMS, e é o padrão em desenvolvimento.

### 2.2 BFF do app

Endpoints que existem para o cliente móvel, não para o domínio:

| Área | Rotas |
|---|---|
| Busca | `/v1/search/{all,users,posts,agents,communities,matches,competitions,history,capabilities}` |
| Comunidades | `/v1/hub/communities/{id}` + membros, discussões, join |
| Discussões | `/v1/discussions/{id}` + mensagens, reações |
| Notificações | `/v1/notifications`, `/unread-count`, `/{id}/read`, `/read-all` |
| Perfil | `/v1/users/me/preferences`, `/me/avatar`, `/{id}/block` |
| Competições | `/v1/competitions/highlights` |
| Denúncias | `POST /v1/reports` |

BFF significa: essas rotas **compõem** respostas de vários domínios para
economizar round-trip do celular. Elas não são o domínio — o dono do
dado continua sendo o Social ou o Sport Hub, alcançados por gRPC.

### 2.3 SSE de tempo real

```
GET /v1/realtime/sse
GET /v1/events/stream
```

O `RealtimeBroker` lê **as 8 partições** do stream derivado do Redis e
faz fan-out para os assinantes:

> *"fans out to subscribers via per-connection channels with
> non-blocking sends + drop-on-full metrics."*

Duas escolhas dentro dessa frase:

**Envio não-bloqueante.** Um cliente lento não pode segurar o broker.
Sem isso, um celular em rede ruim degrada o tempo real de todo mundo.

**Métrica de descarte.** Descartar é a decisão certa, mas descartar em
silêncio é como se cria um mistério de "às vezes some evento". A métrica
transforma isso em número observável.

E uma restrição do protocolo que aparece no código:

> *"JWT access_token in query string (EventSource constraint)."*

A API `EventSource` do navegador **não deixa** definir cabeçalhos. Token
em query string é geralmente má prática — aqui é a única opção, e está
documentada como tal em vez de parecer descuido.

---

## 3. O Strangler — e por que ele ainda existe

O Gateway nasceu como **proxy strangler** na frente de um backend
legado. Hoje roda em modo standalone:

> *"Runs STANDALONE by default (consolidated platform): every route is
> served by native Go handlers and unmatched paths return 404. The
> original Strangler proxy machinery survives behind
> `LEGACY_UPSTREAM_BASE_URL` for overlap deployments only."*

O mecanismo é uma variável só:

- `LEGACY_UPSTREAM_BASE_URL` **vazio** → rota não casada devolve 404
- **preenchido** → rota não casada vai para o upstream legado

E cada rota nativa é registrada explicitamente:

```go
strangler.Native(http.MethodPost, "/v1/auth/phone/request", handler)
```

Em standalone as flags de rollout ficam inertes — os handlers nativos
servem 100% do tráfego. Com upstream legado configurado, virar uma flag
para `shadow` / `10` / `100` é a alavanca de corte por endpoint.

> **Por que manter isso.** É a diferença entre "migramos e torcemos" e
> "migramos podendo voltar em uma variável de ambiente". O custo é o
> código do strangler parado; o benefício é reversibilidade.

---

## 4. Ordem de boot — fail-fast declarado

```go
//  1. Load + validate config (fail fast on missing required env).
//  2. Init logger + tracer.
//  3. Connect Postgres + Redis (Ping at boot — fail fast if down).
//  4. Build auth dependencies …
//  5. Compose the application Service.
//  6. Build the router …
//  7. Mount middleware chain + start HTTP server.
//  8. Block on SIGINT/SIGTERM, then graceful shutdown.
```

Os passos 1 e 3 são a decisão que importa: **`Ping` no boot**. Um
serviço que sobe com banco fora do ar e só falha no primeiro request
reporta `healthy` enquanto está quebrado — foi exatamente o que
aconteceu com o Postgres do Robozão
([Parte 13](13-deploy-e-migrations.md)), onde um `pg_isready` mentiu por
dias.

---

## 5. O que o Control Plane consome daqui

Do Robozão, o único caminho até o Gateway passa pelo Control Plane, com
allow-list própria (`src/product-plane/gateway-path-policy.ts`):

```
Console → Control Plane → https://insight-api.konohalabs.com.br
                           /v1/admin/moderation/*
                           /v1/console/admin/*
                           /v1/admin/users/{id}/legal
```

Note que o Control Plane consome o Gateway como **fonte de dados de
produto** (moderação, usuários do app), não como autoridade de
identidade. A distinção é toda a correção da Fase B.

---

## 6. Por que 12 telas do console estão fora do menu

O Gateway está **no ar e saudável**:

```
$ curl -o /dev/null -w '%{http_code}' https://insight-api.konohalabs.com.br/healthz
200
$ curl -o /dev/null -w '%{http_code}' .../v1/operator/auth/me
401     ← correto: sem token
```

O bloqueio não é o Gateway. É o `.env` do Robozão:

```
ADMIN_API_BASE_URL=https://insight-api.konohalabs.com.br/v1
ADMIN_API_INTERNAL_TOKEN=__required__      ← placeholder
GATEWAY_OPS_URL=https://insight-api.konohalabs.com.br
GATEWAY_OPS_TOKEN=__required__             ← placeholder
```

`__required__` é literal — o valor real nunca foi preenchido. Toda
chamada do Control Plane ao Gateway sai com esse token e volta **401**.

É isso, e só isso, que mantém as 10 telas de Social, a de moderação e a
de usuários fora do menu do console
([Parte 7](07-insight-console.md), seção 5).

> **Para restaurá-las:** obtenha os dois tokens no ambiente do Gateway,
> substitua no `.env` do Robozão, reinicie o `insight-console-api` e
> remova as entradas correspondentes de `REMOVED_FROM_NAV`. Nenhum
> código precisa mudar — as telas continuam lá.

---

## 7. Arquitetura interna

Hexagonal, como o Nexus. A superfície pública é só `cmd/gateway/main.go`:

```
internal/
├── config/            Settings tipadas, vindas de env
├── domain/            auth (Credential, OtpChallenge), moderation
├── application/       casos de uso
├── infrastructure/    postgres, redis, jwt, otp, phone, sms,
│                      socialclient (gRPC), avatarstore
├── realtime/          Broker + filtros do SSE
└── interfaces/
    ├── proxy/         o strangler (chi router + flags)
    └── http/          16 módulos de handler
```

Existe `tests/architecture/` — os mesmos testes de fronteira que o Nexus
tem, impedindo que um import quebre a direção das dependências.

O deploy tem manifestos Kubernetes (`k8s/base` + overlays `local-lab` e
`production`), incluindo Job de migração. É o único serviço da
plataforma com esse nível de empacotamento — coerente com ser o único
que roda no Google Cloud.

---

## 8. Estado atual

| Item | Estado |
|---|---|
| Serviço | **No ar** no Google Cloud, `/healthz` 200 |
| Modo | Standalone (sem upstream legado) |
| Auth de usuário final | Funcionando |
| SSE | Implementado, 8 partições |
| `/v1/operator/*` | Presente — **superfície legada**, a desligar |
| Consumo pelo Control Plane | **Bloqueado** — tokens `__required__` |
| BFFs do W1.4 | 404 — dependem de W2/W4 por gRPC |

---

## Próximo passo

**[Parte 10 — Insight Social](10-insight-social.md)**: o domínio da rede
social, dono do dado que o Gateway compõe.
