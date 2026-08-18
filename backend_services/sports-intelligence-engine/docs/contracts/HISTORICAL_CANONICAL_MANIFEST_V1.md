# Historical Canonical Manifest — schema V1

A descrição completa e determinística de uma versão publicada do corpus
histórico: o que está aqui dentro, de onde veio, sob quais regras, o que ficou
de fora e por quê.

> **Isto é um corpus PRONTO PARA SER LIDO.** Não é `MatchStateVector`, não há
> feature, não há índice vetorial. `HISTORICAL_CANONICAL_READY` ≠
> `HISTORICAL_VECTOR_ACTIVE` — a distância entre uma coisa e outra é o PR-05
> inteiro (ADR-0007, ADR-0026).

---

## As duas impressões, e por que confundi-las é caro

```
corpus_fingerprint   SHA-256 do CONTEÚDO SEMÂNTICO do corpus, sobre
                     serialização ORDENADA com framing e separador de domínio.
                     NÃO muda entre duas publicações independentes dos mesmos
                     fatos: nenhum carimbo de tempo, nenhum id de execução e
                     nenhuma impressão de política entram nela.
                     É ela que responde «este é o mesmo corpus?».

manifest_sha256      SHA-256 dos BYTES de `manifest.json`.
                     MUDA quando o instante de criação muda.
                     É ele que responde «este arquivo chegou íntegro?».
```

**O manifesto DIZ qual construção produziu a primeira** (`fingerprint_algorithm`
e `fingerprint_schema_version`). Sem isso, uma impressão do XOR-fold do PR-04.3
e uma da serialização ordenada são dois hex de 64 caracteres indistinguíveis, e
compará-las diria «corpus diferente» sem explicação.

Mudar a ordem canônica, o framing ou qualquer campo do que entra **exige subir
`fingerprint_schema_version`** — senão duas impressões incomparáveis passam por
comparáveis.

---

## Schema

```jsonc
{
  "id":                 "8c1f…",
  "schema_version":     "1.0",          // do FORMATO, não do dataset

  "dataset_id":         "55a2…",
  "dataset_name":       "historical-core",
  "dataset_version":    "v1.0",         // do CONTEÚDO
  "dataset_version_id": "7b3e…",

  "corpus_fingerprint": "8a293fdf…",    // 64 hex — a impressão SEMÂNTICA
  "fingerprint_algorithm":      "canonical-sha256-v1",
  "fingerprint_schema_version": "1.0",
  "created_at":         "2026-08-18T12:00:00+00:00",

  "scope": {
    "usage": "RESEARCH",                // RESEARCH | COMMERCIAL
    "entries": [                        // ordenadas canonicamente
      {
        "competition":    "PREMIER_LEAGUE",
        "season":         "2024/25",
        "competition_id": "3f1a…",      // POR ID, nunca por nome
        "season_id":      "9d2c…"
      }
    ]
  },

  "inputs": {                           // a linhagem para trás
    "build_run_ids":               ["…"],
    "quality_run_ids":             ["…"],
    "fusion_run_ids":              ["…"],
    "resolution_run_ids":          ["…"],
    "build_output_fingerprints":   ["…"],   // o QUE cada build produziu
    "build_policy_versions":       ["v1.0"],
    "build_policy_fingerprints":   ["…"],
    "quality_policy_versions":     ["v1.0"],
    "quality_policy_fingerprints": ["…"]
  },

  "counts": {
    "matches": 10000,
    "by_family":    { "MATCH": 10000, "ODDS": 8412 },
    "by_partition": { "PREMIER_LEAGUE/2024/25": 380 }
  },

  "coverage": [                         // TODAS as sete famílias, sempre
    {
      "family":            "MATCH",
      "state":             "MEASURED",  // MEASURED | AVAILABILITY_ONLY | NOT_DECLARED
      "matches_with_data":  10000,
      "matches_total":      10000,
      "available_total":    10000,
      "expected_total":     10000,
      "ratio":              1.0         // `null` quando NOT_DECLARED
    },
    {
      "family":         "TRACKING",
      "state":          "NOT_DECLARED", // e NÃO «0%»
      "matches_total":  10000,
      "ratio":          null
    }
  ],

  "coverage_by_partition": {
    "PREMIER_LEAGUE/2024/25": [ /* mesma forma de `coverage` */ ]
  },

  "quality": {                          // o PIOR caso, nunca a média
    "worst_integrity":           0.97,
    "worst_consistency":         1.0,
    "worst_completeness":        0.83,
    "worst_identity_confidence": 0.94,
    "worst_temporal_integrity":  1.0,
    "worst_provenance_quality":  0.9,
    "eligible":        9840,
    "review_required":  120,
    "ineligible":        40
  },

  "license": {
    "usage_scope":          "COMMERCIAL",
    "licenses_present":     ["PUBLIC_DOMAIN", "RESEARCH_ONLY"],
    "independent_support":  ["PUBLIC_DOMAIN"],
    "families_included":    ["MATCH"],
    "families_excluded":    ["ODDS"],
    "exclusion_reasons":    { "ODDS": { "LICENSE_POLICY": 8412 } },
    "exclusion_licenses":   { "ODDS": "RESEARCH_ONLY" },
    "requires_attribution": false
  },

  "issues": {
    "by_code":                 { "LICENSE_RESTRICTED": 8412 },
    "by_severity":             { "WARNING": 8412 },
    "records_skipped":         0,
    "records_review_required": 120,
    "families_excluded":       1,
    "examples":                ["LICENSE_RESTRICTED: match:4f8a…"]   // no máx. 10
  },

  "objects": [                          // vazio quando não há Parquet
    {
      "object_key":   "corpus/historical-core/v1.0/family=MATCH/competition=PREMIER_LEAGUE/season=2024%2F25/part-00000.parquet",
      "family":       "MATCH",
      "competition":  "PREMIER_LEAGUE",
      "season":       "2024/25",
      "sha256":       "…",
      "size_bytes":   45231,
      "row_count":    500,
      "content_type": "application/vnd.apache.parquet"
    }
  ]
}
```

