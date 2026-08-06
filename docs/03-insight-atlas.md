# Parte 3 — Insight Atlas

> **Papel em uma frase:** transforma o histórico coletado pelo Explorer
> e os eventos ao vivo em inteligência esportiva descritiva.
>
> **Linguagem:** Python · **Framework:** FastAPI · **Porta:** 8085
> **Persistência:** PostgreSQL **com pgvector** + Redis
> **Tamanho:** ~33 mil linhas, 60+ subpacotes — o maior serviço da plataforma

---

## 1. A restrição que define este serviço

Antes de qualquer coisa técnica, entenda a regra que governa o Atlas:

> **O Atlas é descritivo, nunca preditivo.**

Ele descreve o que **está acontecendo** e o que **já aconteceu em
situações parecidas**. Ele **não** prevê resultado, não emite
probabilidade de vitória e não produz recomendação de aposta.

Isso não é convenção verbal — é forçado no código:

```python
# atlas/contracts/no_prediction.py
assert_no_prediction_keys(payload)
assert_no_prediction_phrases(text)
```

Existe uma deny-list de chaves e de frases, aplicada no `model_post_init`
do `Trend` e nos contratos de inteligência que carregam texto livre. Se
alguém adicionar um campo `win_probability`, o objeto falha na
construção.

**Por que tanto rigor:** o valor da plataforma é ser uma camada de
contexto confiável. No momento em que ela emite palpite, todo o resto
passa a ser lido como palpite também.

---

## 2. A segunda restrição: a arquitetura está CONGELADA

O arquivo `ATLAS_V1_FROZEN.md` na raiz do serviço declara, desde
2026-07-02:

> Detectors, thresholds, Oracle/Behavior/Reasoning/Similarity logic and
> embeddings are **FROZEN** for V1.

E define a política de extensão:

> Every new detector/heuristic MUST pass the Quality Gate (regression +
> promotion) against the frozen baseline before promotion. **Human
> approval remains mandatory.**

O que isso significa na prática, para você que vai mexer:

- **Pode:** adicionar coisas novas **por cima**, em pacotes novos.
- **Não pode:** mudar um threshold, a lógica de um detector ou o layout
  de um embedding sem passar pelo Quality Gate e ter aprovação humana
  registrada.

Um exemplo real de como isso se respeita: quando os embeddings passaram
de 32 para 37 dimensões, o layout v1 **não** foi alterado. Nasceu um v2
ao lado, numa coluna separada, e os dois coexistem. Detalhes na seção 6.

---

## 3. Mapa dos pacotes

Os maiores, por linhas de código:

| Pacote | Linhas | O que faz |
|---|---|---|
| `intelligence/` | 7.203 | Os motores de inteligência (comportamento, regime, raciocínio, evidência…) |
| `trends/` | 5.115 | Detecção de tendências — 22 detectores |
| `api/` | 2.402 | Superfície HTTP |
| `backtest/` | 1.795 | Replay determinístico + **Quality Gate** |
| `watchers/` | 1.131 | Observação contínua |
| `outcome/` | 1.091 | Pipeline ML experimental (**fora do escopo V1**) |
| `similarity/` | 1.057 | Similaridade online (pgvector) |
| `vector_memory/` | 928 | Embeddings e memória vetorial |
| `streaming/` | 864 | Consumo de eventos canônicos |
| `strength/` | 843 | Motor de força de time (Elo, ataque/defesa, h2h) |
| `market/` | 825 | Estado de mercado a partir de odds |

### Uma armadilha de nomenclatura

Existem **três** sistemas de sinais paralelos, e confundi-los custa
tempo:

| Apelido | Onde | Estado |
|---|---|---|
| **Sistema A** | `atlas/features/definitions.py` — 11 features de ML | Alimenta o `/v1/context` |
| **Sistema B** | `intelligence/similarity_engine/` | **É o que roda ao vivo** |
| **Sistema C** | `atlas/outcome/` | Offline, experimental, **sem modelo promovido** |

Quando alguém diz "as features do Atlas", pergunte qual sistema.

---

## 4. Como o dado entra

Duas portas, e elas têm naturezas diferentes.

### Porta 1 — eventos canônicos (Redis Streams)

O `CanonicalConsumer` (`atlas/streaming/`) consome os envelopes que o
Sport Hub publica:

- `insight:stream:events:match` — estado da partida
- `insight:stream:events:context`
- `insight:stream:events:odds` — mercado

Este é o **único** caminho de ingresso ao vivo. O Atlas não chama
provedor externo.

