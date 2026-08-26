"""A visão EFETIVA dos eventos num instante — o que se sabia, e não o que se sabe.

O CASO QUE ELA EXISTE PARA RESOLVER (§25):

    63:21  GOAL E1
    64:10  correção E2, que substitui E1

Um replay honesto aos 63:30 enxerga E1 — porque E2 ainda não existia para
ninguém. O mesmo replay às 64:30 enxerga E2, e E1 aparece como corrigido. O
corpus guarda os dois; qual deles é o «efetivo» depende do instante da
pergunta.

    EffectiveEventProjection  ≠  CanonicalEventHistory        (§24)

A PROJEÇÃO É DERIVADA E NÃO MUTA NADA. O corpus continua append-only e
auditável: nenhum evento é apagado, nenhum status é reescrito. O que a projeção
faz é DECIDIR, para um corte, quais eventos entram e em que estado.

DUAS DECISÕES QUE PARECEM UMA (§22, §76, §77):

    ocorrência     o evento aconteceu antes do corte?
    conhecimento   a correção dele já era conhecida no corte?

Um evento cuja correção só ficou conhecida depois do corte entra na projeção na
forma ORIGINAL — não na corrigida, e não fora dela. Deixá-lo de fora seria
inventar um jogo em que o gol não existiu; aplicá-lo corrigido seria dar ao
passado uma informação que ele não tinha.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final, Self, final

from sports_intelligence.domain.events.canonical import CanonicalMatchEvent, EventStatus
from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.leakage import (
    FactTiming,
    LeakageDecision,
    LeakageReason,
    TemporalLeakageGuard,
)
from sports_intelligence.domain.features.temporal import FeatureAsOf, MatchTimePoint
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Instant


@final
@dataclass(frozen=True, slots=True)
class EventKnowledge:
    """Quando cada evento pôde ser conhecido — o que o corpus NÃO sabe (§26).

    POR QUE ISTO É UM OBJETO À PARTE, e não um campo do evento. O corpus
    histórico não guarda o instante em que o provedor publicou cada evento: o
    `ObservationTimes` dos eventos canônicos é `at_once(ingestão)`, que é outra
    coisa. Fingir que ele é o instante de observação seria inventar precisão.

    Este mapa é a porta por onde uma fonte que DE FATO tenha esses carimbos os
    entrega. Vazio, tudo se decide pela política — e a política padrão trata
    correção sem carimbo como retrospectiva, que é o fail-closed do §78.
    """

    by_event: dict[uuid.UUID, Instant] = field(default_factory=dict)

    def of(self, event_id: uuid.UUID) -> Instant | None:
        return self.by_event.get(event_id)

    @property
    def is_empty(self) -> bool:
        return not self.by_event


@final
@dataclass(frozen=True, slots=True)
class ProjectedEvent:
    """Um evento na visão efetiva, com o que a projeção decidiu sobre ele."""

    event: CanonicalMatchEvent
    #: `True` quando este evento é o ORIGINAL de uma cadeia cuja correção
    #: existe e não era conhecida no corte. É o caso do §76, e ele merece nome:
    #: quem lê a projeção precisa poder distinguir «não foi corrigido» de
    #: «a correção ainda não era sabida».
    correction_withheld: bool = False

    @property
    def id(self) -> uuid.UUID:
        return self.event.id

    @property
    def position(self) -> MatchTimePoint:
        return MatchTimePoint.from_clock(self.event.clock, sequence=self.event.sequence)


@final
@dataclass(frozen=True, slots=True)
class ProjectionOutcome:
    """O resultado da projeção — o que entrou, e por que o resto não entrou.

    OS EXCLUÍDOS SÃO CONTADOS POR MOTIVO, e não descartados. «A projeção viu 12
    eventos» não explica nada quando alguém esperava 15; «12 vistos, 2 do
    futuro, 1 correção retrospectiva» explica.
    """

    events: tuple[ProjectedEvent, ...] = ()
    excluded_by_reason: dict[str, int] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.events)

    @property
    def excluded_total(self) -> int:
        return sum(self.excluded_by_reason.values())

    def ids(self) -> tuple[uuid.UUID, ...]:
        return tuple(p.id for p in self.events)


#: Os estados que um evento pode ter na projeção efetiva. `CORRECTED` fica de
#: fora: um evento corrigido foi SUBSTITUÍDO, e quem o publica na visão efetiva
#: mostraria o gol antigo ao lado do novo — dois gols onde houve um.
_ESTADOS_VIGENTES: Final[frozenset[EventStatus]] = frozenset({EventStatus.ACTIVE})


@final
@dataclass(frozen=True, slots=True)
class EffectiveEventProjection:
    """Projeta a história canônica de eventos sobre um corte (§23).

    O ALGORITMO, e cada passo existe por um caso concreto:

        1. ordena por posição            a ordem canônica, sempre a mesma
        2. recusa o que é do futuro      guarda de ocorrência
        3. resolve a cadeia de revisão   quem substitui quem, e se a
                                         substituição era conhecida
        4. devolve os vigentes           mais a contagem do que ficou de fora

    ELE É PURO E SEM I/O (§95). Recebe a lista de eventos — que alguém já leu
    do corpus —, o corte, a política e o mapa de conhecimento. Não conhece
    banco, repositório nem arquivo.
    """

    guard: TemporalLeakageGuard

    @classmethod
    def with_policy(cls, policy: TemporalAvailabilityPolicy) -> Self:
        return cls(guard=TemporalLeakageGuard(policy=policy))

    def project(
        self,
        events: Iterable[CanonicalMatchEvent],
        *,
        as_of: FeatureAsOf,
        knowledge: EventKnowledge | None = None,
    ) -> ProjectionOutcome:
        conhecimento = knowledge or EventKnowledge()
        ordenados = _em_ordem(events)
        _recusar_partida_errada(ordenados, as_of)

        excluidos: dict[str, int] = {}
        admitidos: list[CanonicalMatchEvent] = []
        for evento in ordenados:
            decisao = self._decidir(evento, as_of, conhecimento)
            if decisao.admits:
                admitidos.append(evento)
                continue
            assert decisao.reason is not None
            excluidos[decisao.reason.value] = excluidos.get(decisao.reason.value, 0) + 1

        vigentes = _resolver_cadeia(admitidos)
        return ProjectionOutcome(
            events=vigentes, excluded_by_reason=dict(sorted(excluidos.items()))
        )

    # ---------------------------------------------------------- internos --

    def _decidir(
        self,
        event: CanonicalMatchEvent,
        as_of: FeatureAsOf,
        knowledge: EventKnowledge,
    ) -> LeakageDecision:
        """O veredito do guarda para UM evento.

        A REVISÃO É TRATADA COMO FAMÍLIA PRÓPRIA (§22). Um evento com
        `supersedes` não é um evento comum: ele é a correção de outro, e a
        política o classifica separadamente — por padrão como retrospectivo,
        que o modo causal recusa.
        """
        e_revisao = event.supersedes is not None
        carimbo = knowledge.of(event.id)
        # UM CARIMBO REAL SUPERA A CLASSE. Quando a fonte de fato sabe quando a
        # correção ficou disponível, a comparação é objetiva e a classificação
        # conservadora deixa de ser necessária.
        if e_revisao and carimbo is not None and as_of.mode.is_causal:
            sabido = as_of.knows(carimbo)
            if sabido is False:
                return LeakageDecision.denied(
                    LeakageReason.KNOWLEDGE_TIME_AFTER_CUTOFF,
                    f"a correção {event.id} só ficou conhecida em {carimbo}",
                )
            if sabido is None:
                return LeakageDecision.unknown(
                    LeakageReason.MISSING_KNOWLEDGE_CUTOFF,
                    "a correção tem carimbo e o corte não declara conhecimento",
                )
            return self.guard.evaluate(
                FactTiming.event(
                    _posicao(event), revision=False, knowledge=carimbo, label=str(event.id)
                ),
                as_of,
            )
        return self.guard.evaluate(
            FactTiming.event(
                _posicao(event),
                revision=e_revisao,
                knowledge=carimbo,
                label=str(event.id),
            ),
            as_of,
        )


def _posicao(event: CanonicalMatchEvent) -> MatchTimePoint:
    return MatchTimePoint.from_clock(event.clock, sequence=event.sequence)


def _em_ordem(events: Iterable[CanonicalMatchEvent]) -> tuple[CanonicalMatchEvent, ...]:
    """A ordem canônica, imposta aqui (§131).

    ELA NÃO É HERDADA DA ENTRADA. Duas leituras do mesmo corpus podem devolver
    os mesmos eventos em ordens diferentes — plano de consulta, ordem de
    arquivo —, e a projeção precisa produzir o mesmo resultado nos dois casos.
    O desempate final é o `id`, que é derivado e estável.
    """
    return tuple(sorted(events, key=lambda e: (_posicao(e), str(e.id))))


def _recusar_partida_errada(events: Sequence[CanonicalMatchEvent], as_of: FeatureAsOf) -> None:
    """Um evento de outra partida na projeção é defeito de quem chamou.

    ELE NÃO É FILTRADO EM SILÊNCIO. Filtrar esconderia o erro e produziria uma
    projeção plausível de um jogo que não é o pedido — o pior desfecho
    possível, porque nada denuncia.
    """
    de_outra = [e for e in events if e.match_id != as_of.match_id]
    if de_outra:
        raise ValidationError(
            f"a projeção de {as_of.match_id} recebeu {len(de_outra)} evento(s) de "
            f"outra partida, a começar por {de_outra[0].id}",
            context={"match_id": str(as_of.match_id), "foreign": str(de_outra[0].id)},
        )


def _resolver_cadeia(
    admitidos: Sequence[CanonicalMatchEvent],
) -> tuple[ProjectedEvent, ...]:
    """Quem está vigente depois de aplicar as correções ADMITIDAS (§76, §77).

    A REGRA É SIMPLES E O EFEITO É O ESPERADO: um evento substituído por uma
    correção que ENTROU sai da visão; um substituído por uma correção que NÃO
    entrou permanece — na forma original, marcado como `correction_withheld`.

    Cancelados não aparecem: um gol anulado não faz parte do estado do jogo. Ele
    continua no corpus, que é onde a auditoria o encontra.
    """
    substituidos = {e.supersedes for e in admitidos if e.supersedes is not None}
    projetados: list[ProjectedEvent] = []
    for evento in admitidos:
        if evento.id in substituidos:
            continue
        if evento.status not in _ESTADOS_VIGENTES:
            # `CORRECTED` sem sucessor admitido: a correção existe no corpus e
            # não entrou nesta projeção. O fato ORIGINAL continua sendo o que
            # se sabia — e o marcador diz que há uma correção lá fora.
            if evento.status is EventStatus.CORRECTED:
                projetados.append(ProjectedEvent(event=evento, correction_withheld=True))
            continue
        projetados.append(ProjectedEvent(event=evento))
    return tuple(projetados)
