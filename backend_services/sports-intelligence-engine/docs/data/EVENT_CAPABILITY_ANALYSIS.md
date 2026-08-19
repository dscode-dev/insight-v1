# Eventos canônicos — análise de capacidade

Conferência exigida pelo **PR-04.3.1 §38–§51**, feita em **2026-08-18**.
**Atualizada em 2026-08-18 pelo PR-04.4.1**, que escolheu a Opção A e
implementou os seis primeiros estágios.

> **O histórico desta página é parte dela.** A classificação anterior
> (`NOT_IMPLEMENTED`) está preservada abaixo, com a data e o motivo. Apagá-la
> transformaria «foi decidido adiar, e depois construído» em «sempre esteve
> pronto» — e é justamente a rastreabilidade da decisão que o §48 do
> PR-04.3.1 exige.

> **A pergunta que esta análise responde** não é «algum dataset atual declara
> eventos?». É «o motor SABE construir um evento canônico?». As duas são
> diferentes, e confundi-las é a forma mais fácil de fechar um PR sobre uma
> capacidade que não existe:
>
> ```
> CapabilityNotImplemented  ≠  CapabilityNotDeclaredByCurrentDataset
> ```

---

## Veredito — 2026-08-18, depois do PR-04.4.1

```
EVENT      CANONICAL_PIPELINE_SUPPORTED · CORPUS_INTEGRATION_PENDING
PLAYER     coberto por referência; sem família independente
SPATIAL    atributo de evento; o registro canônico já o guarda, o corpus não
TRACKING   fora da V1, por decisão anterior
```

**O que a primeira linha quer dizer, exatamente.** O motor **sabe** construir
um evento canônico a partir de uma fonte histórica, e o faz de ponta a ponta
até o PostgreSQL — cem mil registros medidos. O que ele **ainda não faz** é
publicar esses eventos numa versão do corpus: pertinência, Parquet e contagem
no manifesto são o PR-04.4.2.

As duas metades precisam de nomes diferentes porque falham diferente:

```
CanonicalPipelineSupported     «o motor sabe construir»      sim, no PR-04.4.1
CorpusIntegrationPending       «uma versão publica eventos»  não, é o PR-04.4.2
```

Chamar isso de `DONE` faria uma feature que precisa de eventos publicados
acreditar que pode consumi-los da versão do corpus, quando a versão não os
tem.

---

## O caminho, estágio a estágio

O PR-04.3.1 §40 pediu o traçado concreto. Ele quebrava no primeiro degrau;
hoje quebra no sétimo:

| # | estágio | estado | evidência |
|---|---------|--------|-----------|
| 1 | `SemanticRole` de evento | **PRONTO** (PR-04.4.1) | 22 papéis `EVENT_*` em `domain/sources/semantics.py`, com `is_event` |
| 2 | contrato de fonte linha-por-evento | **PRONTO** (PR-04.4.1) | `RecordKind`, `EventContractReport`, `inspect_contract` |
| 3 | leitura linha-por-evento | **PRONTO** (PR-04.4.1) | `EventRowReader` sobre o `SourceReader` do PR-02 |
| 4 | elegibilidade de evento | **PRONTO** (PR-04.4.1) | `EventEligibilityEvaluator`, cinco guardas ordenadas |
| 5 | `CanonicalEventBuilder` | **PRONTO** (PR-04.4.1) | `historical/events/builder.py`, id derivado por `uuid5` |
| 6 | persistência `canonical_match_events` | **PRONTO** (PR-04.4.1) | migration `0009`, com linhagem por evento |
| 7 | pertinência no corpus | **AUSENTE** | `EVENT ∉ MATERIALIZABLE_FAMILIES` |
| 8 | linhas de evento no Parquet | **AUSENTE** | não há schema de evento |
| 9 | contagem no manifesto | reporta `NOT_DECLARED` | que continua sendo a verdade |

**O estágio que não existe e não é omissão.** Resolução de evento **entre
provedores** — dois provedores descrevendo o mesmo gol terminando no mesmo
evento canônico. O PR-04.4.1 trata cada fonte isoladamente, por decisão
explícita: `UncertainSameEvent` não vira `ForceMerge`, e uma fusão
probabilística de eventos criada para fechar checklist atribuiria fatos a quem
não os praticou.

