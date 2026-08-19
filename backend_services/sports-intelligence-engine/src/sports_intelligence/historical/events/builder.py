"""`CanonicalEventBuilder` — o registro da fonte vira fato canônico. E só.

O QUE ELE FAZ: recebe um registro cuja elegibilidade JÁ foi decidida, com as
referências JÁ traduzidas, e monta o `CanonicalMatchEvent` com os detalhes
tipados que o PR-01 definiu.

O QUE ELE NÃO FAZ, e cada linha desta lista é uma porta que ficaria aberta
(§56):

    não resolve identidade    isso é o PR-03. Um `TeamId` inventado aqui
                              atribuiria um fato a quem não o praticou
    não recalcula qualidade   a decisão vem pronta; recalcular criaria uma
                              segunda opinião sobre a mesma evidência
    não funde provedores      isso não existe neste PR, e é deliberado (§25)
    não calcula feature       xG que a fonte deu é OBSERVADO; xG que o motor
                              calculasse seria DERIVADO, e a distinção é o
                              ADR-0009 inteiro (§119)

ELE FALHA FECHADO (§57). Quando falta o que o tipo exige, ele não inventa —
levanta. A elegibilidade já deveria ter recusado antes, e a guarda aqui é a
segunda: uma delas sem a outra transformaria um defeito de orquestração em
fato canônico errado.

A IDENTIDADE CANÔNICA É DERIVADA (§20). `uuid5` sobre
`(provedor, id do evento, revisão)` — determinística, então reprocessar a
mesma fonte produz o MESMO id e o `ON CONFLICT` do banco reconhece o que já
está lá. Um `uuid4` faria toda releitura duplicar o corpus de eventos.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final, final

from sports_intelligence.domain.events.canonical import CanonicalMatchEvent, EventStatus
from sports_intelligence.domain.events.coordinates import (
    CoordinateFrame,
    PitchCoordinate,
)
from sports_intelligence.domain.events.details import (
    BodyPart,
    CardDetail,
    CardType,
    EventDetail,
    ShotDetail,
    ShotOutcome,
    SubstitutionDetail,
)
from sports_intelligence.domain.events.records import (
    EventRevisionKind,
    HistoricalEventRecord,
)
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.feature_value import FeatureValue, Unavailability
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.provenance import DataProvenance
from sports_intelligence.domain.shared.quality import DataQuality
from sports_intelligence.domain.shared.temporal import MatchClock
from sports_intelligence.historical.events.references import EventReferences

#: O espaço de nomes da derivação determinística do id canônico.
#:
#: ELE É FIXO E NOMEADO. Mudá-lo re-chaveia todo evento já persistido: dois
#: processamentos da mesma fonte, um antes e um depois, produziriam eventos
#: diferentes para o mesmo fato — e o banco os aceitaria como dois.
EVENT_ID_NAMESPACE: Final[uuid.UUID] = uuid.UUID("6f0d8a1e-6c8a-5f6b-9a1c-3d2e4b5a6c7d")

#: O referencial das coordenadas que a fonte entrega. Declarado, nunca suposto
#: (ADR-0012): uma fonte que normaliza pelo sentido de ataque e outra que
#: normaliza pelo estádio produzem números idênticos com significados opostos.
DEFAULT_COORDINATE_FRAME: Final[CoordinateFrame] = CoordinateFrame.ATTACKING

#: A qualidade de um evento construído a partir de fonte declarada. Ela existe
#: porque `CanonicalMatchEvent` a exige desde o PR-01; os eixos aqui são os do
#: `DataQuality` (quatro), que é outro objeto do `QualityVector` (seis) — e
#: misturar os dois seria o sétimo eixo que o §43 proíbe.
_QUALIDADE_DE_FONTE_DECLARADA: Final[DataQuality] = DataQuality(
    completeness=1.0, consistency=1.0, freshness=1.0, identity_confidence=1.0
)


def canonical_event_id(*, source_key: str, revision: int, match_id: MatchId) -> uuid.UUID:
    """O id canônico, DERIVADO e estável entre execuções (§20, §24).

    O QUE ENTRA E POR QUÊ:

        chave da fonte   `provedor:id_do_evento` — a identidade forte
        revisão          uma correção é um evento NOVO, com id próprio; sem a
                         revisão na derivação ela colidiria com o original e
                         o `ON CONFLICT` a trataria como reprocessamento
        partida          a âncora canônica. Sem ela, dois provedores com o
                         mesmo id de evento em partidas diferentes colidiriam

    O QUE NÃO ENTRA: número da linha, instante de ingestão, `uuid4`. Os três
    fariam a mesma fonte lida duas vezes produzir eventos diferentes, e o
    corpus dobraria a cada reprocessamento.
    """
    return uuid.uuid5(EVENT_ID_NAMESPACE, f"{match_id}|{source_key}|r{revision}")


@final
@dataclass(frozen=True, slots=True)
class CanonicalEventBuilder:
    """Monta `CanonicalMatchEvent` a partir de registro e referências."""

    def build(
        self,
        record: HistoricalEventRecord,
        *,
        match_id: MatchId,
        event_type: EventType,
        references: EventReferences,
        provenance: DataProvenance,
        source_key: str,
        sequence: int,
        revision: int = 1,
        supersedes: uuid.UUID | None = None,
    ) -> CanonicalMatchEvent:
        """Constrói. Levanta quando falta o que o tipo exige (§57)."""
        time = references.team_for(record)
        jogador = references.player_for(record)

        # A GUARDA É A SEGUNDA, e não a primeira: a elegibilidade já recusou
        # isto. Ela está aqui porque o construtor é público e um caminho novo
        # que o chamasse direto não pode produzir fato inventado.
        if event_type.requires_team and time is None:
            raise ValidationError(
                f"{event_type} exige time e a referência não resolveu — inventar "
                "um dono distorce toda contagem por equipe"
            )
        if event_type.requires_player and jogador is None:
            raise ValidationError(f"{event_type} exige executante e a referência não resolveu")
        # O TIPO QUE NÃO TEM DONO NÃO PODE RECEBER UM. O domínio recusa desde
        # o PR-01, e passar o time «porque a linha tinha» transformaria um
        # apito final em evento do mandante.
        if not event_type.requires_team:
            time = None
        if not event_type.requires_player:
            jogador = None

        return CanonicalMatchEvent(
            id=canonical_event_id(source_key=source_key, revision=revision, match_id=match_id),
            match_id=match_id,
            type=event_type,
            clock=MatchClock(
                period=record.clock.period,
                minute=record.clock.minute,
                stoppage=record.clock.stoppage,
            ),
            sequence=sequence,
            provenance=provenance,
            quality=_QUALIDADE_DE_FONTE_DECLARADA,
            team_id=time,
            player_id=jogador,
            start_location=_ponto(record.start_point),
            end_location=_ponto(record.end_point),
            detail=self.detail_for(record, event_type, references),
            revision=revision,
            supersedes=supersedes,
            status=EventStatus.ACTIVE,
        )

    def detail_for(
        self,
        record: HistoricalEventRecord,
        event_type: EventType,
        references: EventReferences,
    ) -> EventDetail | None:
        """O detalhe TIPADO do evento — nunca um `dict[str, Any]` (§30).

        `None` É LEGÍTIMO: um apito inicial não tem detalhe próprio, e um
        detalhe vazio obrigatório seria ruído em toda linha estrutural.

        SÓ OS TIPOS QUE O CONTRATO SABE RECEBER. `PassDetail`, `DuelDetail` e
        `GoalkeeperDetail` existem no domínio e não têm papéis semânticos
        declarados neste PR — construí-los a partir de campos inventados seria
        preencher contrato com suposição.
        """
        if event_type in (EventType.SHOT, EventType.GOAL):
            return self._finalizacao(record, event_type)
        if event_type is EventType.CARD:
            return self._cartao(record)
        if event_type is EventType.SUBSTITUTION:
            return self._substituicao(record, references)
        return None

    @staticmethod
    def _finalizacao(record: HistoricalEventRecord, event_type: EventType) -> ShotDetail:
        """A finalização, com o xG que a FONTE observou.

        `xg` AUSENTE NÃO É `xg = 0` (§32, §94). Zero significa «chance nula»,
        que é uma afirmação sobre algo não medido — e ela entraria em qualquer
        média como se fosse observação. `FeatureValue.absent` diz que não
        houve medida, e `FeatureValue.of(0.0)` diz que a medida foi zero: as
        duas existem, e são coisas diferentes.
        """
        bruto = record.detail("EVENT_OUTCOME")
        desfecho = _desfecho(bruto, event_type)
        parte = _parte_do_corpo(record.detail("EVENT_BODY_PART"))
        return ShotDetail(
            outcome=desfecho,
            body_part=parte,
            xg=_xg(record.detail("EVENT_XG")),
        )

    @staticmethod
    def _cartao(record: HistoricalEventRecord) -> CardDetail:
        bruto = (record.detail("EVENT_CARD_TYPE") or "").strip().upper()
        try:
            tipo = CardType(bruto)
        except ValueError as erro:
            raise ValidationError(
                f"cartão {bruto!r} desconhecido: o catálogo tem "
                f"{[c.value for c in CardType]}. Escolher um por conta própria "
                "confundiria segundo amarelo com vermelho direto, que descrevem "
                "situações diferentes"
            ) from erro
        return CardDetail(card_type=tipo)

    @staticmethod
    def _substituicao(
        record: HistoricalEventRecord, references: EventReferences
    ) -> SubstitutionDetail:
        saiu = references.player_by_reference(record.detail("EVENT_PLAYER_OUT_PROVIDER_ID"))
        entrou = references.player_by_reference(record.detail("EVENT_PLAYER_IN_PROVIDER_ID"))
        if saiu is None or entrou is None:
            raise ValidationError(
                "substituição sem os dois jogadores resolvidos — um par "
                "desemparelhado é exatamente o que o detalhe tipado impede"
            )
        return SubstitutionDetail(player_out=saiu, player_in=entrou)


def _ponto(bruto: object) -> PitchCoordinate | None:
    """A coordenada canônica. AUSENTE CONTINUA AUSENTE (§93).

    `None` não vira `(0, 0)`: a origem do campo é uma posição real — a linha
    de fundo, na lateral —, e usá-la como «sem coordenada» colocaria todo
    evento sem dado espacial no mesmo canto do gramado.
    """
    if bruto is None:
        return None
    x = getattr(bruto, "x", None)
    y = getattr(bruto, "y", None)
    if x is None or y is None:
        return None
    return PitchCoordinate(x=float(x), y=float(y), frame=DEFAULT_COORDINATE_FRAME)


def _xg(bruto: str | None) -> FeatureValue | None:
    """O xG observado. `None` quando a fonte não declara o campo.

    TRÊS ESTADOS E NÃO DOIS, e a diferença entre eles é o §94:

        campo ausente        `None` — a fonte não trabalha com xG
        campo vazio          `NOT_PUBLISHED` — trabalha e não publicou este
        `0.00`               `FeatureValue.of(0.0)` — MEDIU, e deu zero

    O TEXTO ILEGÍVEL VIRA `REJECTED_BY_VALIDATION` e não silêncio: um `n/a`
    numa coluna de xG é um defeito da fonte, e apagá-lo faria a ausência
    parecer escolha do provedor.
    """
    if bruto is None:
        return None
    texto = bruto.strip()
    if not texto:
        return FeatureValue.absent(Unavailability.NOT_PUBLISHED)
    try:
        return FeatureValue.of(float(Decimal(texto)))
    except (InvalidOperation, ValueError):
        return FeatureValue.absent(Unavailability.REJECTED_BY_VALIDATION)


def _desfecho(bruto: str | None, event_type: EventType) -> ShotOutcome:
    """O desfecho da finalização.

    UM `GOAL` SEM DESFECHO DECLARADO É `GOAL`, e não é suposição: o tipo do
    evento já afirma que a bola entrou. Um `SHOT` sem desfecho é outra
    história — aí a fonte não disse o que aconteceu, e inventar «defendido»
    ou «para fora» seria fabricar o dado mais importante do evento.
    """
    if bruto is None or not bruto.strip():
        if event_type is EventType.GOAL:
            return ShotOutcome.GOAL
        raise ValidationError(
            "finalização sem desfecho declarado: qual foi o resultado é o dado "
            "central do evento, e supô-lo produziria estatística inventada"
        )
    texto = bruto.strip().upper()
    try:
        return ShotOutcome(texto)
    except ValueError as erro:
        raise ValidationError(
            f"desfecho de finalização {texto!r} desconhecido: o catálogo tem "
            f"{[o.value for o in ShotOutcome]}"
        ) from erro


def _parte_do_corpo(bruto: str | None) -> BodyPart | None:
    if bruto is None or not bruto.strip():
        return None
    try:
        return BodyPart(bruto.strip().upper())
    except ValueError:
        # PARTE DO CORPO DESCONHECIDA NÃO INVALIDA A FINALIZAÇÃO. Ela é
        # enriquecimento; recusar o chute inteiro por causa dela perderia o
        # fato principal por causa de um adjetivo.
        return None


def revision_status_for(kind: EventRevisionKind) -> EventStatus:
    """O estado que uma linha de revisão produz no evento NOVO."""
    if kind is EventRevisionKind.CANCELLATION:
        return EventStatus.CANCELLED
    return EventStatus.ACTIVE
