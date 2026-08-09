# Parte 1 — Conceitos e fluxos ponta a ponta

Esta parte dá o vocabulário. Os termos abaixo aparecem em nomes de
classe, de tabela e de variável no código inteiro — sem eles, a leitura
dos serviços fica em tradução simultânea.

---

## 1. Vocabulário

### Operador

Uma pessoa que administra a plataforma. **Não é um usuário do
aplicativo.** São populações separadas, em bancos separados, com
autenticação separada. Um operador vive na tabela
`control_plane.operators`; um usuário do app vive no Social.

### Operational Identity

A identidade **sob a qual uma ação é autorada**. Normalmente é o próprio
operador, mas pode diferir quando há delegação (agir em nome de uma
identidade oficial ou de um agente).

O ponto importante: ela é **resultado de resolução no servidor**, nunca
algo que o navegador informa. No código isso aparece assim:

```typescript
// lib/control-plane/security/operator-context.ts
export interface OperatorContext {
  readonly operatorId: string;      // quem é a pessoa
  readonly identityId: string;      // sob qual identidade ela age
  readonly identityKind: "operator" | "official_identity" | "agent";
  readonly sessionId: string;       // sha256(token) — não é o token
  // ...
}
```

`sessionId` é o **hash** do token, não o token. Isso permite logar e
correlacionar uma sessão sem que o log carregue uma credencial viva.

### Capability

Um identificador no formato `domain.resource.action` — por exemplo
`atlas.replay.promote`. Descreve **o que existe**, não **quem pode**.

Essa distinção já custou um bug: a presença no registro de capabilities
é uma *pré-condição* para autorizar, não a autorização em si.

```typescript
// lib/control-plane/security/authorization.ts
// Registry presence is a precondition, NOT authorization.
if (!CapabilityRegistry.isValidId(capability)) {
  return decision({ ...base, allowed: false,
                    reasonCode: "denied_capability_unsupported" });
}
```

**Armadilha real:** uma capability declarada só no mapa `META` de
`capabilities.ts`, mas **não** listada em `svc.capabilities` de
`services.ts`, não vira descritor. `isValidId()` retorna falso e
**toda** decisão sobre ela é negada — parecendo falta de permissão do
operador. Existe um teste (`tests/governed-capabilities.test.ts`)
exatamente para impedir isso.

### Audit Spine

O registro durável de comandos administrativos. Toda mutação governada
emite dois eventos:

1. **intent** — a decisão de autorização (`AUTHORIZED` ou `DENIED`)
2. **outcome** — o que de fato aconteceu (`COMPLETED` ou `FAILED`)

E é **fail-closed**: se o intent não pôde ser gravado de forma durável,
a mutação **não acontece**.

```typescript
// app/api/v1/quality-gate/[...path]/route.ts
if (!intent.persisted) {
  throw new ConsoleApiError(503, "audit_unavailable", {
    upstreamCode: "audit_intent_not_durable",
  });
}
```

O motivo é direto: uma aprovação que existe no Atlas sem rastro no
console derrota a própria exigência de auditoria que motivou a tela.

### Quality Gate

O portão que valida mudanças no núcleo de inteligência do Atlas antes
de promovê-las. Roda um *replay* determinístico sobre dados históricos,
compara com uma *baseline congelada* e emite recomendações. **Aprovação
humana é obrigatória** — e isso é forçado no código, não só no
documento. Detalhes na [Parte 3](03-insight-atlas.md).

### Plano validado / lake

O Explorer grava em camadas: `raw` (resposta crua do provedor),
`normalized` e `validated`. Só a camada `validated` é autoritativa —
e é dela que o Atlas lê. Confundir as camadas já causou um bug de
produção (o watcher do Atlas apontava para a raiz do lake).

---

## 2. Fluxo do usuário final

```
Aplicativo
    │
    ▼
Insight Gateway ──── autentica o usuário, aplica rate limit
    │
    ▼
Insight Social ───── feed, posts, comentários, comunidades
```

Simples de propósito: o caminho quente do produto não deve depender da
camada de inteligência estar de pé.

---

## 3. Fluxo de inteligência — o coração da plataforma

Este é o fluxo que dá razão de existir ao projeto. Vale seguir com
calma.

