# Dataset Manifest — schema V1

O manifesto congela um conjunto validado. Ele existe para responder uma
pergunta que só aparece depois de o motor estar rodando há meses:

> **este resultado saiu de quais bytes?**

Sem manifesto, a resposta é uma reconstrução — consultar o banco hoje e supor
que o dataset não mudou. Ele mudou: um arquivo foi acrescentado, a licença
corrigida, a versão do validador subiu. A suposição não falha, ela só fica
errada — e é assim que uma investigação de regressão persegue uma diferença
que não está onde se procura.

---

## Schema

```jsonc
{
  "schema_version": "1.0",

  "dataset": {
    "id":                     "9f2b6f3e-…",   // uuid5(nome, versão)
    "name":                   "premier-league-2019-2024",
    "version":                "v1.0",
    "declared_competitions":  ["PREMIER_LEAGUE"],   // ordenado
    "declared_seasons":       ["2019-2020", "2020-2021"]  // ordenado
  },

  "files": [                                  // ordenado por sha256
    {
      "file_id":      "3c1e…",                // uuid5(dataset, versão, sha256)
      "filename":     "E0.csv",               // nome SANITIZADO
      "format":       "CSV",
      "sha256":       "a3f5…",                // 64 hex, minúsculo
      "size_bytes":   1048576,
      "row_count":    380,                    // null antes da inspeção
      "column_count": 22                      // null antes da inspeção
    }
  ],

  "source": {
    "name":          "football-data.co.uk",
    "type":          "OPEN_DATA",             // OPEN_DATA | COMMERCIAL_PROVIDER | MANUAL
    "license_class": "ATTRIBUTION_REQUIRED",
    "url":           "https://…",             // ou null
    "retrieved_at":  "2026-08-01T10:00:00+00:00"
  },

  "validation": {
    "id":                "b7d2-…",            // a EXECUÇÃO, não o conteúdo
    "status":            "PASSED_WITH_WARNINGS",
    "validator_version": "v1.0",
    "rows_observed":     380,
    "issue_count":       2
  }
}
```

---

## Campos

### `dataset`

| Campo | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | `uuid` | nunca | derivado de (nome, versão) |
| `name` | `str` | nunca | slug minúsculo, 3–63 caracteres |
| `version` | `str` | nunca | `vMAJOR.MINOR` |
| `declared_competitions` | `str[]` | nunca, ≥1 | do catálogo fechado de 5 |
| `declared_seasons` | `str[]` | pode ser `[]` | **rótulos**, não `SeasonId` |

> `declared_*` são **declarações do operador**, não fatos verificados.
> Ninguém abriu o arquivo para conferir; quando alguém abrir, será o PR-03.
> Chamá-los de `competition_id` sugeriria um vínculo que não existe.
>
> As temporadas são **rótulos de texto** porque um `SeasonId` exigiria que a
> temporada já existisse como entidade — e no momento do upload ela pode não
> existir, porque a fonte é justamente o que vai povoá-la.

### `files`

| Campo | Tipo | Nulo? | Observação |
|---|---|---|---|
| `file_id` | `uuid` | nunca | derivado de (dataset, versão, sha256) |
| `filename` | `str` | nunca | sanitizado; o original fica no registro |
| `format` | `str` | nunca | `PARQUET` \| `CSV` \| `JSONL` |
| `sha256` | `str` | nunca | 64 hex minúsculos, dos **bytes recebidos** |
| `size_bytes` | `int` | nunca | > 0 |
| `row_count` | `int` | **sim** | ausente até a inspeção medir |
| `column_count` | `int` | **sim** | idem |

> `row_count` ausente é `null` e **nunca** `0`: um arquivo cujas linhas não
> foram contadas não é um arquivo de zero linhas.
>
> **Só arquivos com bytes confirmados entram.** Um arquivo em `PENDING` é uma
> promessa, e um manifesto que listasse promessas afirmaria ter provado o que
> não provou.
>
> **`object_key` NÃO está aqui, de propósito.** É a topologia do bucket, e
> publicá-la convida alguém a construir uma URL a partir dela — o arquivo
> bruto não tem caminho de leitura pela API.

### `source`

| Campo | Tipo | Nulo? |
|---|---|---|
| `name` | `str` | nunca |
| `type` | `str` | nunca |
| `license_class` | `str` | nunca |
| `url` | `str` | sim |
| `retrieved_at` | ISO-8601 UTC | nunca |

