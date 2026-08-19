# PR-04 — Data Quality & Historical Canonical Build · checklist de fechamento

Conferência do **DoD ORIGINAL do PR-04**, item a item. Escrita ao fim do
PR-04.3 e **atualizada no PR-04.4.1**, que avançou o blocker de eventos sem
fechá-lo.

> **Qualquer requisito original não entregue aparece aqui como BLOCKER, e não é
> reclassificado como dívida.** Um item rebaixado silenciosamente para «dívida»
> é um item que ninguém volta a olhar — e o PR-04 é a fundação de tudo que o
> PR-05 vai ler.

O PR-04 foi entregue em cinco incrementos:

```
PR-04.1   Quality Domain Foundation
PR-04.2   Quality Execution & Canonical Build Core
PR-04.2.1 Final Closure & Repository Integrity Hardening
PR-04.3   Historical Corpus Materialization, Manifest, Interfaces & Production Proof
PR-04.3.1 Corpus Integrity & Final Closure
PR-04.4.1 Historical Event Contract & Canonicalization Pipeline
```

**Três categorias, e nenhuma quarta vaga** (§52):

```
DONE                             entregue e verificado
NOT_APPLICABLE_WITH_JUSTIFICATION  não se aplica, e o porquê está escrito
BLOCKED                          aplicável, não entregue, e não reclassificado
```

---

## 1. Domínio de qualidade

| # | requisito original | onde | estado |
|---|--------------------|------|--------|
| 1.1 | Qualidade em EIXOS, nunca num score único | `domain/quality/dimensions.py` — `QualityVector`, seis eixos | ✅ PR-04.1 |
| 1.2 | Cobertura separada de qualidade, e ela NÃO reprova | `domain/quality/coverage.py` — `CoverageReport` | ✅ PR-04.1 |
| 1.3 | Cobertura com três estados, `expected` nulo quando não há denominador | `MEASURED` / `AVAILABILITY_ONLY` / `NOT_DECLARED` | ✅ PR-04.1 |
| 1.4 | Licença separada de qualidade, POR FAMÍLIA | `domain/quality/licensing.py` — `LicenseFootprint` | ✅ PR-04.1 |
| 1.5 | Veredito de uso PRÓPRIO por escopo (pesquisa / comércio) | `UsageVerdict` | ✅ PR-04.1 |
| 1.6 | Catálogo fechado de problemas, sem severidade no problema | `domain/quality/issues.py` | ✅ PR-04.1 |
| 1.7 | Política versionada, com pisos por eixo e por sujeito | `domain/quality/policy.py` | ✅ PR-04.1 |
| 1.8 | Elo mais fraco, nunca média | `QualityVector.weakest` | ✅ PR-04.1 |
| 1.9 | Avaliação por PARTIDA, nunca por dataset | `MatchQualityAssessment` | ✅ PR-04.1 |

## 2. Execução de qualidade persistida

| # | requisito original | onde | estado |
|---|--------------------|------|--------|
| 2.1 | `QualityRun` com fusões consumidas e impressão da saída de cada uma | `domain/quality/runs.py`, migration 0005 | ✅ PR-04.2 |
| 2.2 | Versão E impressão da política gravadas | `policy_version` + `policy_fingerprint` | ✅ PR-04.2 |
| 2.3 | Execução concluída IMUTÁVEL | `UPDATE ... WHERE status = 'RUNNING'`, teste de arquitetura | ✅ PR-04.2 |
| 2.4 | Vereditos persistidos com cobertura, licenças, identidade e problemas | 5 tabelas, migration 0005 | ✅ PR-04.2 |
| 2.5 | Severidade gravada junto do problema, vinda da política | coluna `severity`, `append_many(policy=…)` | ✅ PR-04.2 |
| 2.6 | Ator de serviço nomeado pelo que ELE É | `QUALITY_ASSESSOR`, sem `system`/`root`/`admin` | ✅ PR-04.2 |
| 2.7 | Processamento em lote, sem N+1 | 7,0 consultas/lote medidas | ✅ PR-04.2 |

## 3. Construção canônica

