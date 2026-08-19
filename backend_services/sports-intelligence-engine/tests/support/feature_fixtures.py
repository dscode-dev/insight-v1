"""O cenário temporal do PR-05.1 — uma partida com tudo que vaza.

O JOGO SINTÉTICO (§122), montado para que cada corte tenha uma resposta que se
possa conferir a olho:

    pré-jogo   escalação divulgada · cotação às 19:30
    10'        passe          A
    20'        chute          B
    30'        GOL            C
    35'        correção de C  C2   (conhecida às 19:52)
    40'        substituição   D
    ---------- corte de referência: 63' ----------
    70'        substituição   E
    78'        GOL            F
    pós-jogo   resultado 2 a 1 · cotação de fechamento

E UM SENTINELA (§125): um evento aos 80 com valor absurdo, que existe para que
qualquer feature causal que o enxergue produza um número obviamente errado em
vez de um número plausível.

TUDO DERIVADO, NADA SORTEADO. As identidades saem de `uuid5` sobre rótulos
estáveis, porque duas execuções do mesmo teste precisam produzir as mesmas
impressões — e um `uuid4` faria todo teste de determinismo passar ou falhar por
acidente.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import (
    Competition,
    CompetitionRegime,
    RegimeCode,
    Season,
    Stage,
    StageType,
)
from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.events.canonical import CanonicalMatchEvent, EventStatus
from sports_intelligence.domain.events.coordinates import PitchCoordinate
from sports_intelligence.domain.events.details import (
    BodyPart,
    EventDetail,
    ShotDetail,
    ShotOutcome,
    SubstitutionDetail,
)
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.context import (
    CanonicalFeatureContext,
    CorpusSource,
)
from sports_intelligence.domain.features.definitions import (
    FeatureDefinition,
    FeatureOutputType,
    FeatureScope,
    FeatureTemporalClass,
)
from sports_intelligence.domain.features.projection import EventKnowledge
from sports_intelligence.domain.features.space import (
    CorpusRequirement,
    FeatureSpaceDefinition,
)
from sports_intelligence.domain.features.temporal import FeatureAsOf, TemporalMode
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.lineup import Lineup, LineupEntry, LineupStatus
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.matches.result import MatchResult, Score
from sports_intelligence.domain.odds.models import (
    BookmakerRef,
    CanonicalOddsObservation,
    OddsMarket,
    OddsSelection,
)
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.feature_value import FeatureValue
from sports_intelligence.domain.shared.identity import (
    MatchId,
    PlayerId,
    ProviderId,
    TeamId,
)
from sports_intelligence.domain.shared.provenance import (
    DataProvenance,
    LicenseClass,
    SourceType,
)
from sports_intelligence.domain.shared.quality import DataQuality
from sports_intelligence.domain.shared.temporal import (
    Instant,
    MatchClock,
    ObservationTimes,
    Period,
    instant,
)
from sports_intelligence.domain.shared.versioning import DatasetVersion, FeatureSpaceVersion

# ------------------------------------------------------------ identidades --

PARTIDA: Final[MatchId] = MatchId.derive("pr051", "partida-de-referencia")
CASA: Final[TeamId] = TeamId.derive("pr051", "mandante")
FORA: Final[TeamId] = TeamId.derive("pr051", "visitante")
ARTILHEIRO: Final[PlayerId] = PlayerId.derive("pr051", "artilheiro")
RESERVA: Final[PlayerId] = PlayerId.derive("pr051", "reserva")
OUTRO_RESERVA: Final[PlayerId] = PlayerId.derive("pr051", "outro-reserva")
PROVEDOR: Final[ProviderId] = ProviderId("fonte_de_referencia")

#: O apito inicial. Todo instante de parede do cenário é relativo a ele, para
#: que a leitura do teste não precise fazer contas de fuso.
KICKOFF: Final[Instant] = instant(datetime(2026, 3, 14, 19, 45, tzinfo=UTC))

_REGIME: Final[CompetitionRegime] = CompetitionRegime(
    code=RegimeCode.DOUBLE_ROUND_ROBIN,
    effective_from=instant(datetime(1990, 1, 1, tzinfo=UTC)),
    regulation_version="pr051",
)


def relogio_de_parede(minutos: float) -> Instant:
    """O instante de parede de um minuto de jogo — SÓ para o cenário.

    ELA NÃO É UMA CONVERSÃO DE PRODUÇÃO (§5). No mundo real o minuto 63 não
    acontece 63 minutos depois do apito: há paralisação, VAR e intervalo. O
    corpus não sabe converter, e é por isso que as duas réguas do
    `FeatureAsOf` não se convertem uma na outra. Aqui a conversão existe porque
    o cenário é sintético e o teste precisa de instantes coerentes.
    """
    return instant(KICKOFF + timedelta(minutes=minutos))


# ----------------------------------------------------------------- partida --


def competicao() -> Competition:
    return Competition.from_code(CompetitionCode.PREMIER_LEAGUE)


def temporada() -> Season:
    liga = competicao()
    return Season.create(
        competition_id=liga.id,
        label="2025/26",
        starts_at=instant(datetime(2025, 8, 1, tzinfo=UTC)),
        ends_at=instant(datetime(2026, 5, 31, tzinfo=UTC)),
        regime=_REGIME,
    )


def partida() -> Match:
    liga, epoca = competicao(), temporada()
    return Match(
        id=PARTIDA,
        competition_id=liga.id,
        season_id=epoca.id,
        regime=_REGIME,
        stage=Stage(type=StageType.LEAGUE, round_number=28),
        home_team_id=CASA,
        away_team_id=FORA,
        scheduled_kickoff=KICKOFF,
        lifecycle=MatchLifecycle.RECONCILED,
    )


def resultado() -> MatchResult:
    """2 a 1. Ele NUNCA pode aparecer num estado intra-jogo (§13, §73)."""
    return MatchResult(regular_time=Score(home=2, away=1))


def escalacao() -> tuple[Lineup, ...]:
    return (
        Lineup(
            match_id=PARTIDA,
            team_id=CASA,
            entries=(
                LineupEntry(
                    player_id=ARTILHEIRO, status=LineupStatus.STARTER, shirt_number=9
                ),
                LineupEntry(
                    player_id=RESERVA, status=LineupStatus.BENCH, shirt_number=19
                ),
                LineupEntry(
                    player_id=OUTRO_RESERVA, status=LineupStatus.BENCH, shirt_number=23
                ),
            ),
        ),
    )


# ----------------------------------------------------------------- eventos --


#: A procedência do cenário. Pública porque o cenário do PR-05.2 a reaproveita:
#: dois construtores de procedência produziriam eventos de «fontes» diferentes
#: dentro do mesmo teste, e a diferença apareceria na impressão.
def procedencia_do_cenario(momento: Instant) -> DataProvenance:
    return DataProvenance(
        source_type=SourceType.OPEN_DATA,
        provider_id=PROVEDOR,
        source_record_id="cenario-pr051",
        times=ObservationTimes.at_once(momento),
        license_class=LicenseClass.PUBLIC_DOMAIN,
    )


def _id(rotulo: str) -> uuid.UUID:
    return uuid.uuid5(uuid.UUID("00000000-0000-5000-8000-0000000051a1"), rotulo)


def evento(
    rotulo: str,
    *,
    minuto: int,
    tipo: EventType = EventType.PASS,
    periodo: Period = Period.FIRST_HALF,
    sequencia: int = 0,
    stoppage: int = 0,
    jogador: PlayerId | None = ARTILHEIRO,
    time: TeamId | None = CASA,
    supersedes: uuid.UUID | None = None,
    status: EventStatus = EventStatus.ACTIVE,
    revision: int = 1,
    xg: str | None = None,
    substituicao: tuple[PlayerId, PlayerId] | None = None,
) -> CanonicalMatchEvent:
    detalhe: EventDetail | None = None
    if tipo in (EventType.SHOT, EventType.GOAL):
        detalhe = ShotDetail(
            outcome=ShotOutcome.GOAL if tipo is EventType.GOAL else ShotOutcome.SAVED,
            body_part=BodyPart.RIGHT_FOOT,
            xg=None if xg is None else _feature_value(xg),
        )
    elif substituicao is not None:
        detalhe = SubstitutionDetail(player_out=substituicao[0], player_in=substituicao[1])
    return CanonicalMatchEvent(
        id=_id(rotulo),
        match_id=PARTIDA,
        type=tipo,
        clock=MatchClock(period=periodo, minute=minuto, stoppage=stoppage),
        sequence=sequencia,
        provenance=procedencia_do_cenario(relogio_de_parede(minuto)),
        quality=DataQuality(
            completeness=1.0, consistency=1.0, freshness=1.0, identity_confidence=1.0
        ),
        team_id=time,
        player_id=jogador,
        start_location=(
            None if tipo not in (EventType.SHOT, EventType.GOAL, EventType.PASS)
            else PitchCoordinate(x=0.7, y=0.5)
        ),
        detail=detalhe,
        revision=revision,
        supersedes=supersedes,
        status=status,
    )


def _feature_value(bruto: str) -> FeatureValue:
    return FeatureValue.of(float(Decimal(bruto)))


#: Os rótulos do cenário, nomeados para que o teste cite o evento pelo nome.
GOL_C: Final[str] = "gol-c"
CORRECAO_C2: Final[str] = "correcao-c2"
GOL_F: Final[str] = "gol-f"
SENTINELA: Final[str] = "sentinela-80"


def historia() -> tuple[CanonicalMatchEvent, ...]:
    """A história canônica COMPLETA — com futuro e correção dentro.

    ELA É O QUE O CORPUS GUARDA, e não o que um corte enxerga. Entregá-la
    inteira aos testes é o ponto: o que se quer provar é que a projeção e o
    guarda tiram do caminho o que não podia ser sabido.
    """
    return (
        evento("passe-a", minuto=10, tipo=EventType.PASS, jogador=ARTILHEIRO, sequencia=1),
        evento(
            "chute-b",
            minuto=20,
            tipo=EventType.SHOT,
            jogador=ARTILHEIRO,
            sequencia=2,
            xg="0.11",
        ),
        # O GOL C e a CORREÇÃO dele. O corrigido fica `CORRECTED` no corpus, e
        # o sucessor aponta para ele — exatamente como o PR-04.4.1 grava.
        evento(
            GOL_C,
            minuto=30,
            tipo=EventType.GOAL,
            jogador=ARTILHEIRO,
            sequencia=3,
            xg="0.30",
            status=EventStatus.CORRECTED,
        ),
        evento(
            CORRECAO_C2,
            minuto=31,
            tipo=EventType.GOAL,
            jogador=ARTILHEIRO,
            sequencia=4,
            xg="0.42",
            revision=2,
            supersedes=_id(GOL_C),
        ),
        evento(
            "substituicao-d",
            minuto=40,
            tipo=EventType.SUBSTITUTION,
            jogador=None,
            sequencia=5,
            substituicao=(ARTILHEIRO, RESERVA),
        ),
        # ---- tudo daqui para baixo é FUTURO em relação ao corte de 63' ----
        evento(
            "substituicao-e",
            minuto=70,
            tipo=EventType.SUBSTITUTION,
            periodo=Period.SECOND_HALF,
            jogador=None,
            sequencia=6,
            substituicao=(RESERVA, OUTRO_RESERVA),
        ),
        evento(
            GOL_F,
            minuto=78,
            tipo=EventType.GOAL,
            periodo=Period.SECOND_HALF,
            jogador=RESERVA,
            sequencia=7,
            xg="0.55",
        ),
    )


#: Quantos eventos o sentinela do §125 acrescenta ao futuro. O número é
#: absurdo de propósito: qualquer feature causal que enxergue o futuro salta de
#: uma casa decimal, e o teste falha com um valor que ninguém confunde com
#: ruído.
SENTINELA_QUANTIDADE: Final[int] = 999


def historia_com_sentinela() -> tuple[CanonicalMatchEvent, ...]:
    """A história COMPLETA mais uma rajada absurda no futuro (§125).

    ELE NÃO É UM VALOR ESTRANHO NUM CAMPO — o domínio recusaria um xG de
    999999, e com razão: é uma probabilidade. O sentinela é uma QUANTIDADE
    absurda de eventos aos 80 minutos, que é o que uma feature de contagem
    causal jamais pode enxergar.
    """
    rajada = tuple(
        evento(
            f"{SENTINELA}-{n}",
            minuto=80,
            tipo=EventType.SHOT,
            periodo=Period.SECOND_HALF,
            jogador=RESERVA,
            sequencia=100 + n,
            xg="0.99",
        )
        for n in range(SENTINELA_QUANTIDADE)
    )
    return (*historia(), *rajada)


def historia_ate_o_corte() -> tuple[CanonicalMatchEvent, ...]:
    """Só o passado do corte de 63' — o conjunto `F≤t` do §126."""
    return tuple(
        e
        for e in historia()
        if e.clock.period is Period.FIRST_HALF and e.clock.minute <= 63
    )


