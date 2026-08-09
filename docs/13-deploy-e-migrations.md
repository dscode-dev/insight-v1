# Parte 13 — Deploy, migrations e verificação

> Esta parte é operacional: como subir, como migrar, como criar o
> primeiro usuário — e, sobretudo, **como saber que funcionou**.

---

## 1. Onde ficam os arquivos

| Onde | O quê |
|---|---|
| `infra/robozao/docker-compose.yml` (repo) | A fonte da verdade |
| `~/Insight/docker-compose.yml` (servidor) | O que está rodando |
| `~/Insight/.env` (servidor) | Segredos — **nunca vai para o repo** |

O compose do repo e o do servidor **devem ser idênticos**. Eles
divergiram durante a Fase C (o servidor recebeu o `NODE_AGENT_TOKEN` e
as tags novas antes do repo) e foram sincronizados. Vale checar:

```bash
ssh -p 2222 ninja@172.23.207.224 "md5sum ~/Insight/docker-compose.yml"
md5sum infra/robozao/docker-compose.yml
```

> Compose de servidor à frente do repo é como se perde uma configuração:
> ela existe em uma máquina só, e ninguém sabe que existe até a máquina
> ser reconstruída.

---

## 2. Ordem de subida

As dependências ditam a ordem, e o compose a codifica com
`depends_on: condition: service_healthy`:

```
1. postgres · redis · clickhouse         (infra)
        ↓ healthy
2. *-migrate                             (roda e sai)
        ↓ completed_successfully
3. explorer · atlas · anvil · nexus · sport-hub · node-agent
        ↓
4. insight-console-api                   (Control Plane)
        ↓
5. insight-console
```

```bash
cd ~/Insight
docker compose up -d
docker compose ps          # todos devem chegar a (healthy)
```

Os serviços de migration usam `condition: service_completed_successfully`
— não `service_started`. A diferença importa: um serviço que sobe antes
da migration terminar encontra tabela faltando e falha de um jeito que
não aponta para a causa.

---

## 3. Migrations — três mecanismos diferentes

Não há um padrão único, e saber qual é qual evita procurar comando que
não existe.

| Serviço | Como migra | Comando |
|---|---|---|
| Control Plane | Serviço de compose | `docker compose run --rm control-plane-migrate` |
| Atlas | Serviço de compose | `docker compose run --rm atlas-migrate` |
| Nexus | Binário `nexus-migrate` | `docker compose run --rm nexus-migrate` |
| **Anvil** | **Sozinho, no boot** | nenhum — `AUTO_APPLY_MIGRATIONS=true` |
| Explorer | Sem DDL própria | — |

O Anvil é a exceção: todo o DDL é `CREATE ... IF NOT EXISTS` e roda no
start. **Não procure um `anvil-migrate`.**

Todos são idempotentes e seguros de rodar a cada deploy.

---

## 4. O primeiro operador do console

Um Control Plane recém-migrado tem a tabela `operators` **vazia**.
Ninguém consegue entrar — e as telas que criariam uma conta estão atrás
do próprio login.

### Passo 1 — apontar as credenciais no `.env`

No `~/Insight/.env` do servidor:

```bash
CONSOLE_SEED_USERNAME=darlan
CONSOLE_SEED_EMAIL=darlansimplicio@gmail.com
CONSOLE_SEED_PASSWORD=<no mínimo 12 caracteres>
CONSOLE_SEED_DISPLAY_NAME=Darlan            # opcional
CONSOLE_SEED_ROLE=SuperAdmin                # padrão
CONSOLE_SEED_RESET_PASSWORD=false           # padrão
```

As três primeiras são **obrigatórias** — o compose usa `:?`, então o
comando nem inicia sem elas.

### Passo 2 — rodar

```bash
cd ~/Insight
docker compose --profile seed run --rm control-plane-seed
```

### Passo 3 — remover a senha do `.env`

Ela já está no banco, com hash. Deixá-la em texto no arquivo não serve
mais para nada e só amplia a superfície.

### Por que é assim, e não `docker compose exec`

O comentário no compose responde:

```yaml
# First console operator. Its own service so the CONSOLE_SEED_* values
# reach it from .env — `compose run` on the serving container would
# not, and adding those variables to the serving container would put a
# plaintext admin password in the environment of a long-lived process
# for no reason.
```

E o `profiles: ["seed"]` garante que ele **nunca** sobe num
`docker compose up`.

### As proteções do seed

**Não troca senha de quem já existe** sem `CONSOLE_SEED_RESET_PASSWORD=true`:

```typescript
// A seed that silently rewrote the admin credential on every deploy is
// a way to lock people out — and deploys re-run far more often than
// anyone expects.
```

**Não faz `trim` na senha:**

```typescript
// NOT trimmed: leading/trailing spaces are legitimate password
// characters, and stripping them would make the stored password differ
// from the one the operator was handed.
```

**Recusa senha fraca** (mínimo 12 caracteres) e **recusa o placeholder
literal `__required__`** — que é exatamente o valor que sobra num `.env`
mal preenchido.

**Recusa papel inválido** em vez de cair num padrão. Criar um SuperAdmin
porque alguém digitou `Admnistrator` seria a falha na direção errada.