| # | requisito original | onde | estado |
|---|--------------------|------|--------|
| 3.1 | `CanonicalBuildPolicy` decide; construtor consome | `domain/build/policy.py`, ADR-0024 | ✅ PR-04.2 |
| 3.2 | Escrita REAL no registro canônico PostgreSQL | `PostgresCanonicalRegistryWriter` | ✅ PR-04.2 |
| 3.3 | Equivalência antes de reuso; conflito RECUSADO, nunca sobrescrito | `MatchWriteOutcome` — 3 desfechos | ✅ PR-04.2 |
| 3.4 | Builds de pesquisa e comercial coexistem sobre a MESMA avaliação | `DEFAULT_RESEARCH_/COMMERCIAL_BUILD_POLICY` | ✅ PR-04.2 |
| 3.5 | Exclusão de família por licença com MOTIVO e LICENÇA rastreáveis | `canonical_build_family_decisions`, ADR-0025 | ✅ PR-04.2 |
| 3.6 | Linhagem por fato até o byte bruto | `canonical_build_records` → avaliação → fusão → `record_ref` → SHA-256 | ✅ PR-04.2 |
| 3.7 | Execuções imutáveis, contagens que fecham | constraint `build_runs_contagens_fecham` | ✅ PR-04.2 |
| 3.8 | Ausente é `NULL`, nunca zero | `CanonicalOddsObservation.observed_at`, colunas nuláveis | ✅ PR-04.2 |

## 4. Fronteira identidade × procedência factual

| # | requisito original | onde | estado |
|---|--------------------|------|--------|
| 4.1 | Rótulo de identidade NÃO contamina a pegada de licença | `SemanticRole.is_identity_label` | ✅ PR-04.2.1 |
| 4.2 | Fonte restrita ÚNICA de um fato do núcleo NÃO vira comercialmente livre | `CORE_ROLES` inclui `KICKOFF` | ✅ PR-04.2.1 |
| 4.3 | Confirmação ≠ derivação | `LicenseFootprint.independent_support`, coluna `independent` | ✅ PR-04.2.1 |

## 5. Corpus histórico publicado

| # | requisito original | onde | estado |
|---|--------------------|------|--------|
| 5.1 | `HistoricalCanonicalDataset` e versões separados | `domain/corpus/versions.py`, ADR-0026 | ✅ PR-04.3 |
| 5.2 | Versão publicada IMUTÁVEL | grafo sem `DRAFT → READY`, `assert_mutable` | ✅ PR-04.3 |
| 5.3 | Pertinência GRAVADA, nunca derivada | `historical_canonical_members` | ✅ PR-04.3 |
| 5.4 | Manifesto completo e determinístico | `HistoricalCanonicalManifest`, contrato V1 | ✅ PR-04.3 |
| 5.5 | Impressão determinística do corpus, independente do lote | `compute_corpus_fingerprint` + XOR-fold | ✅ PR-04.3 |
| 5.6 | Parquet canônico opcional, particionado, schema explícito | `ParquetCorpusMaterializer`, ADR-0027 | ✅ PR-04.3 |
| 5.6b | Objetos escritos ficam CONSULTÁVEIS, e não só descritos | `historical_canonical_objects`, `record_objects` | ✅ PR-04.3 |
| 5.7 | Control API e CLI, pelos MESMOS casos de uso | `routes/corpus.py`, `cli/corpus.py`, teste de superfície | ✅ PR-04.3 |
| 5.8 | Gate `READY` que confere contra o BANCO | `PublishCorpusVersion._conferir` | ✅ PR-04.3 |
| 5.9 | Versão anterior SUPERADA e ainda legível | `supersede`, `is_readable_corpus` | ✅ PR-04.3 |
| 5.10 | Travessia de linhagem do corpus ao byte bruto | teste E2E `test_do_corpus_ate_o_arquivo_bruto` | ✅ PR-04.3 |

## 5-bis. Integridade do corpus (PR-04.3.1)

