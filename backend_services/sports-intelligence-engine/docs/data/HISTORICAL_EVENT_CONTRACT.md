# Contrato de fonte histórica de eventos

O que uma fonte precisa declarar para que o motor consiga construir eventos
canônicos a partir dela. Implementado em **PR-04.4.1**.

> **A forma é a decisão inteira.** Uma linha de um arquivo de eventos é **um
> evento**, não uma partida. Isso não é detalhe de leitura: muda o contrato,
> a resolução, a identidade e a linhagem. O porquê está no
> [ADR-0028](../architecture/adr/0028-historical-event-records-are-repeated-entities.md).

---

## `RecordKind` — a forma é declarada, nunca inferida

`SourceMappingDefinition.record_kind` diz qual mundo o arquivo descreve:

| valor | uma linha é | linhas por partida |
|-------|-------------|--------------------|
| `MATCH_RECORD` | uma partida | 1 |
| `EVENT_RECORD` | um evento de uma partida | muitas |

A declaração é conferida no `__post_init__` do mapeamento: um mapeamento
incoerente **não chega a existir**. E `assert_resolvable_as_matches()` — que
exige nome de mandante e de visitante — não se aplica a um fluxo de eventos:
aplicá-la recusaria uma fonte boa por não declarar o que só a partida declara.

**Inferir a forma pelo conteúdo é proibido.** Uma heurística do tipo «tem
coluna de minuto, então é evento» erra em silêncio, e o erro só aparece como
partida construída errada.

---

## Os papéis de evento

Vinte e dois papéis, todos com prefixo `EVENT_`, todos nomeados no catálogo
fechado. `SemanticRole.is_event` separa os dois mundos.

### Obrigatórios — sem os quatro não há evento

| papel | por que é obrigatório |
|-------|----------------------|
| `MATCH_PROVIDER_ID` | um evento órfão não descreve nada |
| `EVENT_TYPE` | «algo aconteceu aos 34» não é fato utilizável |
| `EVENT_PERIOD` | 45 do primeiro tempo e 45 do segundo são momentos diferentes |
| `EVENT_MINUTE` | o `when` mínimo |

`MATCH_PROVIDER_ID` é **reaproveitado** do catálogo de partida. É o mesmo
identificador, do mesmo provedor, para a mesma partida; um
`EVENT_MATCH_REFERENCE` paralelo faria o operador escolher entre dois nomes
certos.

### Fortemente recomendados — a fonte funciona sem, mas perde uma propriedade

| papel | o que se perde sem ele |
|-------|------------------------|
| `EVENT_PROVIDER_ID` | **idempotência**: a identidade passaria a depender da posição no arquivo, e reler a mesma linha produziria dois eventos |
| `EVENT_SEQUENCE` | **ordem determinística**: dois eventos no mesmo minuto empatam e o desempate cai na ordem do arquivo |

O relatório os reporta em `weak`, e `is_reprocessable` é **falso** quando
`EVENT_PROVIDER_ID` está entre eles. A frase que isso evita — «este dataset
não pode ser reprocessado sem duplicar» — precisa ser dita antes de rodar, e
não depois.

### Relógio, identidade e revisão

| papel | observação |
|-------|-----------|
| `EVENT_STOPPAGE` | o `+3` de `45+3`, **separado** do minuto — achatá-los confunde o acréscimo do primeiro tempo com o do segundo |
| `EVENT_TEAM_PROVIDER_ID`, `EVENT_TEAM_NAME` | o time que praticou; o id resolve, o nome é evidência |
| `EVENT_PLAYER_PROVIDER_ID`, `EVENT_PLAYER_NAME` | idem para o jogador |
| `EVENT_REVISION_TYPE` | `NEW` / `CORRECTION` / `CANCELLATION`, **declarado pela fonte** |
| `EVENT_SUPERSEDES_PROVIDER_ID` | qual evento esta linha revisa |

A revisão é declarada, nunca deduzida: inferi-la de um id repetido faria toda
reingestão parecer correção.

### Espaço

