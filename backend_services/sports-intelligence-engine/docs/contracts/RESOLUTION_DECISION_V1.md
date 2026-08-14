# Resolution Decision — schema V1

Uma decisão de identidade, e tudo que é preciso para conferi-la anos depois
sem reexecutar nada.

> Toda resolução possui: **decisão + evidência + confiança + versão + ator +
> linhagem.** Faltando qualquer uma, ela é indistinguível de um palpite que
> deu certo.

---

## Schema

```jsonc
{
  "id":            "b7d2-…",
  "subject_type":  "TEAM",              // COMPETITION | SEASON | TEAM | PLAYER | MATCH

  "source": {
    "provider_id":        "football_data",
    "provider_entity_id": "MCI",        // ou null
    "raw":                "Man City",
    "normalized":         "man city",
    "normalizer_version": "v1.0"
  },

  "outcome": {
    "status":              "RESOLVED",  // RESOLVED | UNRESOLVED | AMBIGUOUS
                                        // REVIEW_REQUIRED | REJECTED
    "method":              "EXACT_ALIAS",
    "confidence":          1.0,
    "canonical_entity_id": "9f2b6f3e-…" // SÓ em RESOLVED
  },

  "versions": {
    "resolver":   "v1.0",
    "normalizer": "v1.0",
    "policy":     "v1.0"
  },

  "input": {
    "dataset_id":           "3c1e…",
    "dataset_version":      "v1.0",
    "manifest_fingerprint": "a3f5…"     // 64 hex — fecha a linhagem
  },

  "decided_at":   "2026-08-13T12:00:00+00:00",
  "decided_by":   { "id": "historical-resolution-worker", "kind": "SERVICE" },
  "reason":       null,                 // obrigatório em MANUAL_REVIEW e REJECTED

  "evidence": [
    {
      "kind":            "ALIAS",
      "outcome":         "MATCHED",     // MATCHED | MISMATCHED | UNAVAILABLE
      "explanation":     "ALIAS_MATCH",
      "weight":          1.0,
      "source_value":    "Man City",
      "canonical_value": "Man City"
    }
  ],

  "alternatives": [
    {
      "canonical_entity_id": "7a4d…",
      "score":               0.83,
      "label":               "Melbourne City",
      "evidence_summary":    "+NAME_SIMILARITY -COUNTRY"
    }
  ]
}
```

---

## Campos

### `outcome`

| campo | nulo? | observação |
|---|---|---|
| `status` | nunca | cinco valores; nenhum é booleano |
| `method` | nunca | seis valores; nunca `AUTO` |
| `confidence` | nunca | [0,1]; **não** é probabilidade calibrada |
| `canonical_entity_id` | **só em RESOLVED** | cobrado no domínio e no banco |

> **A regra central, cobrada nos dois lugares:**
> ```sql
> CHECK ((status = 'RESOLVED') = (canonical_entity_id IS NOT NULL))
> ```
> `RESOLVED` sem entidade afirmaria ter resolvido sem dizer para quê; qualquer
> outro status **com** entidade produziria uma referência que alguém usaria
> por engano.

### `versions`

As três mudam independentemente, e confundi-las apaga a informação que torna o
reprocessamento útil:

```
resolver     a LÓGICA: que evidências, em que ordem, como o score compõe
normalizer   a preparação do TEXTO — mudá-la re-chaveia todo alias
policy       os LIMIARES e PESOS
```

Com uma versão só, «o resolver melhorou» e «o limiar afrouxou» ficariam
indistinguíveis — e a pergunta «por que este registro resolveu agora e não
antes» não teria resposta.

**Confianças de versões diferentes não se comparam.** São réguas diferentes, e
`DecisionVersions.assert_comparable` recusa.

### `evidence`

Estruturada, e nunca texto livre. Um campo `explanation: str` pareceria
resolver e viraria a autoridade sobre o que aconteceu — divergindo do que de
fato aconteceu no primeiro refactor, porque ninguém atualiza uma string. Pior:
não é agregável. «Quantas resoluções de jogador dependeram de data de
nascimento?» exigiria varrer texto.

**`weight` é gravado com a evidência** porque a política muda: sem ele, reler
uma decisão antiga aplicaria os pesos de hoje ao raciocínio de ontem.

**`UNAVAILABLE` ≠ `MISMATCHED`.** É a regra do PR-00 aplicada à resolução:
ausente nunca é zero. Uma fonte que não traz data de nascimento não está
discordando da data canônica — ela não disse nada, e tratar silêncio como
divergência puniria fontes incompletas por serem incompletas.

O texto legível é **derivado**:

```
+ PROVIDER_MAPPING (MCI contra 9f2b…) [PROVIDER_ID_MATCHED, peso 1.00]
+ DATE_OF_BIRTH (1994-07-12 contra 1994-07-12) [VALUE_MATCHED, peso 0.80]
- POSITION (CM contra ST) [VALUE_MISMATCH, peso 0.20]
```

### `alternatives`

Os candidatos **descartados**, com quanto faltou. Sem eles, uma decisão
`AMBIGUOUS` diz «não sei» e não diz entre o quê — e o humano na fila
precisaria refazer a busca à mão.

Top-N limitado por política (3 a 8 conforme o sujeito): guardar mil candidatos
de um nome genérico enche o banco sem acrescentar nada depois do décimo.

**Ordenação determinística**: score decrescente, depois id da entidade. Dois
candidatos com o mesmo score saem do banco em ordem arbitrária, e sem
desempate a mesma entrada produziria decisões diferentes em execuções
diferentes.

### `decided_by`

```
{ "id": "historical-resolution-worker", "kind": "SERVICE" }
{ "id": "user:9f2b6f3e-…",              "kind": "HUMAN_OPERATOR" }
```

Recusados como identificador: `system`, `admin`, `root`, `unknown`,
`anonymous`, `default`. Cada um deles, encontrado numa trilha dois anos
depois, significa exatamente «não sabemos quem fez».

**A coerência é cobrada**, no domínio e no banco:

```sql
CHECK ((method = 'MANUAL_REVIEW') = (decided_by_kind IN ('HUMAN_OPERATOR','CLI')))
```

O método diz que um humano decidiu; o ator precisa concordar.

---

## Imutabilidade

A tabela `resolution_decisions` é **append-only**. Não há `UPDATE` sobre ela
em lugar nenhum do código, e um teste de arquitetura lê o SQL do adapter e
falha se aparecer.

Reprocessar emite decisões novas numa execução nova. A anterior fica
exatamente como estava — e a diferença entre as duas é o que mostra o que o
resolver novo passou a enxergar (ADR-0019).

---

## Mapeamento derivado

Uma decisão `RESOLVED` pode originar um `ProviderEntityMapping`, e o vínculo é
**obrigatório**:

```sql
resolution_decision_id  uuid NOT NULL
```

Um mapeamento sem decisão que o explique é indistinguível de um mapeamento
inventado. E reapontar um mapeamento existente para outra entidade é
`ConflictError` — sobrescrever faria todo o histórico já resolvido apontar
para a entidade errada, em silêncio.

