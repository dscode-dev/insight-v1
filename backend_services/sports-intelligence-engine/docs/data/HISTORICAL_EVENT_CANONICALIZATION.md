# Canonicalização de eventos históricos

Do registro bruto de evento ao `CanonicalMatchEvent` gravado no PostgreSQL.
Implementado em **PR-04.4.1**.

---

## O caminho, e onde ele para

```
fonte histórica de eventos
    │  SourceReader (PR-02) — CSV / JSONL / Parquet, em lotes
    ▼
SourceRecord                          uma linha, papéis já aplicados
    │  EventRowReader                 tradução de FORMA, e só ela
    ▼
HistoricalEventRecord                 registro estruturado, ainda do provedor
    │  EventReferenceReader           3 consultas por lote: partida, time, jogador
    ▼
EventReferences                       traduções que a resolução JÁ provou (PR-03)
    │  EventEligibilityEvaluator      decide, e é a ÚNICA que decide
    ▼
EventEligibility                      INCLUDED / REVIEW_REQUIRED / EXCLUDED
    │  CanonicalEventBuilder          materializa; falha fechado
    ▼
CanonicalMatchEvent                   fato canônico, com detalhe tipado
    │  PostgresCanonicalEventWriter
    ▼
canonical_match_events  +  canonical_event_build_records
```

**E PARA AQUI.** A canonicalização **não** escreve pertinência de corpus,
**não** gera `events.parquet` e **não** toca o manifesto. Isso é o PR-04.4.2,
e antecipá-lo faria eventos entrarem numa versão publicada sem passar pelo
gate que existe exatamente para isso.

---

## Identidade — derivada, nunca sorteada

```python
uuid5(EVENT_ID_NAMESPACE, f"{match_id}|{source_key}|r{revision}")
```

Reprocessar a mesma fonte produz **o mesmo id**, e o `ON CONFLICT` do banco
reconhece o que já está lá — o desfecho vira `REUSED`, não um segundo evento.
Um `uuid4` faria toda releitura duplicar o corpus.

A `source_key` é a chave do provedor quando ela existe (`EVENT_PROVIDER_ID`) e
o referencial da linha quando não existe. As duas colunas são **distintas** no
banco:

| coluna | responde |
|--------|----------|
| `source_event_key` | como o **provedor** identifica este evento |
| `record_ref` | de qual **linha de qual arquivo** este fato veio |

Escrever uma no lugar da outra faz a coluna que deveria identificar o evento
no vocabulário do provedor guardar um número de linha.

---

## Ordem canônica

`ordering_key` ordena por `(período, minuto, acréscimo, sequência da fonte,
chave)` **antes de qualquer outra coisa**, e a sequência canônica é atribuída
sobre essa ordem. Atribuí-la sobre a ordem do arquivo faria dois
processamentos do mesmo dado produzirem sequências diferentes.

A sequência canônica **não é a do provedor**: provedores numeram a partir de
zero, de um, ou globalmente por temporada. O que o domínio precisa é uma ordem
local densa por `(partida, período)` — e a do provedor já foi usada, no
desempate acima, que é onde ela vale.

**A sequência atravessa lotes.** Um período pode cruzar a fronteira do lote;
se ela reiniciasse, dois eventos do mesmo tempo teriam a mesma posição, e a
ordem determinística deixaria de existir exatamente onde o lote quebrou.

---

## Revisão e cancelamento

A revisão é **declarada** pela fonte (`EVENT_REVISION_TYPE`), nunca deduzida:

| declarado | efeito |
|-----------|--------|
| `NEW` | evento novo, revisão 1 |
| `CORRECTION` | evento novo com `revision = anterior + 1`, `supersedes_event_id` apontando para o anterior, que passa a `CORRECTED` |
| `CANCELLATION` | **nenhum evento novo**; o anterior passa a `CANCELLED` |

**Cancelamento não é correção.** Um gol anulado pelo VAR não é um gol
corrigido; criar uma revisão «cancelada» faria o registro ter dois gols, um
deles anulado — quando houve um só, que não valeu.

Uma correção cujo predecessor não está no conjunto vira `DANGLING_REVISION` e
entra em revisão humana. Aplicá-la sem o anterior deixaria a cadeia quebrada,
e o banco recusa a incoerência de qualquer forma (`revision > 1` exige
predecessor).

**O predecessor é procurado no índice da execução, não no banco.** Uma fonte
que emite o evento e a correção no mesmo arquivo é o caso comum, e ir ao banco
por linha seria N+1. O índice guarda `chave → (id, revisão)` e atravessa lotes
— senão o tamanho do lote passaria a mudar o resultado.

---

## Elegibilidade — a ordem das guardas é a decisão

| # | guarda | motivo quando recusa |
|---|--------|----------------------|
| 1 | a partida resolve e está elegível | `MATCH_NOT_ELIGIBLE` |
| 2 | o tipo tem tradução canônica | `UNMAPPED_TYPE` |
| 3 | a identidade que **o tipo** exige | `IDENTITY_FAILURE` |
| 4 | o relógio é estruturalmente possível | `INVALID_CLOCK` |
| 5 | a licença permite este escopo | `LICENSE_POLICY` |

