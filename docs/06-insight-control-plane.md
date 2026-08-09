# Parte 6 — Insight Control Plane

> **Papel em uma frase:** é a autoridade administrativa do plano de
> inteligência — autentica operadores, autoriza, audita e encaminha
> comandos aos serviços internos.
>
> **Repositório:** `backend_services/insight-console-api`
> **Linguagem:** TypeScript · **Framework:** NestJS 11 + Fastify
> **Porta:** 3002 · **Persistência:** PostgreSQL (schema `control_plane`)

---

## 1. O nome confunde: leia isto primeiro

O diretório se chama `insight-console-api`, mas o serviço **é o Insight
Control Plane**. O nome ficou de quando ele era só um backend do
console; a responsabilidade cresceu.

Segundo o `insight-context.md` v2.0, ele responde por:

- Autenticação administrativa
- Sessões de operadores
- RBAC
- Operational Identity
- Delegation
- Audit Spine
- Capabilities
- Registries
- Orquestração administrativa e comunicação com os serviços internos

E **não** responde por: feed, usuários públicos, APIs mobile,
inteligência do Atlas, publicação social.

---

## 2. A regra de ouro

> **O Console fala só com o Control Plane. O Control Plane fala com
> todo o resto.**

Isso não é organograma. É verificável:

```
$ docker exec insight-console printenv | grep -E 'TOKEN|_URL|API'
CONSOLE_API_BASE_URL=http://insight-console-api:3002
```

**Uma variável de rede. Zero tokens de serviço.** O console não tem como
chamar o Atlas mesmo que alguém escreva o código — não existe
credencial nem rota. Essa é a garantia forte; a regra escrita seria a
fraca.

---

## 3. A inversão de autoridade que aconteceu

Vale entender, porque explica muito código.

### Antes (errado)

```
Console ──credenciais──► Insight Gateway (PRODUCT PLANE)
        ◄──sessão───────
Console ──envelope HMAC assinado──► console-api
```

O Console autenticava operadores **no Gateway público** e depois
*afirmava* a identidade ao backend, assinando um envelope HMAC.

Dois problemas:

1. **Colocava identidade administrativa no Product Plane** — o único
   lugar que o documento proíbe.
2. **Invertia a autoridade:** o Console decidia quem você era e o
   backend acreditava.

E havia um custo: para assinar, o Console precisava **primeiro** resolver
a identidade em algum lugar. Cada requisição custava uma resolução mais
a chamada que ela realmente queria.

### Depois (correto)

```
Console ──Bearer <token de sessão>──► Control Plane
                                       │ resolve, autoriza, audita
                                       ▼
                          Explorer · Atlas · Nexus · Node Agent · Gateway
```

O Console apenas **apresenta** o token do cookie. O Control Plane
decide. Um round-trip a menos, e a autoridade no lugar certo.

---

## 4. Identidade — como funciona

### Schema `control_plane` (migration `0001`)

```sql
CREATE TABLE control_plane.operators (
    id            UUID PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    role          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    ...
);
```

Schema próprio, ao lado de `atlas` e `nexus` no mesmo banco — cada
domínio é autoridade sobre os próprios dados.

### Senha: scrypt, não pgcrypto

O Gateway usava `crypt()` do pgcrypto. O Control Plane usa
`node:crypto` scrypt, e o motivo está no código:

```typescript
// src/identity/password.ts
// NOT pgcrypto's `crypt()` — the shape the Gateway used. Verifying in
// the database means the plaintext password travels inside a SQL
// statement, where it shows up in `pg_stat_activity` and in any
// statement logging that is ever switched on.
```

Formato `scrypt$N$r$p$salt$hash` — **autodescritivo**, para elevar o
custo depois sem invalidar as senhas existentes.

### Sessões

Token opaco de 32 bytes. **O token nunca é guardado** — só o
`sha256(token)`. Um vazamento do banco não entrega sessões vivas.

E a resolução é toda em SQL:

```sql
WHERE s.token_hash = $1
  AND s.revoked_at IS NULL
  AND s.expires_at > now()
  AND o.is_active = TRUE
```

Colocar expiração, revogação e o flag de ativo **na cláusula WHERE**, e
não em código, faz com que desativar um operador encerre as sessões dele
imediatamente.

### O cache e a única janela de obsolescência

`SessionCacheService` guarda a resolução por 30s. Como tudo acima é
verificado em SQL, **o TTL do cache é o único ponto onde uma revogação
pode ficar velha**.

Foi exatamente aí que surgiu um bug:

> **Logout não deslogava de verdade.** `revokeSession` atualizava o
> banco, mas o cache continuava respondendo por mais 30 segundos.
> Revogação e cache estavam corretos **isoladamente** — só o teste
> ponta a ponta mostrou. Hoje o `logout` também chama
> `sessions.invalidate(token)`.

### Não vaza se a conta existe

```typescript
if (row === null || !row.password_hash) {
  // Hash anyway, against a dummy digest, so a missing account does
  // not return measurably faster than a wrong password.
  await verifyPassword(password, DUMMY_HASH);
  return null;
}
```

Senha errada, usuário inexistente e conta desativada devolvem **a mesma
coisa, no mesmo tempo**. Diferenciá-los transforma o formulário de login
num oráculo de enumeração de contas.

---

## 5. Encaminhar não é fazer proxy

O Control Plane "encaminha comandos". Mas encaminhar **não** é ser um
proxy aberto. Todo path é classificado contra uma lista fechada, e o que
não é reconhecido é **recusado**.

