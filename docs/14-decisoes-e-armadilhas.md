# Parte 14 — Decisões arquiteturais e armadilhas já pagas

> Esta parte não descreve um serviço. Ela reúne o que já custou caro,
> para que não custe de novo — e as decisões que explicam por que o
> código é como é.
>
> Cada item tem o **sintoma**, porque é assim que você vai reencontrá-lo.

---

## Parte A — As decisões

### A.1 Dois planos, e a autoridade fica no de controle

O Console fala **só** com o Control Plane. O Control Plane fala com todo
o resto.

Antes, o Console autenticava operadores no Gateway público e depois
*afirmava* a identidade ao backend, assinando um envelope HMAC. Dois
problemas: colocava identidade administrativa no Product Plane, e
invertia a autoridade — o Console decidia quem você era e o backend
acreditava.

A garantia forte não é a regra escrita, é a ausência de credencial:

```
$ docker exec insight-console printenv | grep TOKEN
(vazio)
```

**Detalhes:** [Parte 6](06-insight-control-plane.md), [Parte 7](07-insight-console.md)

### A.2 O Atlas é descritivo, nunca preditivo

O Atlas descreve o que está acontecendo. Ele não prevê resultado, não
recomenda aposta, não emite probabilidade de vitória.

Isso é contrato, não preferência — está no `ATLAS_V1_FROZEN.md` e
aparece como **guardrails** na tela de Conhecimento do console. Todos
bloqueados é o estado correto; qualquer um ativo significa que o
contrato foi violado.

**Detalhes:** [Parte 3](03-insight-atlas.md)

### A.3 Default-deny em toda fronteira

Não é um lugar só — é o mesmo padrão repetido em cinco camadas:

| Camada | Mecanismo |
|---|---|
| nginx | Três `location`; o resto é 404 |
| Control Plane | Allow-list de path por primeiro segmento |
| Console | Classificadores `governed \| ordinary \| refuse` |
| Node Agent | Ação precisa estar no catálogo **e** no executor |
| Sport Hub | Oito regras de quarentena antes de canonicalizar |

Uma allow-list curta é auditável de relance. Uma deny-list nunca está
completa.

### A.4 Falhar fechado, e dizer por quê

- Auditoria não durável ⇒ **a mutação não acontece** (503)
- Sem autoridade de identidade ⇒ **API trancada** (503, nomeando a variável)
- Cadeia de LLM esgotada ⇒ **ticket**, nunca texto genérico
- Path não classificado ⇒ **recusa**, não encaminhamento

E sempre com código legível: `audit_unavailable`,
`self_approval_forbidden`, `denied_capability_unsupported`. "Deu erro"
sem código é indistinguível de bug.

### A.5 `null` não é zero

Zero é uma **medição**. `null` é a **ausência** dela. A UI mostra "—".

Confundir os dois cria incidente falso — alguém investiga uma fonte que
nunca teve problema. Está aplicado em todas as telas reescritas.

### A.6 Strangler, com o caminho de volta

Serviço novo nasce ao lado do legado, ambos vendo o mesmo estado, e a
virada é uma variável de ambiente (`LEGACY_UPSTREAM_BASE_URL`). O custo
é código parado; o benefício é reversibilidade.

**Condição obrigatória:** o legado precisa estar **congelado**. Banco
compartilhado com legado que ainda recebe features não é strangler, são
dois serviços brigando.

---

## Parte B — As armadilhas

### B.1 Nest resolve todo parâmetro de construtor

**Sintoma:** o container morre no boot. Build, typecheck e testes verdes.

```typescript
constructor(private readonly fetcher: typeof fetch = fetch) {}
```

Parece um seam de teste que o Nest vai ignorar. Não vai: o container
procura um provider daquele tipo, não acha, e o processo morre. Testes
não pegam porque constroem a classe diretamente.

**Aconteceu 3 vezes.** Correção: remover o parâmetro, ou usar
`useFactory`. Existe `src/injectable-constructors.spec.ts` varrendo todo
`@Injectable`.