**A ordem não é arbitrária.** A licença vem por último porque ela não é
defeito do dado: o evento está perfeito e o que falta é o direito de publicá-lo
neste escopo. Reportá-la antes esconderia problemas reais atrás de uma questão
jurídica.

**Só a identidade que o tipo exige.** `EventType.requires_team` e
`requires_player` decidem, e a diferença é concreta: um `SHOT` sem jogador não
descreve quem chutou, mas um `GOAL` sobrevive sem jogador — gol contra, gol em
lance confuso, fonte que só registra o time. Exigir jogador em todo evento
descartaria gols reais.

Uma substituição exige **os dois** jogadores: um par desemparelhado é o que o
`SubstitutionDetail` existe para impedir.

O relógio é conferido **estruturalmente**, não esportivamente: minuto acima de
200 é erro de parsing, não prorrogação longa. O motor não sabe quantos minutos
um jogo deveria ter, e não vai saber.

---

## Observado ≠ derivado

`EVENT_XG` é o xG **que a fonte deu**. O motor nunca o calcula aqui — xG
calculado é `DerivedFeature`, tem versão de modelo, e pertence ao PR-05.

O valor tem **três estados**, e eles são diferentes:

| situação | o que fica gravado |
|----------|--------------------|
| a fonte não declara o papel | detalhe sem xG |
| a fonte declara e a célula está vazia | `FeatureValue` indisponível, com motivo |
| a fonte declara um número | o número observado |

`xg unavailable` **não é** `xg = 0`. Um chute sem xG e um chute com xG zero
são fatos diferentes, e colapsá-los envenena qualquer média calculada depois.

---

## Linhagem — o que não entrou também deixa linha

`canonical_event_build_records` grava **uma linha por registro lido**,
inclusive os recusados:

| status | significado |
|--------|-------------|
| `BUILT` | evento construído e gravado |
| `REUSED` | já existia — reprocessamento idempotente, ou cancelamento aplicado |
| `SKIPPED` | recusado com motivo |
| `REVIEW_REQUIRED` | não entrou sozinho; precisa de decisão humana |
| `FAILED` | falhou na construção |

Sem essa linha, «excluído por licença» e «nunca veio no arquivo» ficam
idênticos — e a pergunta «por que este evento não está no registro» deixa de
ter resposta.

O status vem de **quem escreveu**, não de quem construiu: o canonicalizador
diz `BUILT` porque construiu; só o registro canônico sabe se aquele evento já
existia. As contagens fecham por constraint no banco:
`built + reused + skipped + review + failed = records_read`.

---

## Transação e falha

A unidade transacional é **o lote**. Uma transação sobre cem mil eventos
seguraria locks por minutos e refaria tudo por causa de um; uma por evento
pagaria o custo de transação cem mil vezes.

Dentro do lote a ordem é fixa: escrever os eventos → marcar as transições de
revisão → gravar a linhagem. Marcar o predecessor como corrigido antes de o
sucessor existir deixaria, numa falha, um evento «corrigido» sem correção
nenhuma.

A execução é **aberta antes do primeiro evento** — a chave estrangeira aponta
para ela — e uma falha é **gravada**, não só levantada: uma execução que some
sem estado deixa «o que aconteceu com aquele arquivo» sem resposta.

---

## Números medidos

PostgreSQL 17 real, 100.000 registros de evento, 200 partidas, lote de 1.000:

| métrica | valor |
|---------|-------|
| duração | 39,4 s |
| throughput | 2.536 eventos/s |
| pico de memória | 30 MB |
| consultas | 602 (6,0 por lote — **não cresce com os registros**) |
| construídos | 100.000 |

Detalhes, comparação entre lotes e a prova de determinismo:
[baseline do PR-04.4.1](../performance/PR0441_EVENT_CANONICALIZATION_BASELINE.md).

---

## O que este PR deliberadamente não faz

| não faz | por quê |
|---------|---------|
| resolução de evento entre provedores | dois provedores descrevendo o mesmo gol é um problema próprio; `UncertainSameEvent` **não** vira `ForceMerge` |
| fusão campo a campo de eventos | não existe neste PR, e a ausência é declarada |
| pertinência de corpus, Parquet, manifesto | PR-04.4.2 |
| qualquer feature derivada | PR-05 |

---

## Relacionados

- [Contrato de fonte histórica de eventos](HISTORICAL_EVENT_CONTRACT.md)
- [Contrato do registro de evento (V1)](../contracts/HISTORICAL_EVENT_RECORD_V1.md)
- [ADR-0028 — registro de evento é entidade repetida](../architecture/adr/0028-historical-event-records-are-repeated-entities.md)
- [ADR-0013 — revisão e correção de eventos](../architecture/adr/0013-event-revision-and-correction-semantics.md)
- [ADR-0009 — procedência e valores ausentes](../architecture/adr/0009-data-provenance-and-missing-values.md)
- [ADR-0012 — sistema canônico de coordenadas](../architecture/adr/0012-canonical-spatial-coordinate-system.md)
- [Análise de capacidade de eventos](EVENT_CAPABILITY_ANALYSIS.md)
