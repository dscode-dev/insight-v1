# Parte 10 — Insight Social

> **Papel em uma frase:** é o dono do domínio social — usuários,
> comunidades, discussões, posts, reações, reputação. Fala gRPC, não
> HTTP público.
>
> **Repositório:** `backend_services/insight-social`
> **Linguagem:** Go · **Arquitetura:** hexagonal · **Transporte:** gRPC (`social.v1`)
> **Tamanho:** ~14.203 linhas · **Onde roda:** Google Cloud

---

## 1. O que "dono do domínio" significa aqui

O Gateway ([Parte 9](09-insight-gateway.md)) tem rotas de comunidades, de
discussões, de busca. Isso pode dar a impressão de que ele é dono desse
dado. Não é.

```
App ──HTTP──► Gateway ──gRPC──► Social ──► Postgres (insight_social)
              (BFF: compõe)      (decide, valida, persiste)
```

O Gateway **compõe** — junta respostas de vários domínios numa só
para economizar round-trip do celular. O Social **decide** — o que é uma
comunidade válida, quem pode postar, como reputação é calculada.

A distinção tem uma consequência prática: regra de negócio social que
vira código no Gateway está no lugar errado, mesmo funcionando.

---

## 2. Doze agregados

O Social registra doze serviços gRPC:

```go
RegisterUserServiceServer          RegisterPostServiceServer
RegisterCommunityServiceServer     RegisterReactionServiceServer
RegisterDiscussionServiceServer    RegisterFeedServiceServer
RegisterSignalServiceServer        RegisterNotificationServiceServer
RegisterSentimentServiceServer     RegisterAgentServiceServer
RegisterRelationshipServiceServer  RegisterReputationServiceServer
```

Dois merecem explicação, porque não são óbvios pelo nome:

**`SignalService`** — sinais **humanos**. É a contraparte social dos
sinais que o Atlas calcula: um usuário marcando que algo está
acontecendo. É o dado que a tabela `human_signals` do Anvil
([Parte 4](04-insight-anvil.md)) foi criada para receber — e que, hoje,
nada escreve. As duas pontas existem; a ligação não.

**`AgentService`** — os agentes de IA do Nexus
([Parte 5](05-insight-nexus.md)) publicam **como usuários**. Eles têm
perfil, seguidores e posts, atravessando o mesmo domínio social que uma
pessoa. Por isso o Nexus publica no Social por gRPC em vez de escrever
direto no banco: as regras de reputação e moderação valem igual para
agente e para gente.

---

## 3. O README está desatualizado — e isso é útil saber

O `README.md` do serviço descreve o estado **W2.0**:

> *"The service boots, registers all 7 services as `Unimplemented`
> stubs… What's **not** here yet: every aggregate's real
> implementation."*

O código diz outra coisa. `internal/domain/` tem **quatorze** pacotes
(`user`, `community`, `discussion`, `post`, `reaction`, `feed`,
`notification`, `agent`, `signal`, `sentiment`, `relationship`,
`reputation`, `search`, `preferences`), e `internal/interfaces/grpc/`
tem um arquivo de implementação para cada um.

O arquivo `stubs.go` ainda existe, mas ao lado das implementações reais.

> **Regra ao ler qualquer README deste monorepo:** eles descrevem o
> sprint em que foram escritos. Quando README e código divergem, **o
> código está certo** — é a mesma regra do índice desta apostila.

---

## 4. A superfície HTTP que existe apesar do gRPC

O Social é "exclusivamente gRPC" no papel, mas tem
`internal/interfaces/httpapi/`:

```
competitions.go                    me_profile.go
console_social.go                  search.go
console_social_agent_state.go      sports_profile.go
console_social_investigation.go    interactions.go
```

Os três `console_social*` são a razão pela qual as telas de Social do
console existiam. Eles servem **investigação** — ver o estado de um
agente, rastrear uma denúncia — que é leitura administrativa, não
tráfego de app.

Essa é também a superfície bloqueada hoje: o caminho até ela é
`Console → Control Plane → Gateway → Social`, e o `ADMIN_API_INTERNAL_TOKEN`
é o placeholder `__required__` ([Parte 9](09-insight-gateway.md), seção 6).

---

## 5. O banco compartilhado, e por que era temporário

O diagrama do README mostra algo incomum:

```
insight-social ──┐
                 ├──► mesmo Postgres (insight_social)
plaza-py    ─────┘   (legado, congelado)
```

Dois serviços no mesmo banco é normalmente um erro de arquitetura — dois
donos para o mesmo dado. Aqui foi **deliberado e temporário**: o padrão
strangler exige que o serviço novo e o legado enxerguem o mesmo estado
durante a virada, senão cada request cai numa realidade diferente.

O que tornava isso seguro era o `plaza-py` estar **congelado**. Um
legado que ainda recebe features com banco compartilhado não é
strangler, é dois serviços brigando.

O `plaza-py` está aposentado — e o console tem um verificador que
impede seu retorno:

```javascript
const LEGACY = ["playmaker", "pundit", "atrium", "plaza", "insight-magnus"];
```

---

## 6. Estado atual

| Item | Estado |
|---|---|
| Onde roda | Google Cloud — **não** faz parte da stack do Robozão |
| Alcançável do Robozão | Só via Gateway, e o token é placeholder |
| Agregados implementados | 12 serviços gRPC, 14 pacotes de domínio |
| Telas no console | 10 preservadas, **todas fora do menu** (401) |
| `human_signals` no Anvil | Tabela existe, **nada escreve** |

O Social é o serviço menos exercitado por este trabalho — a plataforma
de inteligência (Explorer, Atlas, Anvil) foi a prioridade, e o Social é
o outro plano. Nada aqui foi revisado com a profundidade das Partes 2–4,
e a documentação não deve sugerir que foi.

---

## Próximo passo

**[Parte 11 — Insight Sport Hub](11-insight-sport-hub.md)**: a
orquestração da fonte da verdade esportiva.
