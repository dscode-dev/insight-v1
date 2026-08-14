# Fusion Output — schema V1

A saída de uma fusão: uma partida montada de várias fontes, com cada valor
sabendo quem o disse, quem discordou e sob qual regra foi escolhido.

> **Isto é um CANDIDATO.** Não é conhecimento histórico ativo, não é
> `MatchStateVector`. Falta a avaliação de qualidade e a construção canônica —
> o PR-04 — mais a barreira do ADR-0007.

---

## Schema

```jsonc
{
  "canonical_match_id": "4f8a…",
  "schema_version":     "1.0",

  "fields": [                            // ordenados por nome
    {
      "name":           "HOME_SCORE",
      "rule":           "EXACT_AGREEMENT",
      "selected_value": "2",
      "selected_from":  "fonte_a",
      "confidence":     1.0,
      "sources": [                       // ordenados por provedor
        { "provider": "fonte_a", "record": "9f2b…:3c1e…:391", "value": "2" },
        { "provider": "fonte_b", "record": "7a4d…:8b2f…:118", "value": "2" }
      ]
    },
    {
      "name":           "HOME_XG",
      "rule":           "CONFLICT_UNRESOLVED",
      "selected_value": null,            // a ausência É a informação
      "selected_from":  null,
      "confidence":     0.0,
      "sources": [
        { "provider": "fonte_a", "record": "…:391", "value": "1.8" },
        { "provider": "fonte_b", "record": "…:118", "value": "2.1" }
      ]
    }
  ],

  "observation_sets": [                  // NUNCA fundidos em valor único
    {
      "kind": "odds",
      "observations": [
        {
          "discriminator": "1X2|Casa X",
          "provider":      "fonte_c",
          "record":        "…:77",
          "values": { "ODDS_HOME": "2.00", "ODDS_DRAW": "3.40", "ODDS_AWAY": "3.60" }
        },
        {
          "discriminator": "1X2|Casa Y",
          "provider":      "fonte_c",
          "record":        "…:78",
          "values": { "ODDS_HOME": "2.05" }
        }
      ]
    }
  ]
}
```

---

## Campos

| campo | nulo? | observação |
|---|---|---|
| `name` | nunca | papel semântico, do catálogo fechado |
| `rule` | nunca | sete regras; nunca `AUTO` |
| `selected_value` | **só em `CONFLICT_UNRESOLVED`** | a ausência é a informação |
| `selected_from` | idem | |
| `confidence` | nunca | [0,1]; cresce com fontes concordantes |
| `sources` | ≥1 | TODAS as contribuições, inclusive as descartadas |

### A regra central

```sql
CONSTRAINT fused_fields_conflito_sem_valor CHECK (
    (rule = 'CONFLICT_UNRESOLVED') = (selected_value IS NULL)
)
```

Um valor num campo em conflito seria lido como se tivesse sido decidido — e
ninguém o revisaria.

### `sources` preserva o perdedor

O que a outra fonte disse **fica**. É isso que permite a alguém decidir
depois, e é o que distingue esta saída de um `dict.update`.

### `confidence` de campo

```
EXACT_AGREEMENT        min(1,0 ; 0,6 + 0,2 × fontes concordantes)
conflito resolvido     0,5   — a escolha resolveu quem vence, não a discordância
CONFLICT_UNRESOLVED    0,0
```

---

## `fields` vs `observation_sets`

| | `fields` | `observation_sets` |
|---|---|---|
| pergunta | qual é o valor certo? | quais observações existem? |
| conflito | possível | **não existe** |
| exemplo | `home_score` | odds de várias casas |

**Odds de casas diferentes não são conflito** (§54). `2.00` e `2.05` são duas
observações verdadeiras ao mesmo tempo, e a média — `2.025` — é um preço que
nenhuma casa ofereceu.

A deduplicação é por `discriminator`, e só: a mesma casa trazida por duas
fontes é uma observação; casas diferentes são duas.

---

## Impressão

```
fingerprint = SHA256( json(as_canonical, sort_keys, sem espaço, UTF-8) )
```

Determinística por construção:

| regra | por quê |
|---|---|
| campos ordenados por nome | a ordem de processamento não é estável |
| fontes ordenadas por provedor | idem |
| observações ordenadas por discriminante | idem |
| `separators=(",", ":")` | um espaço a mais muda o hash |

A impressão do **conjunto** de uma execução é o SHA-256 das impressões dos
candidatos, ordenadas por id de partida — para que duas execuções que
processam os mesmos grupos em ordens diferentes produzam a mesma impressão.

---

## Licença

`most_restrictive_license` é gravada com o candidato, e vem do **conjunto** de
fontes que contribuíram — não da que venceu mais campos (§76).

```
UNKNOWN  <  RESEARCH_ONLY  <  ATTRIBUTION_REQUIRED  <  COMMERCIAL_ALLOWED  <  PUBLIC_DOMAIN
```

Um campo cujo conflito foi resolvido consultando a fonte restrita foi
produzido usando-a, mesmo que o valor final tenha vindo de outra.

---

## Persistência e linhagem

```
fused_candidates       body jsonb + fingerprint + licença
  └── fused_fields     regra, valor, fonte, confiança
       └── fused_field_sources   provedor, record_ref, valor, foi_selecionado
```

O `body` guarda a forma canônica **exata** que produziu a impressão; as
tabelas normalizadas existem para consulta (o operador de conflitos abre
`fused_fields WHERE rule = 'CONFLICT_UNRESOLVED'`).

`record_ref` é `dataset:arquivo:linha` e volta ao arquivo bruto — que é
imutável e continua lá (ADR-0014).

---

## Imutabilidade

`fused_candidates`, `fused_fields` e `fused_field_sources` são **append-only**.
Política nova produz execução nova; a anterior fica intacta (ADR-0020).

Comparar as impressões de duas execuções é o único jeito honesto de medir o
que a política nova mudou.