def futuro_do_corte() -> tuple[CanonicalMatchEvent, ...]:
    """Só o futuro — o conjunto `F>t`."""
    passados = {e.id for e in historia_ate_o_corte()}
    return tuple(e for e in historia() if e.id not in passados)


def conhecimento_das_correcoes() -> EventKnowledge:
    """Quando a correção ficou conhecida: 19:52, sete minutos depois do gol.

    O GOL É DOS 30 E A CORREÇÃO É CONHECIDA NO MINUTO 35 DE PARTIDA. Um replay
    aos 33 não pode enxergá-la; um replay aos 40, pode.
    """
    return EventKnowledge(by_event={_id(CORRECAO_C2): relogio_de_parede(35)})


# ------------------------------------------------------------------- odds --


def cotacao(minuto: float, *, valor: str = "1.80") -> CanonicalOddsObservation:
    return CanonicalOddsObservation(
        match_id=PARTIDA,
        bookmaker=BookmakerRef(code="BET365"),
        market=OddsMarket.MATCH_RESULT_1X2,
        selection=OddsSelection.HOME,
        decimal_odds=Decimal(valor),
        observed_at=relogio_de_parede(minuto),
        provenance=procedencia_do_cenario(relogio_de_parede(minuto)),
    )


def cotacao_sem_carimbo(valor: str = "1.95") -> CanonicalOddsObservation:
    """A cotação de fechamento sem instante (§18).

    ELA NÃO PODE SER TRATADA COMO PRÉ-JOGO por existir: sem carimbo, não há o
    que provar, e o guarda a recusa em modo causal.
    """
    return CanonicalOddsObservation(
        match_id=PARTIDA,
        bookmaker=BookmakerRef(code="PINNACLE"),
        market=OddsMarket.MATCH_RESULT_1X2,
        selection=OddsSelection.HOME,
        decimal_odds=Decimal(valor),
        observed_at=None,
        provenance=procedencia_do_cenario(KICKOFF),
    )