```typescript
// src/data-intelligence/path-policy.ts
if (EXPLORER_ROOTS.has(firstSegment(path))) {
  return { kind: 'allow', upstream: 'explorer', path };
}
return { kind: 'refuse', reason: 'unknown_data_intelligence_path' };
```

Casa pelo **primeiro segmento**, não por prefixo de string —
`pipelinesX/secret` não é `pipelines`. E `..` é recusado
explicitamente: sairia do prefixo que a lista acabou de aprovar.

Três classificadores, cada um com default-deny:

| Arquivo | Cobre |
|---|---|
| `data-intelligence/path-policy.ts` | Explorer + Atlas |
| `product-plane/gateway-path-policy.ts` | Gateway da nuvem → Social |
| (no console) `explorer-ops-routing.ts` | Quais escritas são governadas |

---

## 6. O Audit Spine e o fail-closed

Mutações governadas seguem sempre a mesma espinha:

```
capability → authorize → audit(intent) → mutar → audit(outcome)
```

E se o intent não puder ser gravado de forma durável, **a mutação não
acontece**:

```typescript
if (!intent.persisted) {
  throw new ConsoleApiError(503, "audit_unavailable", {
    upstreamCode: "audit_intent_not_durable",
  });
}
```

Uma aprovação que existe no Atlas sem rastro no console derrota a
própria exigência de auditoria que motivou a tela.

E uma **recusa** do gate é registrada como outcome `FAILED` com o código
do próprio gate — não é exceção, é o sistema funcionando.

---

## 7. Os módulos

| Módulo | O que faz |
|---|---|
| `identity/` | Login, sessões, RBAC, o guard global |
| `db/` | Pool + runner de migrations |
| `platform/` | Saúde do plano de inteligência + Node Agent |
| `quality-gate/` | Replays e decisões de promoção do Atlas |
| `explorer-ops/` | Curadoria, jobs, qualidade, runtime |
| `data-intelligence/` | Encaminhamento Explorer + Atlas |
| `product-plane/` | Encaminhamento para o Gateway da nuvem |
| `realtime/` | Canais SSE |
| `upstream/` | Transporte HTTP tipado |

### Uma distinção forçada pelo tipo

```typescript
async taskAction(actor, action: 'start' | 'restart', competition, season)
async schedulerAction(actor, action: 'pause' | 'resume' | 'cancel')
```

Os cinco endpoints de job do Explorer **não** são cinco variantes da
mesma coisa: `start`/`restart` agem numa tarefa, `pause`/`resume`/
`cancel` agem no **scheduler inteiro**. Juntá-los é como um botão
"cancel" acaba renderizado ao lado de um job cancelando todos.

---

## 8. A armadilha que pegou três vezes

**O Nest resolve TODO parâmetro de construtor de um provider — inclusive
opcional ou com default.**

```typescript
constructor(private readonly fetcher: typeof fetch = fetch) {}
```

Isso lê como "o Nest vai pular, é só um seam de teste". Não é: o
container procura um provider daquele tipo, não acha, e **o processo
morre no boot**. Nem typecheck nem teste unitário pegam, porque ambos
constroem a classe diretamente.

Aconteceu com `UpstreamService` (`fetcher`), `SessionCacheService`
(`now`) e `DatabaseService` (`connectionString`) — as três vezes
descobertas **rodando o container**.

Duas formas legítimas:

- não ter o parâmetro; ou
- um provider `useFactory`, que constrói a classe explicitamente.

E existe teste para isso: `src/injectable-constructors.spec.ts` varre
todo `@Injectable`, isentando só o que um módulo provê via `useFactory`.

> **Lição geral:** para um serviço Nest, `docker run` na imagem e curl.
> Build e testes verdes **não são evidência de que ele sobe**.

---

## 9. Comandos operacionais

A imagem é enxuta e sem psql, então migrar e semear são comandos:

```bash
# aplica migrations/*.sql
docker compose run --rm control-plane-migrate

# cria o primeiro operador (idempotente)
docker compose --profile seed run --rm control-plane-seed
```

O seed fica atrás de `profiles: ["seed"]` de propósito: não sobe no
`docker compose up`, e as credenciais não ficam no ambiente de um
processo de vida longa.

Ele **não troca senha** de operador existente sem
`CONSOLE_SEED_RESET_PASSWORD=true` — um deploy que reescreve credencial
de admin em silêncio é forma de trancar gente fora, e deploy roda muito
mais vezes do que se espera.

---

## 10. Configuração

| Variável | Obrigatória | Observação |
|---|---|---|
| `CONTROL_PLANE_DATABASE_URL` | sim | Sem ela não autentica ninguém |
| `ROBOZAO_GATEWAY_URL` | sim | Node Agent |
| `NODE_AGENT_TOKEN` | sim | Segredo compartilhado com o Node Agent |
| `EXPLORER_OPS_TOKEN` | — | |
| `ATLAS_INTERNAL_TOKEN` | — | |
| `ADMIN_API_BASE_URL` / `_INTERNAL_TOKEN` | — | Gateway da nuvem |
| `SESSION_TTL_HOURS` | — | 8 |
| `SESSION_CACHE_TTL_SECONDS` | — | 30 — a janela de revogação |

**Todos os tokens de serviço da plataforma vivem aqui.** É o resultado
de mover o acesso: eles saíram do console.

---

## Próximo passo

**[Parte 7 — Insight Console](07-insight-console.md)**: a interface, e
por que ela é deliberadamente burra.
