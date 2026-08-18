# Eventos canônicos — análise de capacidade

Conferência exigida pelo **PR-04.3.1 §38–§51**, feita em **2026-08-18**.

> **A pergunta que esta análise responde** não é «algum dataset atual declara
> eventos?». É «o motor SABE construir um evento canônico?». As duas são
> diferentes, e confundi-las é a forma mais fácil de fechar um PR sobre uma
> capacidade que não existe:
>
> ```
> CapabilityNotImplemented  ≠  CapabilityNotDeclaredByCurrentDataset
> ```

---

## Veredito

```
EVENT      NOT_IMPLEMENTED — deliberadamente adiado
PLAYER     coberto por referência; sem família independente
SPATIAL    atributo de evento; sem evento, não há o que declarar
TRACKING   fora da V1, por decisão anterior
```

---

## O caminho, estágio a estágio

O PR-04.3.1 §40 pede o traçado concreto. Ele é este, e ele **quebra no
primeiro degrau**:

| # | estágio | estado | evidência |
|---|---------|--------|-----------|
| 1 | `SemanticRole` de evento | **AUSENTE** | `domain/sources/semantics.py` não tem papel de tipo, minuto, jogador do evento, desfecho nem coordenada |
| 2 | contrato de fonte linha-por-evento | **AUSENTE** | todo o intake, a resolução e a fusão são uma-linha-por-PARTIDA |
| 3 | candidato de evento fundido | **AUSENTE** | zero menções a evento em `ingestion/fusion/` |
| 4 | qualidade / elegibilidade de evento | **AUSENTE** | `CoverageFamily.EVENT` existe como rótulo; nada o avalia |
| 5 | `CanonicalEventBuilder` | **AUSENTE** | `historical/build/builders.py` explica, num comentário, por que ele não existe |
| 6 | persistência `match_events` | **AUSENTE** | nenhuma migration cria a tabela |
| 7 | pertinência no corpus | **AUSENTE** | `EVENT ∉ MATERIALIZABLE_FAMILIES` |
| 8 | linhas de evento no Parquet | **AUSENTE** | não há schema de evento |
| 9 | contagem no manifesto | reporta `NOT_DECLARED` | que é a verdade |

**O que EXISTE**, e é o que torna a confusão possível:

| peça | onde | desde |
|------|------|-------|
| `CanonicalMatchEvent`, `EventStatus` | `domain/events/canonical.py` | PR-01 |
| `PitchCoordinate`, `CoordinateFrame` | `domain/events/coordinates.py` | PR-01 |
| `ShotDetail`, `PassDetail`, `CardDetail`… | `domain/events/details.py` | PR-01 |
| `EventEnvelope`, `SourceEventId` | `domain/events/envelope.py`, `idempotency.py` | PR-01 |
| `CanonicalEventRepositoryPort` | `ports/repositories/football.py` | PR-01 |
| `CanonicalFactType.MATCH_EVENT` | `domain/build/decisions.py` | PR-04.2 |

**O vocabulário do domínio está completo e o pipeline não existe.** Nenhum
adapter implementa `CanonicalEventRepositoryPort`, porque não há tabela para
ele escrever.

### A armadilha específica

`SemanticRole` tem `HOME_SHOTS`, `AWAY_SHOTS`, `HOME_SHOTS_ON_TARGET` e
`AWAY_SHOTS_ON_TARGET`. Uma leitura apressada de `grep SHOT` conclui que
chutes são suportados. **Eles não são eventos**: são CONTAGENS agregadas por
partida — «o mandante finalizou 14 vezes» —, e delas não sai um evento com
minuto, jogador, coordenada e desfecho. A distância entre as duas coisas é
exatamente o que falta.

---

## Por que não foi implementado agora

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
EVENT = BLOCKED
```

---

## As duas saídas, para quem decidir

**Opção A — fechar a capacidade num PR próprio.** Um `PR-04.4 — Canonical
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
**Classificação: bloqueada por EVENT, e não separadamente.**

**TRACKING** — fora da V1 por decisão anterior (PR-04.1 §20). O catálogo a
NOMEIA justamente para que a ausência seja declarada em vez de esquecida.
**Classificação: `NOT_APPLICABLE` na V1.**