> **Bug real, corrigido:** o `run()` do consumer só protegia o
> `xreadgroup` com try/except; o `_dispatch` rodava desprotegido.
> Qualquer exceção inesperada — um `RedisError` transitório no `xack`, ou
> um `UnicodeDecodeError` num payload não-UTF8 **dentro do próprio
> handler de erro** — matava a task de ingestão **permanentemente**,
> enquanto o `/ready` continuava reportando saudável.
>
> Hoje o dispatch tem rede de proteção, o consumer é supervisionado com
> backoff exponencial, e existe um `app.state.consumer_alive` que
> alimenta o `/ready` — um consumer morto finalmente aparece.

Outro ponto que valeu correção: a idempotência era *check-then-act*
(`seen()` → handler → `mark_processed()`). Duas réplicas podiam passar
as duas pelo check. Virou `claim()` atômico com `SET NX`.

### Porta 2 — histórico do Explorer (volume em disco)

O `StrengthSyncWatcher` lê periodicamente a camada **`validated`** do
lake do Explorer, montada em `/var/atlas/explorer:ro`.

**Por que não é um evento:** o stream ao vivo nunca carrega "a partida
terminou 2 a 1". Só o histórico do Explorer é autoritativo para
resultado.

---

## 5. Similaridade — o coração do serviço

A pergunta que o Atlas responde melhor é: *"o que costuma acontecer em
jogos parecidos com este?"*

### Os 15 sinais

```python
# atlas/intelligence/similarity_engine/engine.py
_WEIGHTS = {
    "elo_delta": 0.16,
    "home_attack_strength": 0.07,
    "away_attack_strength": 0.07,
    "home_defense_strength": 0.07,
    "away_defense_strength": 0.07,
    "market_pressure": 0.10,
    "line_movement": 0.08,
    "home_form": 0.07,
    "away_form": 0.07,
    "h2h_advantage": 0.05,
    "table_position_gap": 0.05,
    "rest_advantage": 0.04,
    "draw_tendency": 0.04,
    "volatility": 0.03,
    "uncertainty": 0.03,
}
```

Somam 1,0. Eram 7 sinais; foram para 15 no trabalho chamado
**ATLAS-SIM-A**, que trouxe a matemática de força de time que antes
existia só offline.

O comentário logo abaixo é importante:

```python
# Signals that are always present (defaulted, never fabricated as a
# stand-in for "unknown" — 0.5/0.0 are genuinely neutral values here).
```

A diferença entre *ausente* e *neutro* é levada a sério: quando um sinal
opcional falta, o peso é **renormalizado** entre os presentes, em vez de
inventar um valor.

### Dois domínios que não se misturam

| Domínio | Como funciona | Onde |
|---|---|---|
| **Online** | pgvector, no caminho da requisição: `Service → Cache → Repository` | `atlas/similarity/` |
| **Offline** | Índice determinístico sobre dataset | `intelligence/similarity_engine/` |

O `ATLAS_V1_FROZEN.md` é explícito: *"the online-vector read path has ONE
source of truth (SimilarityService); offline similarity is a separate,
documented domain and must not be merged"*.

> **Bug real:** a `cache_key()` incluía todos os facetadores de versão e
> domínio, mas **não** o `minimum_neighbors` — que governa
> `coverage = len(matches)/minimum_neighbors` e portanto a `confidence`.
> Duas requisições que diferiam só nesse valor colidiam: a segunda
> recebia a cobertura da primeira (1.0 em vez de 0.4 para os mesmos
> quatro vizinhos), o que pode inverter um gate do Oracle.

---

## 6. Memória vetorial: v1 e v2 convivendo

Colunas do pgvector têm **dimensão fixa**. Quando o layout novo precisou
de 37 dimensões e o antigo tinha 32, não dava para "mudar a coluna" —
isso quebraria o congelamento e invalidaria todo o corpus existente.

A solução (migration `0018`):

- `embedding` **vector(32)** — o v1 congelado, intacto
- `embedding_v2` **vector(37)** — coluna nova, nullable, com índice HNSW próprio
- A constraint única passou de `source_match_id` para
  **`(source_match_id, embedding_version)`**, para que as duas linhas do
  mesmo jogo coexistam
- O SQL de busca escolhe a coluna física conforme a versão pedida

Consequência operacional: **cobertura assimétrica é um estado real**. Se
o backfill do v2 estiver pela metade, uma busca v2 devolve vizinhos de
um corpus mais fino — silenciosamente. Por isso existe
`GET /v1/meta/embeddings`, que reporta linhas e partidas por versão.

---

## 7. Motor de tendências (`trends/`)

22 detectores. Cada tick monta um `TrendInputs` e cada detector decide se
emite um `Trend`, que vai para `insight:stream:trends`.

### O achado mais importante do projeto

O **Oracle estava morto em produção — e sempre esteve**.

```python
# atlas/trends/pipeline.py — o código ANTIGO, com o bug
inputs.similarity = await probe.probe(inputs)
```