---

## 5. Verificação — a parte que mais economiza tempo

A lição mais cara deste trabalho:

> **Build verde, teste verde e typecheck verde não são evidência de que
> o serviço sobe.**

O Control Plane falhou no boot **três vezes** com tudo verde — parâmetros
de construtor que o Nest não conseguia resolver
([Parte 6](06-insight-control-plane.md), seção 8). A única verificação
que pega isso é rodar o container.

### 5.1 O container sobe?

```bash
docker compose up -d insight-console-api
docker compose logs -f insight-console-api
```

Erro de DI do Nest aparece nos primeiros segundos e o processo morre.

### 5.2 O healthcheck passa de verdade?

Cuidado com healthcheck que mente. O do Postgres usava `pg_isready`, que
responde "pronto" quando o **processo** está de pé — e reportou saudável
por dias enquanto **ninguém conseguia conectar**, porque o papel do banco
não existia.

O healthcheck honesto faz o que a aplicação faz:

```yaml
test: ["CMD-SHELL", "psql -U $$POSTGRES_USER -d $$POSTGRES_DB -c 'SELECT 1'"]
```

E o `/health` do Control Plane precisa ser `@Public()` — sem isso ele
devolve 401, o healthcheck nunca passa, e **a stack inteira não sobe**,
porque tudo depende dele via `service_healthy`.

### 5.3 As telas respondem?

O único jeito confiável de saber é chamar. Foi assim que se descobriu
que 14 das 33 telas do console não podiam funcionar:

```bash
for path in /operations /atlas/quality-gate /data-intelligence/pipelines; do
  curl -s -o /dev/null -w "$path -> %{http_code}\n" \
    -b "session=$TOKEN" "http://127.0.0.1/console$path"
done
```

### 5.4 O serviço está fazendo trabalho, ou só de pé?

Distinção que os logs de boot já respondem, quando bem escritos:

```
sport-hub:  scheduler_inactive_no_providers_configured   ← up, ocioso
nexus:      XLEN insight:stream:trends = 0               ← up, sem entrada
anvil:      consumer group ativo, 0 pending              ← up, em dia
```

`healthy` responde "o processo está vivo". Não responde "há trabalho
acontecendo".

---

## 6. Rodar testes sem Node/npm na máquina

Node não existe na máquina de desenvolvimento. Docker resolve:

```bash
# Console (Next/vitest)
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "/c/Users/Ninja/Documents/Projetos/insight-v1:/work" \
  -w /work/frontend/insight-console node:22-alpine \
  sh -c "npm install --no-package-lock && npm run typecheck && \
         npm run lint && npm run check:boundaries && npm run test"

# Go (Nexus, Gateway, Node Agent, Sport Hub, Social)
docker run --rm -v "/c/.../insight-v1:/work" \
  -w /work/backend_services/insight-nexus golang:1.23-alpine \
  go test ./...

# Python (Atlas, Explorer, Anvil)
docker run --rm -v "/c/.../insight-v1:/work" \
  -w /work/backend_services/insight-atlas python:3.11-slim \
  sh -c "pip install -q -r requirements.txt && python -m pytest -q"
```

> **`MSYS_NO_PATHCONV=1` é obrigatório** no Git Bash do Windows. Sem
> ele, o `/work` do lado direito do `-v` é convertido para um caminho
> Windows e o mount aponta para lugar nenhum.
>
> **`--no-package-lock`, não `npm ci`.** O `package-lock.json` do console
> está dessincronizado do `package.json` desde antes deste trabalho.

---

## 7. Atualizar um serviço

```bash
# 1. build local
docker build -t konohalabs/insight-atlas:1.0.5 backend_services/insight-atlas

# 2. push para o registry do Robozão
docker tag konohalabs/insight-atlas:1.0.5 172.23.207.224/insight-atlas:1.0.5
docker push 172.23.207.224/insight-atlas:1.0.5

# 3. a tag muda NOS DOIS compose (repo e servidor)
# 4. subir
ssh -p 2222 ninja@172.23.207.224 "cd ~/Insight && docker compose up -d insight-atlas"

# 5. verificar
ssh -p 2222 ninja@172.23.207.224 "docker compose ps insight-atlas && \
                                  docker compose logs --tail 30 insight-atlas"
```

O passo 3 é onde a divergência nasce. Mudar só no servidor funciona —
até alguém rodar `docker compose up` a partir do repo e derrubar a
versão nova.

---

## 8. Pendências de deploy

| Item | Estado |
|---|---|
| `ADMIN_API_INTERNAL_TOKEN` | `__required__` — bloqueia 12 telas |
| `GATEWAY_OPS_TOKEN` | `__required__` — mesma origem |
| Swarm para a stack de aplicação | Não feito — só Portainer e registry |
| `deploy.sh` orquestrando migrations | Não feito |
| TLS | Ausente por decisão |
| Baseline congelado do Quality Gate | Precisa de dataset real |

---

## Próximo passo

**[Parte 14 — Decisões e armadilhas](14-decisoes-e-armadilhas.md)**: o
resumo do que já custou caro, para não custar de novo.