**Lição geral:** para serviço Nest, `docker run` na imagem. Verde não é
evidência de que sobe.

### B.2 Healthcheck que mente

**Sintoma:** `healthy` há dias, e nada consegue conectar.

`pg_isready` responde sobre o **processo**, não sobre a capacidade de
autenticar. O Postgres reportou saudável enquanto o papel da aplicação
não existia.

**Correção:** o healthcheck faz o que a aplicação faz —
`psql -U <user> -d <db> -c 'SELECT 1'`.

Da mesma família: o `/health` do Control Plane devolvendo 401 por falta
de `@Public()`. O healthcheck nunca passaria, e **a stack inteira** não
subiria, porque tudo depende dele via `service_healthy`.

### B.3 Path e header são um par

**Sintoma:** 404, você corrige, e vem **401** — que se lê como *chave
errada*, com a chave certa.

O Atlas falava com o Anvil através do gateway da nuvem, que traduzia
**duas** coisas:

| | O Atlas enviava | O Anvil esperava |
|---|---|---|
| Path | `/internal/anvil/features/…` | `/internal/features/…` |
| Header | `X-Atlas-Anvil-Key` | `x-anvil-api-key` |

Com o Anvil local, não há tradutor. Configurar um e esquecer o outro
falha apontando para o lugar errado.

### B.4 ACK antes da persistência

**Sintoma:** eventos somem depois de um deploy comum. O stream diz que
foram consumidos.

O consumer do Anvil dava ACK quando o handler retornava. Mas o handler
só **bufferiza** — a linha vira durável num flush posterior. Até 500
linhas perdidas por queda ou redeploy.

O comentário que autorizava o ACK vinha copiado do consumer do Atlas,
onde era verdadeiro. Aqui não era.

**Correção:** ACK propagado via `on_flushed`, disparando depois do
insert. Falhar em confirmar é a direção segura — o Redis reentrega.

### B.5 Flush parcial reinserindo o que já entrou

**Sintoma:** contagens infladas e médias distorcidas, sem nada indicando.

Insert tabela a tabela; se B falhava, o `except` restaurava **todas** —
inclusive as linhas de A que já estavam no ClickHouse.

E `ReplacingMergeTree` **só deduplica no merge**. As queries de feature
usam `avg()`/`count()` **sem `FINAL`** — até o merge, elas leem a
duplicata.

**Correção:** só as tabelas que não inseriram são restauradas.

### B.6 Stub de teste que responde o que a query pediu

**Sintoma:** cinco features retornando 500 em produção, com teste verde.

```python
return Result([{"minute": 73}])   # ← uma coluna que a tabela nunca teve
```

O stub do ClickHouse devolvia o que a SQL perguntasse. Ele nunca poderia
detectar drift de schema — porque não tinha schema.

**Correção:** teste que **parseia a DDL e a SQL** e compara, sem
ClickHouse vivo. Verificado falhando com cada bug reintroduzido.

### B.7 Método definido fora da classe

**Sintoma:** a funcionalidade "não existe", sem erro.

Um `cat >>` colocou dois métodos **depois** do fim da classe. E havia um
`hasattr` guardando a chamada — que degradava "honestamente" e escondia
o defeito.

**Correção:** métodos movidos para dentro, mais um teste baseado em AST
que verifica que estão no corpo da classe.

**Lição:** guarda defensiva que esconde erro de programação é pior que a
exceção. `hasattr` protege contra versão antiga; não contra código mal
colado.

### B.8 Palavras reservadas e alias que sombreia

**Sintoma:** passa em SQLite, quebra em Postgres. Ou funciona no
ClickHouse antigo e quebra no upgrade.

```sql
SELECT count(*) AS rows          -- ROWS é reservada no Postgres
SELECT anyLast(minute) AS minute -- o analyzer do CH 24.8 resolve o
                                 -- alias antes da coluna → auto-referência
```

