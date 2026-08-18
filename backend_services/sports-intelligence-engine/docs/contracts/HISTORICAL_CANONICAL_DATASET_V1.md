# Historical Canonical Dataset — contrato V1

O corpus histórico visto de fora: como criá-lo, compor uma versão, publicá-la
e lê-la — pela Control API ou pela CLI, que entram pelos mesmos casos de uso.

> **Um corpus `READY` pode ser LIDO.** Ele não tem feature, não tem
> `MatchStateVector`, não está indexado. Toda resposta desta API diz
> `vector_active: false`, e não é decoração: deixar o consumidor inferir isso é
> como a próxima fase começa a ser usada antes de existir.

---

## As duas entidades

```
HistoricalCanonicalDataset          um NOME estável         `historical-core`
HistoricalCanonicalDatasetVersion   um CONTEÚDO imutável    `v1.0`
```

O nome é um ponteiro que dura anos; a versão é um fato que nunca muda
(ADR-0026).

---

## O ciclo de vida

```
DRAFT ──▶ BUILDING ──▶ VALIDATING ──▶ READY ──▶ SUPERSEDED
  │           │             │
  └───────────┴─────────────┴──▶ FAILED
```

| estado        | o que significa                                   | legível? |
|---------------|---------------------------------------------------|----------|
| `DRAFT`       | declarada, sem conteúdo                           | não      |
| `BUILDING`    | materializando pertinência e objetos              | não      |
| `VALIDATING`  | conteúdo pronto, conferindo                       | não      |
| `READY`       | conferida e congelada                             | **sim**  |
| `FAILED`      | falhou em qualquer etapa                          | não      |
| `SUPERSEDED`  | uma versão mais nova a substituiu                 | **sim**  |

**`DRAFT → READY` não existe.** Uma versão que nunca materializou nem conferiu
não pode se declarar publicada, e a recusa mora no grafo — não num `if`.

**`SUPERSEDED` continua legível.** Um resultado calculado sobre a 1.0 continua
explicável pela 1.0, e seria irreproduzível se ela sumisse.

---

## Control API

Prefixo `/v1/historical-corpus`. Todas exigem `X-Internal-Token` e
`X-Actor-Id` — o ator vem de quem autenticou, nunca do corpo.

### `POST /datasets`

Declara a identidade lógica. **Idempotente por nome**: um retry de rede devolve
o mesmo dataset em vez de estourar erro.

```jsonc
// requisição
{ "name": "historical-core", "description": "corpus principal" }

// 201
{ "id": "55a2…", "name": "historical-core", "description": "…",
  "created_at": "2026-08-18T12:00:00+00:00", "created_by": "ana.silva" }
```

O nome vira caminho no object store e chave de manifesto: barra e espaço são
recusados.

### `POST /datasets/{dataset_id}/versions`

Compõe a versão. **Termina em `VALIDATING`, e NÃO publicada.**

```jsonc
// requisição
{
  "version":         "1.0",
  "usage":           "RESEARCH",          // RESEARCH | COMMERCIAL
  "scope": [
    { "competition": "PREMIER_LEAGUE", "season_label": "2024/25",
      "competition_id": "3f1a…", "season_id": "9d2c…" }
  ],
  "build_run_ids":   ["…"],
  "quality_run_ids": ["…"],
  "quality_run_id":  "…",                 // de onde vêm os vereditos agregados
  "fusion_run_ids":  ["…"],
  "resolution_run_ids": ["…"]
}

// 201
{
  "version": { "id": "7b3e…", "version": "v1.0", "status": "VALIDATING",
               "match_count": 10000, "corpus_fingerprint": "8a29…",
               "vector_active": false, … },
  "members_written":   10000,
  "objects_written":   160,
  "materialized":      true,
  "corpus_fingerprint": "8a29…",
  "manifest": { /* o manifesto MONTADO, para conferência antes de publicar */ }
}
```

**Nenhum parâmetro de POLÍTICA no corpo.** Afrouxar um critério é uma política
nova COM VERSÃO — senão duas versões sob a mesma política significariam coisas
diferentes, e comparar corpus deixaria de valer.

**O escopo é DECLARADO e não descoberto.** Uma partida que os builds
produziram e o escopo não menciona reprova a composição — e a versão fica
`FAILED`, com o motivo. Ou o escopo está errado, ou os builds são os errados.

`409` quando a versão já existe: «1.0» precisa significar um conteúdo só, para
sempre.

### `POST /versions/{version_id}/publish`

**O GATE.** Confere contra o BANCO — contagem gravada, impressão recalculada,
manifesto presente — e congela.

```jsonc
// requisição — o MOTIVO é obrigatório: publicar é decisão administrativa
{ "reason": "corpus histórico 1.0", "supersede_previous": true }

// 200
{ "id": "7b3e…", "version": "v1.0", "status": "READY",
  "match_count": 10000, "manifest_id": "8c1f…",
  "corpus_fingerprint": "8a29…", "vector_active": false, … }
```

**O manifesto NÃO vem do cliente.** Ele é produzido pela composição — a única
que viu o fluxo inteiro — e lido do banco pelo gate. Aceitá-lo no corpo
permitiria publicar uma descrição que não corresponde ao conteúdo, e a
conferência estaria conferindo o que o cliente afirmou.

`409` se a versão não estiver em `VALIDATING`, ou se outra publicação chegou
primeiro.

### Leitura

| rota | responde |
|------|----------|
| `GET /datasets` | quais corpus existem |
| `GET /datasets/{id}/versions?status=&usage=` | quais versões existem, com histórico |
| `GET /datasets/{id}/latest?usage=` | qual é o corpus ATUAL daquele escopo |
| `GET /versions/{id}` | o estado de uma versão |
| `GET /versions/{id}/manifest` | a descrição completa do que ela contém |

`latest` e `versions` respondem perguntas diferentes: a primeira tem uma
resposta só e ignora `SUPERSEDED`; a segunda tem histórico e o inclui.

---

## CLI

Os MESMOS casos de uso. Uma orquestração própria por porta faria uma delas
ganhar uma verificação que a outra não tem.

```bash
engine corpus create-dataset historical-core --description "corpus principal"
engine corpus list-datasets

engine corpus build <dataset-id> \
  --version 1.0 \
  --usage RESEARCH \
  --build-run <id> \
  --quality-run <id> \
  --scope PREMIER_LEAGUE:2024/25:<competition-id>:<season-id>

engine corpus publish <version-id> --reason "corpus histórico 1.0"

engine corpus versions <dataset-id> --status READY
engine corpus manifest <version-id>
```

O escopo exige os IDS e não só os nomes: casar competição e temporada por texto
é como um fato da temporada A entra na temporada B.

---

## Layout no object store

```
corpus/<dataset>/v<versão>/
  manifest.json
  family=MATCH/competition=<C>/season=<S>/part-00000.parquet
  family=LINEUP/…
  family=ODDS/…
```

Particionamento Hive-style, ZSTD, schema explícito. É representação, não fonte
da verdade (ADR-0027) — apagá-lo não perde nada, e uma versão publicada sem ele
é `READY` do mesmo jeito.