# ------------------------------------------------------------- corpus/corte --


def origem(
    *,
    families: frozenset[CoverageFamily] = frozenset(
        {CoverageFamily.MATCH, CoverageFamily.LINEUP, CoverageFamily.EVENT}
    ),
    fingerprint: str = "a" * 64,
) -> CorpusSource:
    return CorpusSource(
        version_id="55555555-5555-4555-8555-555555555555",
        version=DatasetVersion(major=1, minor=0),
        corpus_fingerprint=ContentHash(fingerprint),
        published_families=families,
    )


def corte(
    minuto: int = 63,
    *,
    periodo: Period = Period.SECOND_HALF,
    mode: TemporalMode = TemporalMode.AS_KNOWN,
    conhecimento: float | None = None,
) -> FeatureAsOf:
    """O corte do cenário. O padrão é o de referência: 63 minutos.

    `conhecimento` É EM MINUTOS DE JOGO por conveniência do teste — ele vira
    instante de parede pela conversão sintética, que só existe aqui.
    """
    return FeatureAsOf.at(
        PARTIDA,
        periodo,
        minuto,
        mode=mode,
        knowledge_cutoff=None if conhecimento is None else relogio_de_parede(conhecimento),
    )


def contexto(
    *,
    as_of: FeatureAsOf | None = None,
    eventos: tuple[CanonicalMatchEvent, ...] | None = None,
    policy: TemporalAvailabilityPolicy | None = None,
    com_resultado: bool = True,
    odds: tuple[CanonicalOddsObservation, ...] = (),
    knowledge: EventKnowledge | None = None,
) -> CanonicalFeatureContext:
    """O contexto do cenário, com a projeção já aplicada."""
    return CanonicalFeatureContext.build(
        as_of=as_of or corte(),
        source=origem(),
        policy=policy or TemporalAvailabilityPolicy.default(),
        match=partida(),
        canonical_events=historia() if eventos is None else eventos,
        knowledge=knowledge,
        lineups=escalacao(),
        odds=odds,
        result=resultado() if com_resultado else None,
    )