O segundo erro sugere, sem ajudar: *"Maybe you meant: ['minute']"*.

**Correção:** `row_count`, `last_minute`. Nunca dar a uma expressão o
nome de uma coluna que ela usa.

### B.9 Booleano onde faltava um terceiro estado

**Sintoma:** escrita que deveria exigir aprovação passa sem auditoria.

`classifyQualityGateWrite` retornava booleano. Quando o
`decisionTargetId` saía `null`, o caminho era classificado como *não
governado* — e ainda assim encaminhado.

**Correção:** `governed | ordinary | refuse`. E a regra: **nada
terminado em `/decision` é `ordinary`**.

"Não consegui classificar" não é um dos dois valores de um booleano. Foi
disso que o bug nasceu.

### B.10 Revogação correta + cache correto = logout que não desloga

**Sintoma:** logout funciona, e a sessão continua válida por 30s.

`revokeSession` atualizava o banco; o `SessionCacheService` continuava
respondendo do cache. **Cada peça estava certa isoladamente.**

**Correção:** `logout` também chama `sessions.invalidate(token)`.

**Lição:** bug de composição não aparece em teste unitário de nenhuma
das partes.

### B.11 Capability em um lugar e não no outro

**Sintoma:** `denied_capability_unsupported` numa tela que deveria
funcionar.

A capability estava no `META` mas não em `services.ts`. Silencioso,
porque a recusa é o comportamento correto do gate.

**Correção:** adicionada aos descritores, mais
`governed-capabilities.test.ts` cruzando as duas listas.

### B.12 `.env` com sete `__required__` literais

**Sintoma:** autenticação falha com "senha incorreta" usando a senha
certa.

O `.env` do Robozão tinha `__required__` como **valor literal** em sete
lugares — inclusive o superusuário do Postgres, que virou um papel
chamado `__required__`.

**Correção:** conexão pelo socket local (trust), criação do papel e do
banco reais, sem destruir dado. **Dois ainda estão pendentes**
(`ADMIN_API_INTERNAL_TOKEN`, `GATEWAY_OPS_TOKEN`) e bloqueiam 12 telas.

O seed do Control Plane hoje **recusa** esse literal explicitamente.

### B.13 A imagem certa do Postgres

**Sintoma:** `ERROR: type "vector" does not exist`.

`postgres:16-alpine` não tem pgvector, e o Atlas depende dele.

**Correção:** `pgvector/pgvector:pg16`, com backup do diretório de dados
antes. Da mesma família: diretórios de dados criados como `root:root`
enquanto os serviços rodam como `999:987` — resolvido com `chown` via
container alpine descartável.

### B.14 Agent do Portainer não substitui o socket

**Sintoma:** Portainer no ar, agent saudável, **interface vazia**.

O container do Portainer precisa do `/var/run/docker.sock` montado. O
agent serve para **nós remotos** — são mecanismos diferentes.

E o socket só existe nos managers: sem
`constraints: [node.role == manager]`, o scheduler pode colocá-lo num
worker.

### B.15 Swarm ignora o endereço de bind

**Sintoma:** `127.0.0.1:9000:9000` e a porta responde em todas as
interfaces.

A routing mesh não sabe restringir a porta publicada a uma interface —
diferente do compose. O log avisa: *"ignoring IP-address ... service
will listen on 0.0.0.0"*.

O que de fato protege é o portproxy do Windows encaminhar **somente a
porta 80**. Saber qual controle está protegendo o quê importa.

### B.16 `include` do nginx é inserção textual

**Sintoma:** `nginx -t` reclama de diretiva duplicada.

`include` **não é herança**. Timeout no snippet compartilhado + timeout
na location = duplicata, e a config é recusada.

**Correção:** padrões no escopo `server`, locations sobrescrevem. Da
mesma família: repetir `text/html` em `sub_filter_types`, que já está lá
por padrão.

### B.17 O portproxy do WSL aponta para um IP morto

