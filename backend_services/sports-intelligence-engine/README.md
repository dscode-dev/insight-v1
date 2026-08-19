# Insight Sports Intelligence Engine

Motor de tendências contextualizadas e explicáveis para futebol.

**Não é um preditor de placar.** Ele compara o estado corrente de uma partida
com situações históricas matematicamente semelhantes e descreve o que
aconteceu naquelas — nunca o que vai acontecer nesta. A diferença não é de
estilo: uma afirmação sobre o passado tem como ser conferida.

Cobertura da V1: Brasileirão Série A, Libertadores, Premier League, Champions
League, La Liga.

---

## Estado atual — PR-02

Três PRs fechados.

**PR-00 — fundação arquitetural.** Contratos fundamentais (identidade, tempo,
procedência, qualidade, ausência, versões, erros), ciclo de vida da partida,
envelope de eventos, ports, duas APIs, CLI, log estruturado, e testes de
arquitetura que falham o CI quando um limite é violado.

**PR-01 — Canonical Football Domain.** O idioma interno do motor: catálogo
fechado de 5 competições, `Season`, `CompetitionRegime`, `Stage`, `Team`,
`Player`, `PlayerTeamTenure`, `Match` (sem resultado), `MatchResult`,
`Lineup`, `Position` vs `TacticalRole`, `CanonicalMatchEvent` com revisão,
`PitchCoordinate`, `OddsQuote`.

**PR-02 — Dataset Registry & Historical Manual Intake.** A primeira entrada
real de dados no motor: registro de dataset, upload em streaming com SHA-256,
arquivo bruto imutável em S3/MinIO, validação estrutural de CSV/JSONL/Parquet,
manifesto com impressão, trilha de auditoria, e persistência transacional em
PostgreSQL.

> **O que o PR-02 deliberadamente NÃO faz:** nada aqui descreve futebol. Um
> arquivo que diz `Manchester City` continua sendo texto numa coluna. Resolver
> isso para um `TeamId` é o PR-03, e um teste de arquitetura falha o CI se
> alguém antecipar. Ver [`docs/data/HISTORICAL_DATASET_INTAKE.md`](docs/data/HISTORICAL_DATASET_INTAKE.md).

**O que NÃO existe ainda** (e não deve ser inventado antes do PR que o traz):
resolução de identidade, data fusion, adapters de provedor, MatchStateVector,
Player Influence, Team Strength, Pressure, Similarity, as cinco lentes,
scheduler.

---

## Rodando localmente

Requer **Python 3.13+**.

```bash
make install          # instala em modo editável, com as dependências de dev
cp .env.example .env  # e preencha ENGINE_SECURITY_INTERNAL_TOKEN
```

O `.env.example` não tem segredo preenchido, e isso é deliberado (ADR e
Constituição §14): nenhum segredo tem default.

### Subir a infraestrutura

```bash
make infra-up         # PostgreSQL (5433) + MinIO (9000, console 9001)
make migrate
make migrate-status
```

Só esses dois serviços: são os que o código de fato exercita hoje. Redis,
ClickHouse e pgvector estão nos ADRs e não têm uma linha que fale com eles —
um compose que sobe seis contêineres para exercitar dois transforma
`docker compose up` numa espera, e é assim que um ambiente local deixa de ser
usado.

### Verificar o ambiente

```bash
make cli ARGS=doctor
```

`doctor` reporta o que está configurado, o que falta e **o que é exigido
agora** — sem precisar que a infraestrutura exista. Um `doctor` que morre
porque não há Postgres é inútil justamente quando é mais necessário.

### O fluxo de intake, ponta a ponta

```bash
engine dataset create \
  --name premier-league-2019-2024 \
  --source-name football-data.co.uk \
  --source-type OPEN_DATA --provider-id football_data \
  --license-class ATTRIBUTION_REQUIRED \
  --retrieved-at 2026-08-01T10:00:00Z \
  --competition PREMIER_LEAGUE \
  --season 2019-2020

engine dataset upload   <id> ./E0.csv --format CSV
engine dataset validate <id> --required Date --required HomeTeam
engine dataset manifest <id>
engine dataset stage    <id> --reason "conferido contra o site da fonte"
```

A CLI usa **os mesmos casos de uso** da Control API — inclusive as validações,
a trilha de auditoria e os eventos. Promover pelo terminal e promover pela API
fazem exatamente a mesma coisa.

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
make test              # unidade + arquitetura + smoke
make test-architecture # só os limites arquiteturais
make test-integration  # exige PostgreSQL e object store DE VERDADE
make test-performance  # benchmark de ingestão; reporta, não afirma SLO
```

Os testes de integração são separados de propósito. Uma suíte que às vezes
precisa de infraestrutura e às vezes não é uma suíte que ninguém sabe se está
passando — e quem não tem Docker precisa poder rodar a parte rápida.

Eles usam PostgreSQL e MinIO de verdade, de onde quer que venham:

```bash
# 1. o ambiente já oferece  (o compose local, ou o serviço do CI)
SIE_TEST_POSTGRES_DSN=postgresql://engine:engine_local@localhost:5433/sports_intelligence \
SIE_TEST_OBJECT_STORE_ENDPOINT=http://localhost:9000 \
  make test-integration

# 2. sem variável nenhuma: Testcontainers sobe um PostgreSQL descartável
make test-integration

