# Parte 11 — Insight Sport Hub

> **Papel em uma frase:** recebe eventos esportivos brutos de vários
> provedores e produz **um** evento canônico — com o rastro de quem
> disse o quê preservado byte a byte.
>
> **Repositório:** `backend_services/insight-sport-hub`
> **Linguagem:** Go · **Arquitetura:** hexagonal estrita
> **Portas:** 8080 (HTTP) · 9080 (gRPC Operations)
> **Tamanho:** ~19.152 linhas · **Onde roda:** Robozão

---

## 1. O problema que ele resolve

Três provedores dizem que o gol foi aos 34, aos 35 e aos 34 minutos. Qual
é a verdade da plataforma?

Responder "o de maior prioridade" é fácil e errado — apaga a informação
de que houve divergência. O Sport Hub responde de outro jeito:

- **Nenhum evento bruto é a verdade.** `RawSportsEvent` é *uma
  observação*, imutável.
- **A verdade é derivada.** `CanonicalSportsEvent` é o consenso de N
  brutos que compartilham a mesma `Identity`.
- **A divergência é um estado**, não um erro: `conflicting` fica ao lado
  de `confirmed`.

```
Provedor A ─┐
Provedor B ─┼─► Raw (imutável) ─► validação ─► conflito ─► confiança ─► Canonical
Provedor C ─┘                                                              │
                                                                    lineage: quem
                                                                    contribuiu
```

---

## 2. A `Identity` — a chave que faz o resto funcionar

```
Identity = (sport, competition_id, match_id, event_type)
```

É a chave natural que diz "estes três eventos brutos falam da mesma
coisa". Todo o pipeline depende dela: sem `Identity`, canonicalizar seria
adivinhação.

E os estados possíveis do canônico:

```
candidate | confirmed | conflicting | rejected | stale
```

`stale` é o mais fácil de esquecer ao implementar: um evento que era
verdade e deixou de ser (o provedor corrigiu). Sem esse estado, dado
velho fica indistinguível de dado atual.

---

## 3. A regra arquitetural mais forte: linhagem nunca se perde

Do README, e vale citar inteiro:

> *"Every `RawSportsEvent` and every `CanonicalSportsEvent` carries the
> **complete** `SourceRef`. The Hub never flattens, simplifies or
> discards SourceRef fields."*

E existe teste para isso:

```go
TestSourceRefSurvivesAllPipelineHops
```

Ele afirma que **todo campo** — inclusive `adapter_version` e
`metadata` — sobrevive à ida e volta normalizer → canonicalização
**byte a byte**.

### Por que isso merece um teste dedicado

Achatar `SourceRef` é a otimização mais natural do mundo: são muitos
campos, a maioria não é lida no caminho quente, e "guardar só o
`source_id`" parece equivalente. Não é. Quando um provedor começa a
mandar dado errado, `adapter_version` é o que responde *desde quando* —
e sem ele a resposta é "não dá para saber".

A perda de linhagem é silenciosa e irreversível: o dado já foi gravado
sem o campo. Um teste é o único jeito de impedir que uma refatoração
razoável a cause.

No Postgres, isso vira JSONB: coluna `source` em `raw_sports_events` e
array `sources` em `canonical_sports_events`.

---

## 4. As duas políticas plugáveis

Duas decisões do pipeline são intencionalmente substituíveis:

| Serviço | Padrão | Por que é plugável |
|---|---|---|
| `ConflictDetectionService` | `FieldEqualityStrategy` | Igualdade de campo é ingênua para números (34 vs 35 minutos); estratégias com tolerância virão |
| `ConfidenceService` | `WeightedAveragePolicy` — `Σ(peso × conf) / Σ(peso)` | O peso por fonte é calibração, não arquitetura |

O padrão é o **mais simples que funciona**, com o ponto de extensão já
declarado. É o oposto de escrever a política sofisticada antes de ter
dado real para calibrá-la.

---

## 5. Quarentena, não descarte

Oito regras de validação, cada uma com um slug legível:

```
missing_source              unknown_competition
missing_timestamp           empty_payload
unsupported_sport           duplicate_raw_event_id
confidence_out_of_range     future_event_beyond_budget
```

Dois detalhes que valem a leitura:

**`unsupported_sport`** — na V1, só futebol. O parser recusa o resto em
vez de aceitar e quebrar adiante.

**`future_event_beyond_budget`** — evento no futuro é quase sempre
relógio dessincronizado, não notícia. O orçamento é configurável
(`VALIDATION_FUTURE_SKEW_SECONDS`), porque a tolerância certa depende do
provedor.

E a regra de evolução:

> *"Additive only — Sprint 2+ appends new `QuarantineReason` constants
> without renaming existing ones."*

Renomear um slug quebra todo dashboard, alerta e consulta que já
referenciava o nome antigo. Só somar é a disciplina que mantém isso
estável.

---

## 6. Os três streams de publicação

| Stream | Recebe |
|---|---|
| `insight:stream:events:match` | `match.*` |
| `insight:stream:events:odds` | `odds.*` |
| `insight:stream:events:context` | todo o resto |

Separar odds de eventos de partida importa porque as taxas são muito
diferentes: odds mudam continuamente, gols não. Num stream único, o
volume de odds afogaria os eventos raros — que são justamente os que
importam.

---

## 7. Estado atual — no ar, e ocioso

```
$ curl http://insight-sport-hub:8080/healthz
{"status":"ok"}   200
```

Mas o log do boot conta o resto:

```json
{"event":"redis_connected","stream":"insight:queue:syncjobs",
 "group":"insight-syncjob-workers"}
{"event":"queue_backend_initialised","backend":"redis"}
{"event":"scheduler_inactive_no_providers_configured"}   ← aqui
{"event":"redis_claimer_started","min_idle":30000,"max_deliveries":8}
{"event":"http_listen","addr":":8080"}
{"event":"operations_grpc_listen","addr":":9080"}
```

**`scheduler_inactive_no_providers_configured`.** O Sport Hub está de pé,
conectado ao Redis, com claimer ativo e gRPC Operations respondendo — e
**nenhum provedor configurado**. Ele não coleta nada porque não há de
onde.

Isso é exatamente o que se quer de um log de boot: o serviço não fingiu
estar trabalhando, e a razão de estar ocioso está em uma linha, no nível
`warn`, no primeiro segundo de vida.

| Item | Estado |
|---|---|
| Imagem | `konohalabs/insight-sport-hub:0.0.3`, `healthy` |
| HTTP / gRPC Operations | 8080 e 9080 respondendo |
| Registrado no Node Agent | Sim (`sport-hub`) |
| Provedores configurados | **Nenhum** — scheduler inativo |
| Eventos processados | 0 |
| Telas no console | Nenhuma |

> **Relação com o Explorer.** Os dois coletam dado externo, e a
> diferença é o propósito: o Explorer descobre e normaliza dado para o
> **lake analítico**; o Sport Hub orquestra a **fonte da verdade
> operacional** com consenso entre provedores. Não são duplicados — mas
> a fronteira merece revisão quando ambos tiverem provedores reais.

---

## Próximo passo

**[Parte 12 — Infraestrutura do Robozão](12-infraestrutura-robozao.md)**:
Docker, nginx, Swarm e como se chega em tudo isso.