| # | requisito | onde | estado |
|---|-----------|------|--------|
| 5b.1 | Impressão sem as propriedades lineares do XOR | `domain/corpus/fingerprint.py` — SHA-256 sobre serialização ordenada | ✅ DONE |
| 5b.2 | Ordem canônica explícita, imposta e VERIFICADA | `ORDER BY match_id` + guarda estritamente crescente | ✅ DONE |
| 5b.3 | Framing não ambíguo | `frame()` com rótulo e prefixo de tamanho | ✅ DONE |
| 5b.4 | Separador de domínio | `INSIGHT:HISTORICAL_CANONICAL_CORPUS:FINGERPRINT:V1` | ✅ DONE |
| 5b.5 | Hash incremental, memória O(lote) | `CorpusFingerprintBuilder` | ✅ DONE |
| 5b.6 | Algoritmo e versão do contrato nomeados | `canonical-sha256-v1` / `1.0`, no manifesto e na tabela | ✅ DONE |
| 5b.7 | Serialização determinística de UUID, instante e Decimal | `uuid_text`, `instant_text`, `decimal_text` | ✅ DONE |
| 5b.8 | `DISTINCT ON` não decide semântica | removido; composição em `domain/corpus/composition.py` | ✅ DONE |
| 5b.9 | Fatos equivalentes → reuso + linhagem múltipla | `historical_canonical_member_builds` | ✅ DONE |
| 5b.10 | Famílias complementares → união determinística | `compose()` mescla, não elege portador | ✅ DONE |
| 5b.11 | Fatos conflitantes → publicação bloqueada | `divergences()` + `ConflictError` | ✅ DONE |
| 5b.12 | Escopos de uso incompatíveis são recusados antes de escrever | `_assert_escopos_compativeis` | ✅ DONE |
| 5b.13 | Comparação de fatos por Value Object, nunca `repr()` | `factual_form()` + serialização canônica | ✅ DONE |
| 5b.14 | Rótulo continua não sendo fato | `factual_form` carrega `TeamId`, não a grafia | ✅ DONE |

## 6. Prova de produção

| # | requisito original | onde | estado |
|---|--------------------|------|--------|
| 6.1 | E2E do bruto ao `READY`, com PostgreSQL e MinIO reais | `tests/integration/test_historical_corpus_e2e.py` — 21 testes | ✅ PR-04.3 |
| 6.2 | Benchmark de 10.000 partidas | 12.500 registros → 10.000 partidas, 17,2 s | ✅ PR-04.3 |
| 6.3 | Documento de baseline | `docs/performance/PR04_CANONICAL_CORPUS_BASELINE.md` | ✅ PR-04.3 |
| 6.4 | Suíte de performance completa VERDE | 25 testes, exit 0 | ✅ PR-04.3 |
| 6.5 | Integridade do repositório: tudo essencial versionado | `test_repository_integrity.py` | ✅ PR-04.2.1 |
| 6.6 | Prova de clone limpo / construibilidade | export da árvore rastreada + import isolado | ✅ PR-04.2.1 |
| 6.7 | ruff, mypy strict e pytest verdes | ver §relatório | ✅ PR-04.3 |
| 6.8 | ADRs registrando as decisões | 0023, 0024, 0025 (+emenda), 0026, 0027 | ✅ PR-04.3 |

---

## 7. Canonicalização de eventos (PR-04.4.1)

Este bloco **não estava no DoD original como incremento próprio** — ele nasceu
da Opção A da análise de capacidade. Ele avança o blocker de eventos; não o
fecha.