**Sintoma:** a porta aceita a conexão e ninguém responde. Sem erro.

O IP do WSL muda a cada boot. Regra antiga não é substituída por `add`.

**Correção:** o script faz `delete` antes de `add`, sempre a partir do
IP **atual**.

### B.18 FastAPI casa rotas na ordem de declaração

**Sintoma:** `GET /backtests/decisions` cai no handler de
`/{execution_id}` e tenta buscar uma execução chamada "decisions".

**Correção:** declarar a rota literal **antes** da paramétrica.

### B.19 Ciclo de import que só quebra no build

**Sintoma:** dev funciona; `next build` falha com
`UnhandledSchemeError: node:crypto`.

`session.ts` ↔ `console-api.ts` funcionava por hoisting, mas o bundler
seguiu a cadeia e puxou `node:crypto`.

**Correção:** extrair `lib/session-cookie.ts`.

### B.20 O Dockerfile e a convenção de nomes

**Sintoma:** build falha com "path not found" — sintoma que não aponta
para a causa.

O `Dockerfile` referenciava `robozao-gateway/` enquanto o diretório é
`insight-robozao-gateway/`. Todo serviço do monorepo é `insight-*`.

---

## Parte C — O que continua aberto

| Pendência | Impacto |
|---|---|
| Adapter direto do console ao Gateway da nuvem | Código morto, mas ainda uma rota ([Parte 7](07-insight-console.md)) |
| `ADMIN_API_INTERNAL_TOKEN`, `GATEWAY_OPS_TOKEN` | 12 telas fora do menu |
| Stack de aplicação fora do Swarm | Sem resiliência declarativa |
| TLS | `COOKIE_SECURE=false` |
| `human_signals` sem escritor | `signal_count` sempre 0 no Anvil |
| `match_minute` ausente do schema | Lacuna de modelo de dados |
| Testes do console só cobrem `lib/` | Regressão de UI passa despercebida |
| Baseline congelado do Quality Gate | Precisa de dataset real |

---

### Fechadas desde a primeira edição

| Era | Virou |
|---|---|
| `HTTPExecutor` no Node Agent | Removido, com teste de fronteira ([Parte 8](08-node-agent.md), §6) |
| Nexus autenticando pelo Gateway | Identidade pelo Control Plane ([Parte 5](05-insight-nexus.md), §6.1) |
| Fila de publicação sem leitor | `publishworker` drena de verdade ([Parte 5](05-insight-nexus.md), §6) |
| Console falando direto com o Node Agent | Passa pelo Control Plane ([Parte 8](08-node-agent.md), §6.1) |

E três armadilhas novas, da mesma família das de cima:

**B.21 — Autoridade sem autorização.** O Node Agent recebia id, nome e
papel do operador, mas **não as permissões**. Todo comando devolvia 403.
A identidade passava e a autorização não, e a recusa lia-se como "este
operador não pode" quando ninguém tinha perguntado.

**B.22 — Coerção silenciosa que escala.** `severity: "warning"` virava
`ERROR`, porque a constante é maiúscula e a validação caía num
`if !valid { = SevError }`. Escalar o aviso de alguém para erro aciona
plantão por um problema que ninguém reportou. Recusar é visível;
coagir, não.

**B.23 — Um default compilado é uma rota.** `lib/robozao.ts` guardava
`?? "http://robozao-gateway:8095"`. O container do console não tinha a
variável, o que fazia parecer que ele não alcançava nada — e alcançava.
Procure endereços, não só credenciais.

---

## Fecho

O padrão que mais se repete acima não é técnico:

> **A verificação precisa exercitar o que a produção exercita.**

Teste verde com stub que concorda com a query. Healthcheck verde sobre o
processo em vez da conexão. Build verde com um construtor que o
container não consegue resolver. Compose no servidor à frente do repo.

Em todos, alguma camada respondeu por outra — e respondeu "sim".

**Fim da apostila.** Volte ao [índice](README.md).
