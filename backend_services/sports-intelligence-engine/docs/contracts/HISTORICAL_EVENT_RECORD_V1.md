# Historical Event Record — schema V1

Uma linha de uma fonte histórica de eventos, já estruturada e ainda **no
vocabulário do provedor**. É o que a leitura produz e o que a canonicalização
consome.

> **Ele não é canônico.** Nenhum identificador aqui é do motor: `match_reference`,
> `team_reference` e `player_reference` são strings do provedor, e traduzi-las
> é trabalho da resolução (PR-03). Um `TeamId` neste objeto seria identidade
> inventada na borda.

---

## Schema

```jsonc
{
  "record_ref":            "arquivo.csv#L1042",   // de qual LINHA veio
  "provider_id":           "statsbomb",

  // ---- o mínimo, sem o qual não há evento
  "match_reference":       "3749052",             // id da PARTIDA no provedor
  "raw_type":              "Shot",                // rótulo CRU, não traduzido
  "clock": {
    "period":              "SECOND_HALF",
    "minute":              67,
    "stoppage":            0                      // o `+3` de `45+3`
  },

  // ---- fortemente recomendados
  "provider_event_id":     "e-88f1",              // sem ele: não reprocessável
  "sequence":              412,                   // a ordem do PROVEDOR

  // ---- quem
  "team_reference":        "217",
  "team_name":             "Barcelona",           // evidência, não identidade
  "player_reference":      "5503",
  "player_name":           "Lionel Messi",

  // ---- onde, normalizado em [0,1] PELA FONTE
  "start_point":           { "x": "0.88", "y": "0.51" },
  "end_point":             { "x": "0.97", "y": "0.49" },

  // ---- revisão, DECLARADA
  "revision":              "NEW",                 // NEW | CORRECTION | CANCELLATION
  "supersedes_reference":  null,                  // qual evento do provedor isto revisa

  // ---- detalhes tipados, por papel semântico
  "details": {
    "EVENT_OUTCOME":       "Goal",
    "EVENT_BODY_PART":     "Right Foot",
    "EVENT_XG":            "0.34"
  }
}
```

---

## Campo a campo

| campo | obrigatório | observação |
|-------|-------------|------------|
| `record_ref` | sim | o elo para o byte bruto. **Não** é a identidade do evento |
| `provider_id` | sim | de quem é o vocabulário de todos os `*_reference` |
| `match_reference` | sim | a partida. Um evento órfão não descreve nada |
| `raw_type` | sim | rótulo cru. A tradução é do `EventTypeMapping`, versionada |
| `clock` | sim | período + minuto + acréscimo |
| `provider_event_id` | **não, mas** | sem ele o dataset **não é reprocessável sem duplicar** |
| `sequence` | não | a ordem do provedor, usada como **desempate** |
| `team_reference` / `team_name` | não | exigidos pelo **tipo**, não globalmente |
| `player_reference` / `player_name` | não | idem |
| `start_point` / `end_point` | não | par completo ou nada |
| `revision` | tem padrão `NEW` | declarada pela fonte |
| `supersedes_reference` | condicional | obrigatória quando a revisão referencia um predecessor |
| `details` | não | dicionário **fechado**: só papéis com destino tipado |

---

## As quatro decisões que este contrato carrega

**1. O relógio é `(período, minuto, acréscimo)` — três campos, não um.**
Achatá-los confunde o terceiro minuto de acréscimo do primeiro tempo com o
terceiro do segundo, que são momentos táticos opostos. E `45` do primeiro
tempo não é `45` do segundo.

**Não existe campo de segundos.** `MatchClock` não tem onde guardá-los, e um
campo cujo valor é descartado é pior que a ausência dele: ele afirma que o dado
entrou.

**2. `raw_type` fica cru.** A tradução `"Shot" → EventType.SHOT` é do
`EventTypeMapping`, que tem **versão** — e a versão fica gravada na execução.
Traduzir na leitura perderia o rótulo original, e com ele a possibilidade de
retraduzir sob mapeamento novo.

**3. `details` é um dicionário fechado, não um depósito.** Só chegam nele os
papéis semânticos que os contratos tipados do PR-01 sabem receber. Um papel
sem destino descartaria dado em silêncio.

O dicionário distingue **três estados**, e a distinção sobrevive até o fato
canônico:

```
papel não mapeado          a chave não existe em `details`
papel mapeado, sem valor   a chave existe com string vazia → indisponível, com motivo
papel mapeado, com valor   a chave existe com o valor
```

`xg unavailable` não é `xg = 0`.

**4. Coordenadas são normalizadas pela FONTE.** O motor não converte metros:
as dimensões do campo variam por estádio e quem as conhece é o provedor. O
referencial (`ATTACKING` / `ABSOLUTE`) é declarado — sem ele, `0.8` de uma
fonte e `0.8` de outra querem dizer coisas opostas (ADR-0012).

---

## `ordering_key`

A ordem canônica de um conjunto de registros:

```
(ordem do período, minuto, acréscimo, sequência do provedor, chave de origem)
```

Ela é aplicada **antes** de qualquer construção, e é o que faz o resultado não
depender da ordem do arquivo nem do tamanho do lote.

---

## O que ele NÃO carrega

| ausente | onde vive |
|---------|-----------|
| `MatchId`, `TeamId`, `PlayerId` canônicos | resolução (PR-03) |
| `EventType` canônico | `EventTypeMapping`, versionado |
| decisão de elegibilidade | `EventEligibilityEvaluator` |
| qualquer valor calculado | PR-05 — e xG observado ≠ xG derivado |

---

## Relacionados

- [Contrato de fonte histórica de eventos](../data/HISTORICAL_EVENT_CONTRACT.md)
- [Canonicalização de eventos históricos](../data/HISTORICAL_EVENT_CANONICALIZATION.md)
- [ADR-0028 — registro de evento é entidade repetida](../architecture/adr/0028-historical-event-records-are-repeated-entities.md)