| # | requisito | onde | estado |
|---|-----------|------|--------|
| 7.1 | Papéis semânticos de evento, catálogo FECHADO | 22 papéis `EVENT_*`, `SemanticRole.is_event` | ✅ PR-04.4.1 |
| 7.2 | Forma do registro DECLARADA, nunca inferida | `RecordKind`, migration 0010, ADR-0028 | ✅ PR-04.4.1 |
| 7.3 | Contrato de fonte de eventos com `missing` ≠ `weak` ≠ `misplaced` | `EventContractReport`, `inspect_contract` | ✅ PR-04.4.1 |
| 7.4 | Leitura linha-por-evento sobre o leitor do PR-02 | `EventRowReader` — sem pilha paralela | ✅ PR-04.4.1 |
| 7.5 | Referências traduzidas em LOTE, sem N+1 | 3 consultas por lote, medidas | ✅ PR-04.4.1 |
| 7.6 | Elegibilidade com guardas ordenadas e motivo fechado | `EventExclusionReason`, 8 motivos | ✅ PR-04.4.1 |
| 7.7 | Identidade canônica DERIVADA, reprocessamento idempotente | `uuid5(match, source_key, revision)` | ✅ PR-04.4.1 |
| 7.8 | Ordem canônica que não depende do arquivo nem do lote | `ordering_key` + sequência por `(partida, período)` | ✅ PR-04.4.1 |
| 7.9 | Correção ≠ cancelamento | `CORRECTED` vs `CANCELLED`, ADR-0013 | ✅ PR-04.4.1 |
| 7.10 | Observado ≠ derivado: xG da fonte, três estados | `FeatureValue`, ADR-0009 | ✅ PR-04.4.1 |
| 7.11 | Linhagem por evento, inclusive do que NÃO entrou | `canonical_event_build_records` | ✅ PR-04.4.1 |
| 7.12 | Execução persistida, imutável, com contagens que fecham | `canonical_event_build_runs` + constraint | ✅ PR-04.4.1 |
| 7.13 | Benchmark de 100.000 registros de evento | 39,4 s · 2.536 ev/s · 30 MB · 602 consultas | ✅ PR-04.4.1 |
| 7.14 | Três tamanhos de lote medidos, default justificado | 250 / 1.000 / 5.000 | ✅ PR-04.4.1 |
| 7.15 | Documento de baseline | `docs/performance/PR0441_EVENT_CANONICALIZATION_BASELINE.md` | ✅ PR-04.4.1 |
| 7.16 | ADR da decisão de forma | ADR-0028 | ✅ PR-04.4.1 |
| 7.17 | Pertinência de evento no corpus, Parquet, manifesto | — | ❌ PR-04.4.2 |
| 7.18 | Resolução de evento entre provedores | — | ❌ fora de escopo declarado |

## Itens do escopo ORIGINAL que NÃO foram entregues

### BLOCKED — eventos canônicos NO CORPUS

**O estado mudou no PR-04.4.1, e mudou pela metade.** A escolha registrada
como «Opção A» na análise de capacidade foi executada: existe hoje um pipeline
completo de canonicalização de eventos, do contrato de fonte ao PostgreSQL. O
que **não** existe é a integração desses eventos ao corpus publicado.

| estágio | estado |
|---------|--------|
| papéis semânticos de evento (22, `EVENT_*`) | ✅ PR-04.4.1 |
| contrato de fonte linha-por-evento (`RecordKind`) | ✅ PR-04.4.1 |
| leitura linha-por-evento | ✅ PR-04.4.1 |
| elegibilidade por evento (5 guardas ordenadas) | ✅ PR-04.4.1 |
| `CanonicalEventBuilder`, identidade derivada | ✅ PR-04.4.1 |
| `canonical_match_events` + linhagem por evento | ✅ PR-04.4.1 |
| **pertinência de evento no corpus** | ❌ **BLOCKED** |
| **`events.parquet`** | ❌ **BLOCKED** |
| **contagem de eventos no manifesto** | ❌ **BLOCKED** |
| **resolução de evento entre provedores** | ❌ fora de escopo declarado |

A análise estágio a estágio, com o histórico da classificação anterior, está em
[`docs/data/EVENT_CAPABILITY_ANALYSIS.md`](../data/EVENT_CAPABILITY_ANALYSIS.md).

**Por que isto não fecha o PR-04.** O DoD original fala de eventos **no build
canônico histórico**, e um build histórico é uma versão publicada do corpus.
Eventos que existem no PostgreSQL e não aparecem em nenhuma versão não
satisfazem esse requisito: quem lê o corpus continua sem eles, e o manifesto
continua reportando `NOT_DECLARED` — corretamente.

**Por que isto também não é `NOT_APPLICABLE`:** eventos são dado de futebol
real e o motor vai precisar deles.