# --------------------------------------------------- definições de TESTE --
#
# ELAS NÃO SÃO FEATURES DE PRODUÇÃO (§32, §92). Existem para exercitar o
# contrato — nenhuma é registrada fora dos testes, e nenhuma calcula pressão,
# força de time ou janela móvel.


def definicao_de_teste(
    key: str = "test_event_count",
    *,
    version: tuple[int, int] = (1, 0),
    parameters: dict[str, str | int | float | bool | None] | None = None,
    temporal_class: FeatureTemporalClass = FeatureTemporalClass.INTRA_MATCH_CAUSAL,
    output_type: FeatureOutputType = FeatureOutputType.INTEGER,
    scope: FeatureScope = FeatureScope.MATCH,
    families: tuple[CoverageFamily, ...] = (CoverageFamily.EVENT,),
    depends_on: tuple[str, ...] = (),
) -> FeatureDefinition:
    from sports_intelligence.domain.shared.versioning import Version

    return FeatureDefinition(
        key=key,
        version=Version(major=version[0], minor=version[1]),
        description="definição de teste do PR-05.1 — não é feature de produção",
        output_type=output_type,
        scope=scope,
        temporal_class=temporal_class,
        required_families=families,
        parameters=parameters or {},
        depends_on_features=depends_on,
    )


def espaco_de_teste(
    *definicoes: FeatureDefinition,
    live_comparable: bool = True,
    mode: TemporalMode = TemporalMode.AS_KNOWN,
    name: str = "test-space",
) -> FeatureSpaceDefinition:
    features = definicoes or (definicao_de_teste(),)
    exigidas = {f for d in features for f in d.required_families}
    return FeatureSpaceDefinition(
        name=name,
        version=FeatureSpaceVersion(major=1, minor=0),
        features=features,
        temporal_mode=mode,
        live_comparable=live_comparable,
        requirement=CorpusRequirement.of(*exigidas),
        description="espaço de teste do PR-05.1",
    )


def versao_publicada_falsa() -> object:
    """Uma versão de corpus mínima, só para provar a guarda de `CorpusSource`."""
    return DatasetVersionStatus.READY