---

## O que a leitura precisa saber

**`schema_version` é do FORMATO; `dataset_version` é do CONTEÚDO.** Elas mudam
por motivos diferentes — acrescentar um campo ao manifesto não é um corpus
novo. Um número só faria as duas coisas parecerem a mesma.

**`ratio` é `null` e não `0.0` quando não há denominador.** Um corpus sem
partida nenhuma não tem 0% de cobertura; ele tem cobertura indefinida. E
`NOT_DECLARED` sobrevive à agregação de propósito: «as fontes não trabalham com
eventos» e «as fontes prometeram e não veio nada» exigem ações opostas.

**`quality` é o PIOR de cada eixo, nunca a média.** Média sobre dez mil
partidas esconde cem de linhagem quebrada no terceiro decimal, e são elas que
precisam aparecer. Os assessments individuais continuam sendo a autoridade —
este resumo não os substitui.

**`licenses_present` e `independent_support` não são redundantes.** Uma fonte
`RESEARCH_ONLY` que apenas CONFIRMA um placar de domínio público aparece na
primeira — ela de fato alimentou a família — e o fato continua comercialmente
livre, porque a fonte pública o sustenta sozinha, que é o que a segunda diz.
Com uma lista só, o manifesto de um corpus comercial perfeitamente publicável
diria «contém RESEARCH_ONLY» sem qualificação, e a auditoria pararia ali
(PR-04.2.1 §42, ADR-0025).

**`issues.examples` tem teto de dez.** O manifesto descreve o corpus; despejar
um milhão de problemas nele o transformaria no corpus.

**Nada aqui é RECALCULADO.** O resumo de qualidade vem das avaliações
persistidas; o de cobertura, dos mesmos assessments; o de licença, das decisões
que o build já emitiu. Recalcular criaria uma segunda opinião sobre perguntas
já respondidas, e as duas divergiriam no primeiro ajuste de política.

---

## Serialização

Determinística por construção: chaves ordenadas, separador fixo,
`ensure_ascii=False`, UTF-8. Dois manifestos do mesmo corpus produzem os mesmos
bytes — é isso que torna `manifest_sha256` comparável.

O documento vive nos DOIS lugares: a linha em
`historical_canonical_manifests.document` responde consulta, e o
`manifest.json` no object store é o artefato que viaja junto do corpus.