# 3. sem Docker: os testes são PULADOS, com o motivo dito
```

Nunca cai para um duplo em memória. Uma suíte de integração que
silenciosamente vira teste de unidade é pior que uma ausente, porque parece
cobertura.

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
- [`docs/architecture/adr/`](docs/architecture/adr/) — as dezessete decisões
  fundamentais, com contexto, consequências e o que foi rejeitado.

Cinco deles decidem a maior parte das dúvidas do dia a dia:

- **ADR-0007** — uma partida nunca alimenta o índice que ela própria consulta;
- **ADR-0009** — ausente nunca vira zero;
- **ADR-0010** — requisição de usuário não dispara cálculo;
- **ADR-0014** — o bruto é imutável, e a imutabilidade é imposta por ausência;
- **ADR-0016** — `STAGED` não é `HISTORICAL_ACTIVE`;
- **ADR-0026** — uma versão publicada do corpus é imutável, e `DRAFT → READY`
  não é uma aresta que exista;
- **ADR-0027** — o PostgreSQL é a verdade; o Parquet é uma representação, e ela
  é opcional;
- **ADR-0028** — um registro histórico de evento é entidade repetida, e nunca
  campo escalar de partida — no intake e no corpus;
- **ADR-0029** — a geração de features usa semântica AS-KNOWN: tempo efetivo
  não é tempo de conhecimento, e o desconhecido falha fechado;
- **ADR-0030** — definições e espaços de feature são contratos semânticos
  versionados, e a ordem do espaço é parte da identidade dele;
- **ADR-0031** — o estado histórico da partida é reconstruído sob demanda e
  nunca armazenado: ele é função do corpus e da política, e uma linha gravada
  não carrega essas dependências.

Contratos de dados:

- [`docs/data/CANONICAL_FOOTBALL_MODEL.md`](docs/data/CANONICAL_FOOTBALL_MODEL.md)
- [`docs/data/CANONICAL_DATA_DICTIONARY.md`](docs/data/CANONICAL_DATA_DICTIONARY.md)
- [`docs/data/HISTORICAL_DATASET_INTAKE.md`](docs/data/HISTORICAL_DATASET_INTAKE.md)
- [`docs/data/IDENTITY_RESOLUTION.md`](docs/data/IDENTITY_RESOLUTION.md)
- [`docs/data/DATA_FUSION.md`](docs/data/DATA_FUSION.md)
- [`docs/data/HISTORICAL_QUALITY_EXECUTION.md`](docs/data/HISTORICAL_QUALITY_EXECUTION.md)
- [`docs/data/CANONICAL_BUILD_CORE.md`](docs/data/CANONICAL_BUILD_CORE.md)
- [`docs/data/HISTORICAL_CANONICAL_CORPUS.md`](docs/data/HISTORICAL_CANONICAL_CORPUS.md)
- [`docs/data/HISTORICAL_EVENT_CONTRACT.md`](docs/data/HISTORICAL_EVENT_CONTRACT.md)
- [`docs/data/HISTORICAL_EVENT_CANONICALIZATION.md`](docs/data/HISTORICAL_EVENT_CANONICALIZATION.md)
- [`docs/data/EVENT_CAPABILITY_ANALYSIS.md`](docs/data/EVENT_CAPABILITY_ANALYSIS.md)
- [`docs/contracts/DATASET_MANIFEST_V1.md`](docs/contracts/DATASET_MANIFEST_V1.md)
- [`docs/contracts/RESOLUTION_DECISION_V1.md`](docs/contracts/RESOLUTION_DECISION_V1.md)
- [`docs/contracts/FUSION_OUTPUT_V1.md`](docs/contracts/FUSION_OUTPUT_V1.md)
- [`docs/contracts/QUALITY_ASSESSMENT_V1.md`](docs/contracts/QUALITY_ASSESSMENT_V1.md)
- [`docs/contracts/HISTORICAL_CANONICAL_MANIFEST_V1.md`](docs/contracts/HISTORICAL_CANONICAL_MANIFEST_V1.md)
- [`docs/contracts/HISTORICAL_CANONICAL_DATASET_V1.md`](docs/contracts/HISTORICAL_CANONICAL_DATASET_V1.md)
- [`docs/contracts/HISTORICAL_EVENT_RECORD_V1.md`](docs/contracts/HISTORICAL_EVENT_RECORD_V1.md)

Contratos de feature (PR-05.1 — contratos, sem features):

- [`docs/features/FEATURE_CONTRACT_V1.md`](docs/features/FEATURE_CONTRACT_V1.md)
- [`docs/features/TEMPORAL_SEMANTICS_V1.md`](docs/features/TEMPORAL_SEMANTICS_V1.md)
- [`docs/features/TEMPORAL_LEAKAGE_MODEL.md`](docs/features/TEMPORAL_LEAKAGE_MODEL.md)
- [`docs/features/FEATURE_SPACE_V1.md`](docs/features/FEATURE_SPACE_V1.md)
- [`docs/features/NORMALIZATION_CONTRACT_V1.md`](docs/features/NORMALIZATION_CONTRACT_V1.md)

Estado histórico da partida (PR-05.2 — estado, sem feature):

- [`docs/features/HISTORICAL_MATCH_STATE_V1.md`](docs/features/HISTORICAL_MATCH_STATE_V1.md)
- [`docs/features/MATCH_STATE_RECONSTRUCTION.md`](docs/features/MATCH_STATE_RECONSTRUCTION.md)
- [`docs/features/STATE_COMPONENT_AVAILABILITY.md`](docs/features/STATE_COMPONENT_AVAILABILITY.md)

---

## Integração com o resto do Insight

O motor é um serviço do monorepo `insight-v1`. Os contratos de fronteira com
`insight-gateway`, `insight-sport-hub` e `insight-console-api` serão
**renegociados explicitamente** quando cada um for alcançado — nenhum deles é
herdado do motor anterior.

O registro do que foi aposentado, e do que ficou medido dele, está em
[`backup/old/README.md`](../../backup/old/README.md).
