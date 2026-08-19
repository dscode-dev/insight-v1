"""O cenário do PR-05.2 — uma partida com ONZE de cada lado.

POR QUE UM CENÁRIO NOVO. O do PR-05.1 (`feature_fixtures`) foi montado para
exercitar CAUSALIDADE: ele tem um titular, dois reservas e uma correção. Isso
basta para provar que o futuro não vaza, e não basta para provar reconstrução
de ESTADO — um time com um titular nunca chega a onze, e a escalação parcial
do §23 tornaria todo estado degradado, escondendo justamente o caminho feliz.

Aqui os dois times têm elenco completo, e é sobre ele que as transições valem:

    pré-jogo    escalação dos dois lados publicada
    12'         GOL da casa            1-0
    25'         amarelo da casa
    34'         GOL de fora            1-1
    40'         substituição da casa   (titular 11 sai, reserva 12 entra)
    58'         vermelho de fora       (o time fica com dez)
    ---------- corte de referência: 63' ----------
    70'         GOL da casa            2-1  ← futuro
    75'         substituição de fora        ← futuro
    88'         segundo amarelo da casa     ← futuro

TUDO DERIVADO E NADA SORTEADO, pelo mesmo motivo do PR-05.1: duas execuções do
mesmo teste precisam produzir as MESMAS impressões, e um `uuid4` faria os
testes de determinismo passarem ou falharem por acidente.
"""

from __future__ import annotations

import uuid
from typing import Final

from sports_intelligence.domain.events.canonical import CanonicalMatchEvent, EventStatus
from sports_intelligence.domain.events.details import (
    BodyPart,
    CardDetail,
    CardType,
    EventDetail,
    ShotDetail,
    ShotOutcome,
    SubstitutionDetail,
)
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.projection import EventKnowledge
from sports_intelligence.domain.features.state.builder import (
    CanonicalMatchStateInput,
    HistoricalMatchStateBuilder,
    MatchStateBuildResult,
)
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.matches.lineup import Lineup, LineupEntry, LineupStatus
from sports_intelligence.domain.matches.result import MatchResult, Score
from sports_intelligence.domain.odds.models import CanonicalOddsObservation
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.identity import MatchId, PlayerId, TeamId
from sports_intelligence.domain.shared.quality import DataQuality
from sports_intelligence.domain.shared.temporal import Instant, MatchClock, Period
from tests.support.feature_fixtures import (
    CASA,
    FORA,
    PARTIDA,
    corte,
    origem,
    partida,
    procedencia_do_cenario,
    relogio_de_parede,
)

#: A raiz das identidades deste cenário. Separada da do PR-05.1 para que os
#: dois conjuntos de jogadores nunca colidam por acidente.
_RAIZ: Final[uuid.UUID] = uuid.UUID("00000000-0000-5000-8000-0000000052a2")

TITULARES: Final[int] = 11


def jogador(lado: str, numero: int) -> PlayerId:
    return PlayerId.derive("pr052", f"{lado}-{numero}")


#: Onze titulares e três reservas de cada lado.
CASA_TITULARES: Final[tuple[PlayerId, ...]] = tuple(
    jogador("casa", n) for n in range(1, TITULARES + 1)
)
CASA_BANCO: Final[tuple[PlayerId, ...]] = tuple(jogador("casa", n) for n in range(12, 15))
FORA_TITULARES: Final[tuple[PlayerId, ...]] = tuple(
    jogador("fora", n) for n in range(1, TITULARES + 1)
)
FORA_BANCO: Final[tuple[PlayerId, ...]] = tuple(jogador("fora", n) for n in range(12, 15))

TODAS_AS_FAMILIAS: Final[frozenset[CoverageFamily]] = frozenset(
    {
        CoverageFamily.MATCH,
        CoverageFamily.LINEUP,
        CoverageFamily.EVENT,
        CoverageFamily.ODDS,
    }
)


def _lineup(
    time: TeamId,
    titulares: tuple[PlayerId, ...],
    banco: tuple[PlayerId, ...],
    *,
    match_id: MatchId = PARTIDA,
) -> Lineup:
    entradas = [
        LineupEntry(player_id=p, status=LineupStatus.STARTER, shirt_number=n + 1)
        for n, p in enumerate(titulares)
    ]
    entradas += [
        LineupEntry(player_id=p, status=LineupStatus.BENCH, shirt_number=20 + n)
        for n, p in enumerate(banco)
    ]
    return Lineup(match_id=match_id, team_id=time, entries=tuple(entradas))


