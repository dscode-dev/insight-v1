# Insight Sports Intelligence Engine

Motor de tendências contextualizadas e explicáveis para futebol.

**Não é um preditor de placar.** Ele compara o estado corrente de uma partida
com situações históricas matematicamente semelhantes e descreve o que
aconteceu naquelas — nunca o que vai acontecer nesta. A diferença não é de
estilo: uma afirmação sobre o passado tem como ser conferida.

Cobertura da V1: Brasileirão Série A, Libertadores, Premier League, Champions
League, La Liga.

---

## Estado atual — PR-00

Este é o **PR-00: fundação arquitetural**. O que existe:

- contratos fundamentais (identidade, tempo, procedência, qualidade,
  ausência, versões, erros);
- ciclo de vida da partida com transições explícitas;
- envelope de eventos e chaves de idempotência;
- ports para as dependências previstas;
- duas APIs (`control_api`, `query_api`) com health e version;
- CLI com `version` e `doctor`;
- log estruturado com correlação e redação de segredo;
- testes de arquitetura que falham o CI quando um limite é violado.

**O que NÃO existe ainda** (e não deve ser inventado antes do PR que o traz):
MatchStateVector, Player Influence, Team Strength, Pressure, Similarity, as
cinco lentes, provedor real, scheduler, adapters de persistência.

---

## Rodando localmente

Requer **Python 3.13+**.

```bash
make install          # instala em modo editável, com as dependências de dev
cp .env.example .env  # e preencha ENGINE_SECURITY_INTERNAL_TOKEN
```

O `.env.example` não tem segredo preenchido, e isso é deliberado (ADR e
Constituição §14): nenhum segredo tem default.

### Verificar o ambiente

```bash
make cli ARGS=doctor
```

`doctor` reporta o que está configurado e o que falta, **sem exigir** que a
infraestrutura exista. Um `doctor` que morre porque não há Postgres é inútil
justamente quando é mais necessário.

### Subir as APIs

```bash
make run-control-api   # http://127.0.0.1:8080/docs
make run-query-api     # http://127.0.0.1:8081/docs
```

Ambas expõem `GET /health/live`, `GET /health/ready` e `GET /version`.

### Qualidade

```bash
make lint              # ruff
make typecheck         # mypy estrito
make test              # pytest
make test-architecture # só os limites arquiteturais
```

---

## Arquitetura em uma tela

```
apps → application → domain / features / engines
                          ↑
                        ports
                          ↑
                      adapters
```

Adapters implementam ports. Nunca o inverso.

O domínio **não conhece** FastAPI, Postgres, Redis, ClickHouse, S3 nem o
formato de nenhum provedor — verificado por AST em `tests/architecture/`,
falhando o CI.

### Dois planos

**Control Plane** (`control_api`, CLI): administração, datasets,
configuração, reconciliação. Operações raras, privilegiadas, auditadas.

**Execution Plane** (workers, `query_api`): ingestão, cálculo, arquivamento,
promoção, leitura. Contínuas e automáticas.

### O ciclo que governa tudo

```
bootstrap público → conhecimento histórico → partida ao vivo →
inteligência ao vivo → arquivo → reconciliação → reconstrução →
promoção → conhecimento nativo → partidas futuras
```

> Toda partida ao vivo é também um dataset histórico futuro.

---

## Leitura obrigatória antes de contribuir

- [`docs/architecture/CONSTITUTION.md`](docs/architecture/CONSTITUTION.md) —
  os invariantes, e por que cada um existe;
- [`docs/architecture/adr/`](docs/architecture/adr/) — as dez decisões
  fundamentais, com contexto, consequências e o que foi rejeitado.

Três deles decidem a maior parte das dúvidas do dia a dia:

- **ADR-0007** — uma partida nunca alimenta o índice que ela própria consulta;
- **ADR-0009** — ausente nunca vira zero;
- **ADR-0010** — requisição de usuário não dispara cálculo.

---

## Integração com o resto do Insight

O motor é um serviço do monorepo `insight-v1`. Os contratos de fronteira com
`insight-gateway`, `insight-sport-hub` e `insight-console-api` serão
**renegociados explicitamente** quando cada um for alcançado — nenhum deles é
herdado do motor anterior.

O registro do que foi aposentado, e do que ficou medido dele, está em
[`backup/old/README.md`](../../backup/old/README.md).