`EVENT_X`, `EVENT_Y`, `EVENT_END_X`, `EVENT_END_Y` — **normalizadas pela
fonte, em `[0,1]`**. O motor não converte metros: as dimensões do campo
variam por estádio e quem as conhece é a fonte.

### Detalhes tipados

`EVENT_OUTCOME`, `EVENT_BODY_PART`, `EVENT_XG`, `EVENT_CARD_TYPE`,
`EVENT_PLAYER_OUT_PROVIDER_ID`, `EVENT_PLAYER_IN_PROVIDER_ID`.

**Só existem papéis cujo valor tem onde morar** nos contratos do PR-01
(`ShotDetail`, `CardDetail`, `SubstitutionDetail`). Um papel sem destino
descartaria dado em silêncio — que é pior que não aceitá-lo.

Por isso **não existe `EVENT_SECOND`**: `MatchClock` tem período, minuto e
acréscimo, e não tem segundo. Um papel para segundos teria de jogá-los fora.

### O que não existe, por decisão

```
EVENT_1_TYPE, EVENT_2_TYPE, EVENT_1200_TYPE …
```

Colunas numeradas quebram no primeiro jogo com mais eventos que colunas, e o
catálogo fechado não tem como gerar esses nomes — o desenho é recusado pelo
tipo (§9, ADR-0028).

---

## Pares — declarar metade é declaração pela metade

| par | por quê |
|-----|---------|
| `EVENT_X` + `EVENT_Y` | um ponto com uma coordenada só não é um ponto |
| `EVENT_END_X` + `EVENT_END_Y` | idem para o destino |
| `EVENT_PLAYER_OUT_PROVIDER_ID` + `EVENT_PLAYER_IN_PROVIDER_ID` | uma substituição em que alguém sai e ninguém entra não é uma substituição |

Um lado sem o outro entra em `missing`, não em `weak`: a declaração está
incompleta, não frágil.

---

## O relatório

`inspect_contract(kind=…, roles=…)` **não levanta** — devolve
`EventContractReport`:

| campo | significado |
|-------|-------------|
| `missing` | papel obrigatório ausente → **impede a leitura** |
| `weak` | recomendado ausente → **degrada**, e quem opera precisa saber antes |
| `misplaced` | papel do outro mundo → **mapeamento incoerente** |
| `is_usable` | `not missing and not misplaced` |
| `is_reprocessable` | `EVENT_PROVIDER_ID` presente |

Quem precisa recusar chama `assert_usable()`, que levanta `ValidationError`
com o que faltou. **O cálculo é um só**: duas cópias divergiriam, e a
divergência apareceria como um mapeamento aceito na configuração e recusado
na leitura.

Um `MATCH_RECORD` que declara qualquer papel `EVENT_*` recebe todos eles em
`misplaced` — é quase sempre alguém tentando encaixar eventos no formato
antigo.

---

## Onde este contrato fica na fila

```
contrato          «esta declaração é utilizável?»     antes de ler bytes
validação PR-02   «este arquivo tem estas colunas?»   estrutural
qualidade PR-04   «este evento pode entrar?»          por evento
```

São três degraus e o contrato é o primeiro. Recusar aqui custa uma mensagem
na configuração; descobrir na leitura custa metade de um dataset processado
antes de alguém perceber.

**O contrato não interpreta futebol.** Ele não sabe que um pênalti vem de uma
falta, não sabe quantos eventos um jogo deveria ter, e não vai saber. Isso é
julgamento esportivo, e o motor não o faz.

---

## Relacionados

- [ADR-0028 — registro de evento é entidade repetida](../architecture/adr/0028-historical-event-records-are-repeated-entities.md)
- [ADR-0013 — semântica de revisão e correção de eventos](../architecture/adr/0013-event-revision-and-correction-semantics.md)
- [Contrato do registro de evento (V1)](../contracts/HISTORICAL_EVENT_RECORD_V1.md)
- [Canonicalização de eventos históricos](HISTORICAL_EVENT_CANONICALIZATION.md)
- [Dicionário de dados canônico](CANONICAL_DATA_DICTIONARY.md)