def escalacoes(
    *,
    titulares_casa: tuple[PlayerId, ...] | None = None,
    titulares_fora: tuple[PlayerId, ...] | None = None,
) -> tuple[Lineup, ...]:
    """As duas escalações completas — a base do estado em campo (§21)."""
    return (
        _lineup(CASA, titulares_casa or CASA_TITULARES, CASA_BANCO),
        _lineup(FORA, titulares_fora or FORA_TITULARES, FORA_BANCO),
    )


# ----------------------------------------------------------------- eventos --


def evento(
    rotulo: str,
    *,
    tipo: EventType,
    minuto: int,
    periodo: Period = Period.FIRST_HALF,
    sequencia: int = 0,
    stoppage: int = 0,
    time: TeamId | None = CASA,
    jogador_id: PlayerId | None = None,
    cartao: CardType | None = None,
    substituicao: tuple[PlayerId, PlayerId] | None = None,
    status: EventStatus = EventStatus.ACTIVE,
    revision: int = 1,
    supersedes: uuid.UUID | None = None,
    match_id: MatchId = PARTIDA,
    conhecido_em: Instant | None = None,
) -> CanonicalMatchEvent:
    """Um evento do cenário. O DETALHE VEM DO TIPO, e não de um parâmetro solto.

    Deixar o chamador passar um `CardDetail` para um `GOAL` permitiria montar,
    num teste, um evento que o corpus nunca produziria — e um teste que passa
    sobre um fato impossível não prova nada sobre produção.
    """
    # O MODELO CANÔNICO MANDA NO DONO E NO EXECUTANTE. `MATCH_START` não é de
    # ninguém e `CARD` exige quem levou; o cenário obedece em vez de repetir a
    # regra em cada chamada — um fixture que construísse um evento impossível
    # faria testes passarem sobre um fato que o corpus nunca produz.
    if not tipo.requires_team:
        time = None
    if tipo.requires_player and jogador_id is None:
        jogador_id = CASA_TITULARES[0] if time == CASA else FORA_TITULARES[0]

    detalhe: EventDetail | None = None
    if tipo is EventType.CARD and cartao is not None:
        detalhe = CardDetail(card_type=cartao or CardType.YELLOW)
    elif tipo is EventType.SUBSTITUTION and substituicao is not None:
        detalhe = SubstitutionDetail(player_out=substituicao[0], player_in=substituicao[1])
    elif tipo in (EventType.GOAL, EventType.SHOT):
        detalhe = ShotDetail(
            outcome=ShotOutcome.GOAL if tipo is EventType.GOAL else ShotOutcome.SAVED,
            body_part=BodyPart.RIGHT_FOOT,
        )
    return CanonicalMatchEvent(
        id=uuid.uuid5(_RAIZ, rotulo),
        match_id=match_id,
        type=tipo,
        clock=MatchClock(period=periodo, minute=minuto, stoppage=stoppage),
        sequence=sequencia,
        provenance=procedencia_do_cenario(conhecido_em or relogio_de_parede(minuto)),
        quality=DataQuality(
            completeness=1.0, consistency=1.0, freshness=1.0, identity_confidence=1.0
        ),
        team_id=time,
        player_id=jogador_id,
        start_location=None,
        detail=detalhe,
        revision=revision,
        supersedes=supersedes,
        status=status,
    )


def id_de(rotulo: str) -> uuid.UUID:
    return uuid.uuid5(_RAIZ, rotulo)


GOL_CASA_12: Final[str] = "gol-casa-12"
AMARELO_CASA_25: Final[str] = "amarelo-casa-25"
GOL_FORA_34: Final[str] = "gol-fora-34"
SUBSTITUICAO_CASA_40: Final[str] = "substituicao-casa-40"
VERMELHO_FORA_58: Final[str] = "vermelho-fora-58"
GOL_CASA_70: Final[str] = "gol-casa-70"
SUBSTITUICAO_FORA_75: Final[str] = "substituicao-fora-75"
SEGUNDO_AMARELO_CASA_88: Final[str] = "segundo-amarelo-casa-88"