> `retrieved_at` é **quando nós baixamos**, não quando a fonte publicou. Fonte
> pública corrige o passado em silêncio: o mesmo endereço devolve conteúdo
> diferente em março e em agosto. O carimbo de coleta é o que explica por que
> dois datasets do mesmo endereço têm hashes diferentes.

### `validation`

| Campo | Tipo | Observação |
|---|---|---|
| `id` | `uuid` | identifica a **execução** |
| `status` | `str` | `PASSED` \| `PASSED_WITH_WARNINGS` \| `PASSED_WITH_ERRORS` \| `BLOCKED` |
| `validator_version` | `str` | `vMAJOR.MINOR` |
| `rows_observed` | `int` | soma das linhas inspecionadas |
| `issue_count` | `int` | o **total**, não o tamanho da amostra |

> A versão do validador viaja aqui porque **o validador muda**. Um arquivo
> aprovado pela v1.0 e reprovado pela v1.1 não mudou — mudou o que sabemos
> procurar. Sem a versão gravada, a diferença entre dois relatórios pareceria
> uma mudança no arquivo, e alguém iria procurar o que não existe.

---

## Serialização canônica e impressão

```
ManifestFingerprint = SHA256( canonical_json(manifest) )
```

A serialização é determinística por construção:

| Regra | Por quê |
|---|---|
| `sort_keys=True` | a ordem de inserção de um dict é estável; a de reconstrução a partir do banco não é |
| `separators=(",", ":")` | um espaço a mais muda o hash |
| `ensure_ascii=False` | nome de fonte tem acento, e escapá-lo produziria impressões diferentes conforme o serializador |
| UTF-8 | uma codificação só |
| arquivos ordenados por `sha256` | o mesmo conjunto lido em outra ordem daria outra impressão |

### O que fica **fora** do que é hasheado

`created_at` e o id do próprio manifesto. Os dois mudam a cada emissão sem que
nada do conteúdo mude, e incluí-los faria dois manifestos do mesmo conjunto
terem impressões diferentes — que é o contrário do que uma impressão serve
para fazer.

### O que fica **dentro**, deliberadamente

`validation.id`. Duas validações do mesmo conteúdo pela mesma versão do
validador produzem manifestos com impressões distintas — e é o que se quer: o
manifesto prova qual **execução** gerou o resultado, e duas execuções são duas
coisas.

Para a outra pergunta — *é a mesma entrada?* — existe
`describes_same_input_as()`, que compara os hashes dos arquivos e ignora a
execução. As duas perguntas são legítimas e são perguntas diferentes.

### Verificação independente

A API devolve o manifesto na forma **canônica**, mais a impressão. É a mesma
forma que foi hasheada, então o cliente pode reserializá-la e conferir por
conta própria:

```bash
curl -s .../datasets/<id>/manifest | jq -c -S .body \
  | tr -d ' ' | sha256sum
```

Devolver uma forma diferente da que gerou o hash tornaria a verificação
independente impossível.

---

## Emissão e persistência

- Emitido **apenas** quando a validação passa sem impeditivos. Um manifesto
  para dataset inválido afirmaria ter congelado um conjunto estruturalmente
  apto, e ele não é.
- **Append-only.** `dataset_manifests` tem a impressão como chave primária e
  `ON CONFLICT DO NOTHING`: reemitir o mesmo manifesto produz a mesma linha.
- A forma **persistida** difere da canônica: ela guarda `created_at` e o
  `schema_version` também, para que o manifesto volte do banco idêntico ao que
  foi emitido. Se a persistida fosse a canônica, `created_at` se perderia.

---

## Evolução

`schema_version` sobe quando um campo **muda de significado** — nunca quando
um campo novo é acrescentado no fim. Ela existe para que um manifesto lido em
2028 diga por qual regra foi escrito: sem isso, acrescentar um campo mudaria a
impressão de todo manifesto reemitido, e a mudança pareceria mudança de
conteúdo.

Um manifesto que cite uma competição fora do catálogo é **recusado** na
leitura, não ignorado: ele foi escrito por uma versão que conhecia mais do que
esta, e seguir em frente descartando o que não se entende produz um conjunto
menor que passa por completo.
