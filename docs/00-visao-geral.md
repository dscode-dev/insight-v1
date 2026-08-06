# Parte 0 — Visão geral e os dois planos

> Leia esta parte inteira antes de abrir qualquer código. Quase todo
> erro de arquitetura que já cometemos neste projeto veio de não saber
> em qual plano um serviço vive.

## O que é o Insight

Uma plataforma de inteligência esportiva focada em **futebol**. Ela pega
volumes grandes de dados brutos (jogos, odds, estatísticas), transforma
em informação estruturada e contextualizada, e entrega isso de duas
formas: para usuários finais, num aplicativo social; e para operadores,
num console administrativo.

Na V1 o escopo é deliberadamente restrito a cinco competições:
Brasileirão, Premier League, La Liga, Champions League e Libertadores.

## A regra que organiza tudo: dois planos

A plataforma é dividida em dois planos, e **nenhum serviço pertence aos
dois ao mesmo tempo**.

```
                          PRODUCT PLANE
              (infraestrutura pública — Google Cloud)
   ┌──────────────────────────────────────────────────────────┐
   │                                                          │
   │   Internet → Insight Gateway → Insight Social            │
   │                                                          │
   └──────────────────────────────────────────────────────────┘

                  INTELLIGENCE & CONTROL PLANE
                   (rede privada / VPN — Robozão)
   ┌──────────────────────────────────────────────────────────┐
   │                                                          │
   │   Operador → Insight Console → Insight Control Plane     │
   │                                      │                   │
   │                    ┌─────────────────┼─────────────────┐ │
   │                    ▼                 ▼                 ▼ │
   │              Explorer            Atlas             Nexus │
   │                    │                 │                   │
   │                    └────► Anvil ◄────┘                   │
   │                              │                           │
   │                         ClickHouse                       │
   │                                                          │
   │              Node Agent (Robozão) ◄── Control Plane      │
   └──────────────────────────────────────────────────────────┘
```

### Por que essa separação importa na prática

Não é organograma: é uma restrição que muda o código.

**O Product Plane nunca sabe que o Console existe.** O Gateway atende
o aplicativo. Ele não tem endpoint de operador, não tem tela
administrativa, não sabe o que é uma sessão de operador. Se você se
pegar adicionando "só um endpointzinho admin" no Gateway, parou —
aquilo é responsabilidade do Control Plane.

**O Console nunca fala direto com nenhum serviço.** Absolutamente tudo
passa pelo Control Plane. Isso tem consequência medível: hoje o
container do console tem exatamente uma variável de rede
(`CONSOLE_API_BASE_URL`) e **zero tokens de serviço**. Ele não tem como
chamar o Atlas mesmo que alguém escreva o código para isso — não existe
credencial nem rota.

Esse é o tipo de garantia que vale mais que uma regra escrita: um token
que não existe não vaza.

## Os serviços, um parágrafo cada

### Plano de Inteligência

| Serviço | Responsabilidade | Não é responsável por |
|---|---|---|
| **Explorer** | Descobrir dados externos: crawlers, coleta, normalização, pipelines históricos | IA, similaridade, publicação |
| **Atlas** | Motor de inteligência: similaridade, memória vetorial, correlação, contexto | Publicação, feed, APIs públicas |
| **Anvil** | Persistência analítica: consome eventos derivados do Atlas e grava no ClickHouse | Feed, social, inteligência |
| **Nexus** | Orquestra agentes de IA que transformam conhecimento do Atlas em posts | Similaridade, coleta |

### Plano de Controle

| Serviço | Responsabilidade |
|---|---|
| **Control Plane** (`insight-console-api`) | Autenticação administrativa, sessões de operador, RBAC, Operational Identity, Audit Spine, Capabilities, e encaminhamento de comandos aos serviços internos |
| **Console** (`insight-console`) | A interface. Só desenha e coleta intenção; toda regra está no backend |
| **Node Agent** (Robozão) | Representa a máquina física: health, CPU, memória, disco, containers, deploy controlado |

### Plano de Produto

| Serviço | Responsabilidade |
|---|---|
| **Gateway** | Ponto único de entrada das APIs públicas: autenticação de usuário, rate limiting, SSE, BFF do app |
| **Social** | A rede social: feed, posts, comentários, comunidades, moderação |
| **Sport Hub** | Ingestão dos provedores esportivos, publicando eventos canônicos |

## Onde cada coisa roda

Isso confunde muita gente, então: **os planos não são só lógicos, são
físicos.**

- **Product Plane** → Google Cloud, exposto à internet.
- **Intelligence & Control Plane** → o servidor **Robozão**, uma máquina
  Ubuntu rodando em WSL2 dentro de um Windows, atrás de rede privada.

A única exceção histórica: o **Anvil** aparece no documento de
arquitetura original dentro do Product Plane. Foi **movido** para o
Robozão depois, e por um motivo concreto: o Anvil consome o stream
`insight:stream:derived:p*` do Redis que o Atlas alimenta. Ficando ao
lado do Atlas, cada evento derivado deixa de atravessar a rede.

## Princípios que valem para todo serviço

1. **Uma responsabilidade principal por serviço.** Se você precisa
   explicar o que um serviço faz usando "e também", provavelmente ele
   está fazendo demais.
2. **Toda regra de negócio vive no backend.** O frontend consome
   contratos.
3. **Todo domínio é autoridade sobre os próprios dados.** O Control
   Plane não implementa regra do Atlas; ele autentica, autoriza, audita
   e **encaminha**.
4. **Todo comando administrativo é auditável.** Não é opcional: existe
   um Audit Spine e as mutações passam por ele.
5. **Comunicação interna prefere gRPC; pública usa HTTP.**

## Próximo passo

Siga para a **[Parte 1 — Conceitos e fluxos](01-conceitos-e-fluxos.md)**,
que apresenta o vocabulário do projeto (Operational Identity, Capability,
Audit Spine, Quality Gate) e mostra como um dado atravessa a plataforma
de ponta a ponta.