**Consequência, atualizada:** features que leem eventos **do PostgreSQL** por
partida deixaram de estar bloqueadas. Features que dependem de eventos
**publicados numa versão** — leitura analítica pelo Parquet, contagem no
manifesto, reprodutibilidade por versão — continuam bloqueadas até o
PR-04.4.2.

```
PR-04 STILL BLOCKED
blocker único: canonical EVENT corpus integration (PR-04.4.2)
                pipeline de canonicalização: ENTREGUE no PR-04.4.1
```

---

## NOT_APPLICABLE_WITH_JUSTIFICATION

### `PLAYER` como família independente do corpus

A identidade canônica de jogador existe e é resolvida desde o PR-03; jogadores
entram no corpus **por referência**, dentro de `LINEUP`. Atributos de jogador
são DIMENSÃO canônica, não fato de partida — publicá-los como família do corpus
histórico misturaria dimensão com fato.

### `SPATIAL` como família independente

Coordenadas são atributo de evento (`PitchCoordinate` vive em
`domain/events/`). O registro canônico de eventos **já as guarda** desde o
PR-04.4.1 — par completo, intervalo `[0,1]`, referencial declarado. O que
continua ausente é a família `SPATIAL` **no corpus publicado**. **Bloqueada
junto com a integração de eventos, e não separadamente.**

### `TRACKING` na V1

Fora do escopo por decisão do PR-04.1 §20. O catálogo a NOMEIA para que a
ausência seja declarada em vez de esquecida, e o manifesto a reporta como
`NOT_DECLARED` — que é distinguível de «0% de cobertura».

---

## Fronteiras declaradas e verificadas por teste

Não são requisitos não entregues; são propriedades do desenho atual, com teste
que as fixa:

### F2 — O `Match` canônico normalmente é REUSADO, não inserido

No pipeline atual a resolução casa contra o registro canônico existente, então
só o que já foi resolvido chega à fusão (ADR-0022). O desfecho normal do build
é `REUSED_EQUIVALENT`. **O caminho de `INSERTED` existe e é testado**; ele
passa a ser o normal quando a resolução puder criar partida nova, que é uma
decisão de outra fase.

### F3 — Publicação síncrona

`POST /versions` compõe de forma síncrona, como a validação do PR-02 e a
resolução do PR-03. O contrato já suporta a troca por worker — a versão tem id
próprio e estado persistido, então passar a responder `202` com o mesmo id é
trocar quem executa, e não o que o cliente vê.

---

## Observação de higiene do repositório

A árvore **não** está `ruff format`-limpa: 111 arquivos anteriores a este PR
divergem do `line-length = 100` configurado. **Não é regressão de nenhum destes
PRs** — o gate do projeto é `ruff check .` (ver `Makefile`), e ele passa. Rodar
`ruff format` sobre a árvore inteira teria acrescentado 111 arquivos de ruído a
um PR sobre outra coisa, tornando-o irrevisável; a formatação em massa merece
um commit próprio, e fica registrada aqui em vez de acontecer em silêncio.

**No PR-04.4.1 isso voltou a acontecer e foi revertido.** Um `ruff format`
sobre `src/` reformatou 61 arquivos alheios ao PR. A reversão foi feita por
critério verificável, e não por inspeção visual: para cada arquivo, se
`format(versão do HEAD) == format(versão atual)`, então a única diferença era
de layout — formatação preserva tokens — e o arquivo foi restaurado do HEAD.
Os 4 arquivos com mudança real de conteúdo (`adapters/postgres/resolution.py`,
`domain/sources/mapping.py`, `domain/sources/semantics.py`,
`tests/support/pipeline.py`) permaneceram.

---

## Gate

```
PR-04 STILL BLOCKED
```

O único blocker é a **integração de eventos ao corpus publicado**
(`PR-04.4.2`). O pipeline de canonicalização que ele pressupõe foi entregue e
verificado no PR-04.4.1 — 100.000 registros contra PostgreSQL real. Tudo o
mais — os 45 itens do DoD original mais os 14 do PR-04.3.1 — está `DONE` e
verificado.