```
   Provedores externos (ESPN, FBref, Football-Data, casas de odds)
        │
        ▼
   ┌──────────┐   coleta, normaliza, valida
   │ EXPLORER │   grava no lake: raw → normalized → validated
   └────┬─────┘
        │  lake validado (JSONL particionado)
        ▼
   ┌──────────┐   similaridade, memória vetorial, correlação,
   │  ATLAS   │   detecção de tendências, contexto
   └────┬─────┘
        │  publica eventos derivados
        │  Redis: insight:stream:derived:p0..p7
        ▼
   ┌──────────┐   consome o stream, grava em lote
   │  ANVIL   │   ClickHouse: market_snapshots, metric_ticks
   └────┬─────┘
        │  API de features (leitura estreita)
        ▼
   ┌──────────┐   agentes de IA leem o conhecimento
   │  NEXUS   │   e produzem posts para a rede social
   └──────────┘
```

### O detalhe que quase ninguém percebe

O Atlas **também** lê de volta do Anvil. Quando o Atlas monta o contexto
de uma partida, ele pede ao Anvil as features históricas daquele jogo:

```python
# atlas/clients/anvil_gateway.py
path = f"{self._prefix}/matches/{quote(str(match_id), safe='')}"
```

Ou seja, a seta Atlas → Anvil → Atlas é um ciclo, e ele é intencional:
o Atlas produz o histórico e depois o consulta para contextualizar o
presente.

---

## 4. Fluxo administrativo

```
Operador (navegador)
    │  cookie HttpOnly com o token de sessão
    ▼
Insight Console (Next.js)
    │  Bearer <token>  — e SÓ isso
    ▼
Insight Control Plane
    │  autentica a sessão → resolve o operador → autoriza → audita
    │
    ├──► Explorer   (X-Ops-Token + X-Operator)
    ├──► Atlas      (X-Internal-Token + X-Operator)
    ├──► Nexus
    ├──► Node Agent
    └──► Gateway da nuvem  (X-Internal-Token) → Social
```

Repare no que **não** existe nesse desenho: nenhuma seta saindo do
Console para outro serviço. Essa foi a maior correção arquitetural do
projeto, descrita na [Parte 6](06-insight-control-plane.md).

### A inversão que aconteceu

Antes, o Console autenticava operadores **no Gateway** (Product Plane) e
depois *afirmava* a identidade ao backend, assinando um envelope HMAC.
Isso invertia a autoridade: o Console decidia quem você era e o backend
acreditava.

Hoje o Console apenas **apresenta** o token de sessão, e o Control Plane
decide. Além de arquiteturalmente correto, isso removeu um round-trip —
resolver identidade só para poder assiná-la deixou de existir.

---

## 5. Como um dado vira um post — exemplo completo

Vale a pena traçar um caminho inteiro, porque ele cruza quase todos os
serviços:

1. **Sport Hub** recebe do provedor que o jogo `Flamengo x Vasco`
   começou e publica um `CanonicalSportsEvent` no Redis.
2. **Atlas** consome esse evento pelo `CanonicalConsumer`, atualiza o
   snapshot quente de features daquela partida.
3. Chegam odds. O Atlas grava em `atlas.odds_ticks` e recalcula estado
   de mercado.
4. O motor de tendências do Atlas roda: detecta, por exemplo, uma
   anomalia de mercado. Emite um `Trend` no stream
   `insight:stream:trends` e um evento derivado em
   `insight:stream:derived:pN`.
5. **Anvil** consome o derivado e grava em `market_snapshots` no
   ClickHouse — o histórico que amanhã servirá de feature.
6. **Nexus** lê o conhecimento do Atlas, e um agente de IA temático
   transforma isso num post.
7. O post vai para o **Social**, e o usuário vê no feed pelo
   **Gateway**.

Paralelamente, um **operador** pode abrir o **Console**, ver a tendência
detectada, inspecionar o Quality Gate e aprovar (ou rejeitar) a promoção
de uma mudança no detector que a gerou — tudo passando pelo **Control
Plane** e ficando registrado no Audit Spine.

---

## 6. Uma regra transversal: honestidade de estado

Aparece em vários lugares e é uma decisão consciente do projeto:
**nunca reportar saúde que não foi medida**.

```typescript
// lib/control-plane/snapshot.ts
// Absent ⇒ the Control Plane has no probe configured for it.
// Honestly unknown, NOT down: reporting a service as down
// because nobody looked is how a false incident starts.
resolved.set(id, { report: report ?? UNKNOWN_REPORT, source: platformR.source });
```

`unknown` é diferente de `unavailable`. Um serviço que ninguém sondou
não está fora do ar — está não observado. Confundir os dois gera
incidente falso, e um incidente falso custa a confiança no painel
inteiro.

---

## Próximo passo

Siga para a **[Parte 2 — Insight Explorer](02-insight-explorer.md)**,
o primeiro serviço da cadeia de inteligência.