---

## O estado anterior, preservado — 2026-08-18, no PR-04.3.1

```
EVENT      NOT_IMPLEMENTED — deliberadamente adiado
```

| # | estágio | estado então |
|---|---------|--------------|
| 1 | `SemanticRole` de evento | AUSENTE |
| 2 | contrato de fonte linha-por-evento | AUSENTE |
| 3 | candidato de evento fundido | AUSENTE |
| 4 | qualidade / elegibilidade de evento | AUSENTE |
| 5 | `CanonicalEventBuilder` | AUSENTE |
| 6 | persistência `match_events` | AUSENTE |
| 7 | pertinência no corpus | AUSENTE |
| 8 | linhas de evento no Parquet | AUSENTE |
| 9 | contagem no manifesto | `NOT_DECLARED` |

**O que EXISTE**, e é o que torna a confusão possível:

| peça | onde | desde |
|------|------|-------|
| `CanonicalMatchEvent`, `EventStatus` | `domain/events/canonical.py` | PR-01 |
| `PitchCoordinate`, `CoordinateFrame` | `domain/events/coordinates.py` | PR-01 |
| `ShotDetail`, `PassDetail`, `CardDetail`… | `domain/events/details.py` | PR-01 |
| `EventEnvelope`, `SourceEventId` | `domain/events/envelope.py`, `idempotency.py` | PR-01 |
| `CanonicalEventRepositoryPort` | `ports/repositories/football.py` | PR-01 |
| `CanonicalFactType.MATCH_EVENT` | `domain/build/decisions.py` | PR-04.2 |

**Era esse o vocabulário que tornava a confusão possível** — ele estava
completo desde o PR-01 e o pipeline não existia. **No PR-04.4.1 o pipeline
passou a existir**: `PostgresCanonicalEventWriter` escreve em
`canonical_match_events`, e o vocabulário do PR-01 é exatamente o que ele
materializa — nenhum tipo novo de domínio precisou ser inventado para isso,
o que confirma que o desenho do PR-01 estava certo e só lhe faltava o caminho.

### A armadilha específica

`SemanticRole` tem `HOME_SHOTS`, `AWAY_SHOTS`, `HOME_SHOTS_ON_TARGET` e
`AWAY_SHOTS_ON_TARGET`. Uma leitura apressada de `grep SHOT` conclui que
chutes são suportados. **Eles não são eventos**: são CONTAGENS agregadas por
partida — «o mandante finalizou 14 vezes» —, e delas não sai um evento com
minuto, jogador, coordenada e desfecho. A distância entre as duas coisas é
exatamente o que falta.

---

## Por que não foi implementado no PR-04.3.1 — e o que mudou

O §46 autoriza fechar a capacidade quando os contratos já existem, os
`SemanticRole` necessários já existem **ou eram inequivocamente parte do
PR-04**, e a implementação é pequena e coesa. As três condições falham juntas.

Implementar exigiria, no mínimo:

1. **uma família nova de papéis semânticos** — tipo do evento, minuto, período,
   jogador, time, desfecho e (se houver) coordenadas;
2. **uma FORMA de contrato de fonte que não existe** — hoje um arquivo é uma
   linha por partida; um arquivo de eventos é uma linha por evento, e isso
   muda a leitura, o agrupamento e a resolução;
3. **identidade e fusão no nível do evento** — `SourceEventId` existe e nada o
   consome; dois provedores descrevendo o mesmo gol precisam terminar no mesmo
   evento canônico, e essa é uma resolução própria;
4. **qualidade e elegibilidade por evento**;
5. **construtor, tabela e Parquet**.

Isso é uma **camada de mapeamento semântico nova**, não um acréscimo coeso —
e o §44 é explícito: não inventar papéis para fechar checklist.