`TrendInputs` é um `@dataclass(frozen=True)`. Atribuir a um campo lança
`FrozenInstanceError`, que **herda de `AttributeError`** — e era capturado
pelo `except Exception` logo abaixo, virando um log
`similarity_probe_failed` indistinguível de uma queda real do pgvector.

Resultado: `similarity` era **sempre** `None`, o
`OracleSimilarityDetector` retornava `[]` na primeira linha, e
`historical_similarity`/`historical_pattern` **nunca** foram emitidos —
enquanto a query no pgvector continuava sendo executada e paga a cada
tick.

Sobreviveu porque nenhum teste passava `similarity_probe=` ao pipeline.

O código correto:

```python
if self._similarity_probe is not None and inputs.similarity is None:
    try:
        probed = await self._similarity_probe.probe(inputs)
    except Exception:
        # BROAD ON PURPOSE. An earlier revision narrowed this to
        # (OSError, RuntimeError, ValueError, TimeoutError) ... but
        # SQLAlchemy/asyncpg errors derive straight from Exception and
        # match NONE of those, so the narrow form let a real database
        # outage escape and kill the whole tick.
        logger.exception("similarity_probe_failed", ...)
    else:
        inputs = dataclasses.replace(inputs, similarity=probed)
```

**Duas lições aqui, e a segunda é auto-infligida.** Ao corrigir, o
`except` foi estreitado para "parar de mascarar bugs" — e isso estava
**errado**: erros de SQLAlchemy descendem direto de `Exception` e não
casavam com nenhum dos tipos listados, então uma queda real do pgvector
passaria a matar o tick inteiro. Foi revertido para o `except` amplo.

A regra que ficou: **não estreite uma cláusula de isolamento cujo
trabalho é sobreviver a falha de infraestrutura.** O erro de programação
(mutar um frozen dataclass) foi eliminado *por construção*, com
`dataclasses.replace`, que é onde esse tipo de bug pertence.

### Outros bugs corrigidos que valem conhecer

- **Vazamento de alvo:** o `report_builder` filtrava com
  `kickoff_at <= query.kickoff_at`, mantendo a própria partida analisada
  dentro da sua baseline — enquanto o `signal_engine` rotulava a
  evidência como "leakage-safe".
- **Incerteza não-monotônica:** o score era a **média** dos componentes
  de deficiência, então cada problema adicional *diluía* os outros.
  Medido: "sem odds" dava 1,00; "sem odds **e** fonte única" dava 0,75.
  Virou noisy-OR: `1 - Π(1-cᵢ)`.
- **Cooldown com chave insuficiente:** `trend:{match}:{type}` descartava
  emissões de detectores que emitem vários por tick (MarketAnomaly emite
  um por casa de aposta).

---

## 8. Quality Gate — o portão de promoção

Em `atlas/backtest/`. Roda um **replay determinístico** do pipeline de
inteligência sobre dados históricos reais e produz uma avaliação.

```
ReplayScenario → ReplayEngine → ReplayResult
                                     │
                                     ▼
                            QualityEvaluation
                            ├─ DetectorReport (por detector)
                            ├─ StageEvaluation (por etapa)
                            ├─ QualityReport (métricas)
                            ├─ RegressionReport (diff vs baseline)
                            ├─ PromotionReport (Approved/Warning/Rejected)
                            └─ ExplainabilityReport
```

### O determinismo é real

O `_fingerprint` foi verificado empiricamente: cinco ordenações
embaralhadas produzem um único hash. Linhas ordenadas, precisão fixa em
`.6f`, sem timestamps nem UUIDs.

**Mas o escopo dele é estreito, e isso está documentado:** cobre apenas
`(step_index, trend_type, strength, confidence, direction)`. **Não**
cobre evidência, significado, publish_score nem lifecycle. Um
`ReplayHash` inalterado **não** prova que o payload publicado não mudou
— para isso, use o `RegressionDiff`.

### Bugs que o próprio gate tinha

- **O veredito contradizia o relatório.** `_promotions` avaliava só
  `diff.lost_detections`, então um candidato que mantinha todas as
  detecções mas **enfraquecia todas** era carimbado *"Approved — no
  regression"* enquanto o mesmo `RegressionReport` trazia
  `confidence_regression=True`. Hoje existe `_degraded_types()` e o
  veredito vira `Warning`.
- `quality_regression` era `detector_reg or downward or similarity_reg` —
  o `reasoning_reg` era calculado e **descartado**.
- `behavior_consistency = 1.0 if behavior else 1.0` — os dois ramos
  idênticos, uma constante disfarçada de cálculo.

### A aprovação humana, que não existia

O documento exige aprovação humana. **Não havia implementação alguma
disso**: o gate produzia vereditos que nenhum código consumia, e não
existia tabela, coluna ou campo registrando que alguém aprovou algo.