def passado() -> tuple[CanonicalMatchEvent, ...]:
    """Os fatos ATÉ o corte de 63' — o conjunto que o estado pode enxergar."""
    return (
        evento(
            GOL_CASA_12,
            tipo=EventType.GOAL,
            minuto=12,
            sequencia=1,
            time=CASA,
            jogador_id=CASA_TITULARES[8],
        ),
        evento(
            AMARELO_CASA_25,
            tipo=EventType.CARD,
            minuto=25,
            sequencia=2,
            time=CASA,
            jogador_id=CASA_TITULARES[3],
            cartao=CardType.YELLOW,
        ),
        evento(
            GOL_FORA_34,
            tipo=EventType.GOAL,
            minuto=34,
            sequencia=3,
            time=FORA,
            jogador_id=FORA_TITULARES[8],
        ),
        evento(
            SUBSTITUICAO_CASA_40,
            tipo=EventType.SUBSTITUTION,
            minuto=40,
            sequencia=4,
            time=CASA,
            substituicao=(CASA_TITULARES[10], CASA_BANCO[0]),
        ),
        evento(
            VERMELHO_FORA_58,
            tipo=EventType.CARD,
            minuto=58,
            periodo=Period.SECOND_HALF,
            sequencia=5,
            time=FORA,
            jogador_id=FORA_TITULARES[4],
            cartao=CardType.RED,
        ),
    )


def futuro() -> tuple[CanonicalMatchEvent, ...]:
    """Os fatos DEPOIS do corte — nenhum pode aparecer no estado de 63'."""
    return (
        evento(
            GOL_CASA_70,
            tipo=EventType.GOAL,
            minuto=70,
            periodo=Period.SECOND_HALF,
            sequencia=6,
            time=CASA,
            jogador_id=CASA_BANCO[0],
        ),
        evento(
            SUBSTITUICAO_FORA_75,
            tipo=EventType.SUBSTITUTION,
            minuto=75,
            periodo=Period.SECOND_HALF,
            sequencia=7,
            time=FORA,
            substituicao=(FORA_TITULARES[9], FORA_BANCO[0]),
        ),
        evento(
            SEGUNDO_AMARELO_CASA_88,
            tipo=EventType.CARD,
            minuto=88,
            periodo=Period.SECOND_HALF,
            sequencia=8,
            time=CASA,
            jogador_id=CASA_TITULARES[3],
            cartao=CardType.SECOND_YELLOW,
        ),
    )


def historia() -> tuple[CanonicalMatchEvent, ...]:
    """A história canônica COMPLETA — passado e futuro juntos, como no corpus."""
    return (*passado(), *futuro())


def resultado_final() -> MatchResult:
    """2 a 1 — o que os eventos produzem no apito final, e só lá (§100)."""
    return MatchResult(regular_time=Score(home=2, away=1))


def origem_completa() -> CorpusSource:
    return origem(families=TODAS_AS_FAMILIAS)


# --------------------------------------------------------------- entrada --


def entrada(
    *,
    eventos: tuple[CanonicalMatchEvent, ...] | None = None,
    lineups: tuple[Lineup, ...] | None = None,
    families: frozenset[CoverageFamily] | None = None,
    odds: tuple[CanonicalOddsObservation, ...] = (),
    result: MatchResult | None = None,
    knowledge: EventKnowledge | None = None,
) -> CanonicalMatchStateInput:
    """Os insumos de uma partida, como a leitura do corpus os entregaria."""
    return CanonicalMatchStateInput(
        match=partida(),
        competition_code="PREMIER_LEAGUE",
        season_label="2025/26",
        published_families=TODAS_AS_FAMILIAS if families is None else families,
        candidate_events=historia() if eventos is None else eventos,
        lineups=escalacoes() if lineups is None else lineups,
        odds=odds,
        result=result,
        knowledge=knowledge or EventKnowledge(),
    )


def construir(
    entrada_: CanonicalMatchStateInput | None = None,
    *,
    as_of: FeatureAsOf | None = None,
    policy: TemporalAvailabilityPolicy | None = None,
) -> MatchStateBuildResult:
    """Reconstrói com os padrões do cenário — corte de 63' e política padrão."""
    return HistoricalMatchStateBuilder(
        policy=policy or TemporalAvailabilityPolicy.default()
    ).build(entrada_ or entrada(), as_of=as_of or corte(), source=origem_completa())