**O que o PR-04.4.1 fez com essa lista.** Os itens 1, 2 e 4 foram
implementados; o item 3 — identidade e fusão **entre provedores** — ficou
deliberadamente de fora, e o item 5 foi partido em dois: construtor e tabela
entraram, Parquet ficou para o PR-04.4.2. O caminho escolhido foi a **Opção
A** abaixo, e a decisão de forma está no
[ADR-0028](../architecture/adr/0028-historical-event-records-are-repeated-entities.md).

---

## Consequência declarada

**Construção canônica de eventos é PRÉ-REQUISITO de qualquer `FeatureSpace`
que dependa de eventos.** Isso inclui, do roadmap: xG por evento, Player
Influence baseado em ações, Tactical Graph, Pressure e qualquer trajetória.

O PR-05 (Feature Foundation & Historical State Builder) pode começar **sobre
as famílias que o corpus de fato publica** — `MATCH`, `LINEUP`, `ODDS` —, e
qualquer feature que precise de evento fica bloqueada por esta ausência, não
por falta de espaço de features.

**Não classificamos isto como `NOT_APPLICABLE`.** Eventos são dado de futebol
real e o motor vai precisar deles; «não aplicável» seria falso. Também não
classificamos como `DONE` por ausência de fixture — que é exatamente o que o
§39 e o §48 proíbem.

```
EVENT = BLOCKED                       (PR-04.3.1)
EVENT = PARCIALMENTE DESBLOQUEADO     (PR-04.4.1)
        pipeline canônico pronto · integração ao corpus pendente
```

**O que o PR-04.4.1 desbloqueia, e o que continua bloqueado.** Quem lê os
eventos **do PostgreSQL** — pela partida, em ordem determinística — já tem o
dado. Quem depende de eventos **publicados numa versão do corpus** (leitura
analítica pelo Parquet, contagem no manifesto, reprodutibilidade por versão)
continua bloqueado até o PR-04.4.2.

**O PR-04 continua sem estar fechado por esta razão**, e não por outra.

---

## As duas saídas — a Opção A foi a escolhida

**Opção A — fechar a capacidade num PR próprio. → ESCOLHIDA**, executada como
`PR-04.4.1 — Historical Event Contract & Canonicalization Pipeline`, com a
integração ao corpus separada em `PR-04.4.2`. Um `PR-04.4 — Canonical
Event Ingestion` com os cinco itens acima. Escopo real, não decorativo: ele
reabre intake, resolução e fusão para a forma linha-por-evento.

**Opção B — emendar formalmente o escopo do PR-04.** Registrar que a
construção canônica de eventos sai do PR-04 e vira pré-requisito nomeado do
PR-05, com a lista de features que ficam bloqueadas até lá.

**A escolha é de quem responde pelo roadmap, e não deste PR.** Amendar o DoD
por conta própria e depois declarar o PR fechado seria a reclassificação
silenciosa que o §48 proíbe — só que com mais parágrafos.

---

## PLAYER, SPATIAL e TRACKING

**PLAYER** — a identidade canônica de jogador existe e é resolvida
(`PlayerId`, `player_team_tenures`, resolução com evidência desde o PR-03).
Jogadores aparecem no corpus **por referência**, dentro de `LINEUP`. Uma
família `PLAYER` independente descreveria o quê? Atributos de jogador
(nascimento, nacionalidade, posição) são dimensão canônica e não fato de
partida — publicá-los como família do corpus histórico misturaria dimensão com
fato. **Classificação: `NOT_APPLICABLE` para o corpus de partidas, com a
identidade coberta.**

**SPATIAL** — coordenadas são atributo de evento (`PitchCoordinate` vive em
`domain/events/`). Sem evento, não há onde pendurá-las, e uma família
`SPATIAL` independente seria uma tabela de pontos sem o que eles descrevem.
**Classificação (PR-04.4.1): o registro canônico já guarda a coordenada** —
`start_x/y`, `end_x/y` e o referencial declarado, com constraint de par
completo e de intervalo `[0,1]`. O que continua ausente é a família `SPATIAL`
**no corpus**, bloqueada junto com a integração de eventos.

**TRACKING** — fora da V1 por decisão anterior (PR-04.1 §20). O catálogo a
NOMEIA justamente para que a ausência seja declarada em vez de esquecida.
**Classificação: `NOT_APPLICABLE` na V1.**