Hoje existe a tabela `atlas.promotion_decisions`
(migration `0020`), e três decisões de projeto merecem atenção:

**1. A chave é o `replay_hash`, não o `execution_id`.**

```sql
CONSTRAINT ux_promotion_decisions_replay_hash UNIQUE (replay_hash)
```

O `ReplayService` guarda execuções em dicionários **em memória**; um
`execution_id` deixa de resolver no primeiro restart. O fingerprint
determinístico identifica o comportamento avaliado para sempre.

**2. A linha congela o que o gate recomendou.** Como a avaliação vive só
em memória, sem esse retrato a justificativa da decisão fica impossível
de conferir depois.

**3. Duas regras são forçadas em `check()`:**

```python
# aprovar contra um veredito Rejected OU com quality_regression
#   exige override_recommendation explícito
# aprovar sem baseline exige acknowledge_no_baseline
```

E, deliberadamente, **rejeitar não exige nenhum dos dois** — recusar
promoção é sempre seguro e não pode ser mais difícil que aprovar.

Ambos viram **coluna própria**, não JSON: "quem aprovou contra o gate" é
a consulta que um auditor faz.

---

## 9. Superfície HTTP

| Rota | Para quê |
|---|---|
| `GET /health`, `/ready` | Saúde. `/ready` também afere o consumer |
| `POST /v1/context` | **O produto:** contexto de uma partida |
| `/v1/internal/intelligence/*` | Leituras históricas de inteligência |
| `/atlas/*` | Execução em runtime (conflicts, ingestion, reasoning…) |
| `/backtests*` | Quality Gate: submeter replay, ler qualidade, **decidir** |
| `/v1/meta/features`, `/models` | Metadados |
| `/v1/meta/strength`, `/embeddings` | Estado do motor de força e cobertura v1/v2 |

Autenticação: `X-Internal-Token` em tudo. Atribuição: `X-Operator`,
preenchido pelo Control Plane.

> **Pegadinha do FastAPI que já mordeu:** `GET /backtests/decisions`
> precisa ser declarado **antes** de `GET /backtests/{execution_id}`. O
> FastAPI casa por ordem de declaração, e a rota paramétrica engoliria
> o path literal, procurando uma execução chamada "decisions".

---

## 10. Configuração

| Variável | Obrigatória | Observação |
|---|---|---|
| `INTERNAL_TOKEN` | sim | mín. 16 caracteres |
| `DATABASE_URL` | sim | Postgres **com pgvector** |
| `REDIS_URL` | sim | |
| `ATLAS_ANVIL_API_BASE_URL` | sim | |
| `ATLAS_ANVIL_API_KEY` | sim | mín. 32 caracteres |
| `ATLAS_ANVIL_FEATURES_PATH_PREFIX` | não | `/internal/features` quando o Anvil é local |
| `ATLAS_ANVIL_API_KEY_HEADER` | não | `x-anvil-api-key` quando o Anvil é local |
| `ATLAS_EXPLORER_DATA_ROOT` | não | `/var/atlas/explorer` |
| `ATLAS_REGRESSION_BASELINE_PATH` | não | Vazio = sem seção de regressão |

**`pgvector` não é opcional.** A imagem `postgres:16-alpine` não tem a
extensão, e a migration `0013` morre com *"extension vector is not
available"*. Use `pgvector/pgvector:pg16`.

**Os dois settings do Anvil são um par.** Configurar um e não o outro
falha — e as falhas parecem coisas diferentes: 404 (path errado) e 401
(header errado, que parece chave errada). Detalhes na
[Parte 4](04-insight-anvil.md).

---

## 11. Relacionamentos

```
  Explorer ──volume :ro──►  ┌─────────┐  ──derived stream──►  Anvil
                            │  ATLAS  │  ◄──features API────┘
  Sport Hub ──Redis──────►  └────┬────┘
                                 │
                                 ├──► insight:stream:trends ──► Nexus
                                 │
                                 └──► Postgres (pgvector) + Redis

  Control Plane ──X-Internal-Token──► Atlas
```

O ciclo Atlas → Anvil → Atlas é intencional: o Atlas produz o histórico
analítico e depois o consulta para contextualizar o presente.

---

## 12. Uma nota sobre o ambiente de desenvolvimento

`atlas/operations.py` importa o módulo `resource`, que **só existe em
POSIX**. Qualquer teste que importe `atlas.api.*` quebra a coleta da
suíte inteira no Windows.

Isso **não** foi corrigido de propósito: produção roda em Linux, onde o
módulo existe nativamente. A convenção é não escrever testes que
importem `atlas.api.*` — teste a camada abaixo, que é onde a lógica
está de qualquer forma.

---

## Próximo passo

**[Parte 4 — Insight Anvil](04-insight-anvil.md)**: onde o histórico
analítico é persistido.
