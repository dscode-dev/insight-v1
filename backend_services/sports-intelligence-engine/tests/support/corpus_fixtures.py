"""Os fixtures do PR-04.3 — fatos de corpus, escopo, versões.

REAPROVEITAM OS IDS DO PR-04.2 (`build_fixtures`) e é deliberado: o corpus é
composto pelo que aquele build produziu, e um cenário com ids próprios testaria
uma integração que não existe.

TUDO DERIVADO, NADA SORTEADO. A impressão do corpus precisa ser a mesma em duas
execuções para que o §89 e o §88 possam ser afirmados — um `uuid4` aqui faria
todo teste de determinismo passar por acidente ou falhar por acidente.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Final

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import Stage, StageType
from sports_intelligence.domain.corpus.composition import (
    ComposedMatchCorpusFacts,
    PublishedEvent,
)
from sports_intelligence.domain.corpus.facts import MatchCorpusFacts
from sports_intelligence.domain.corpus.membership import CorpusMember
from sports_intelligence.domain.corpus.scope import CorpusScope, ScopeEntry
from sports_intelligence.domain.corpus.versions import (
    HistoricalCanonicalDataset,
    HistoricalCanonicalDatasetVersion,
    VersionInputs,
)
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.events.canonical import (
    CanonicalMatchEvent,
    EventStatus,
)
from sports_intelligence.domain.events.coordinates import PitchCoordinate
from sports_intelligence.domain.events.details import (
    BodyPart,
    CardDetail,
    CardType,
    EventDetail,
    ShotDetail,
    ShotOutcome,
)
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.matches.result import MatchResult, Score
from sports_intelligence.domain.odds.models import (
    BookmakerRef,
    CanonicalOddsObservation,
    OddsMarket,
    OddsSelection,
)
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.feature_value import FeatureValue, Unavailability
from sports_intelligence.domain.shared.identity import PlayerId, ProviderId
from sports_intelligence.domain.shared.provenance import (
    DataProvenance,
    LicenseClass,
    SourceType,
)
from sports_intelligence.domain.shared.quality import DataQuality
from sports_intelligence.domain.shared.temporal import (
    MatchClock,
    ObservationTimes,
    Period,
)
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.historical.events.builder import canonical_event_id
from tests.support.build_fixtures import (
    AGORA,
    CASA,
    COMPETICAO,
    FORA,
    KICKOFF,
    PUBLICA,
    REGIME,
    TEMPORADA,
    match_id,
)

TEMPORADA_LABEL: Final[str] = "2025/26"
COMPETICAO_CODE: Final[CompetitionCode] = CompetitionCode.PREMIER_LEAGUE

#: Um ator de serviço nomeado pelo que ELE É (PR-04.2 §75).
PUBLICADOR: Final[Actor] = Actor(id="historical-corpus-publisher", kind=ActorKind.SERVICE)

BUILD_RUN: Final[str] = "22222222-2222-4222-8222-222222222222"
QUALITY_RUN: Final[str] = "33333333-3333-4333-8333-333333333333"
ASSESSMENT: Final[str] = "44444444-4444-4444-8444-444444444444"
DATASET_ID: Final[str] = "55555555-5555-4555-8555-555555555555"


def escopo(usage: UsageScope = UsageScope.RESEARCH) -> CorpusScope:
    return CorpusScope.of(
        ScopeEntry(
            competition=COMPETICAO_CODE,
            season_label=TEMPORADA_LABEL,
            competition_id=COMPETICAO,
            season_id=TEMPORADA,
        ),
        usage=usage,
    )


def entradas(*, build_runs: tuple[str, ...] = (BUILD_RUN,)) -> VersionInputs:
    return VersionInputs(
        build_run_ids=build_runs,
        quality_run_ids=(QUALITY_RUN,),
        build_output_fingerprints=(ContentHash("a" * 64),),
    )


def dataset(name: str = "historical-core") -> HistoricalCanonicalDataset:
    return HistoricalCanonicalDataset(
        id=DATASET_ID, name=name, created_at=AGORA, created_by=PUBLICADOR
    )


def versao_rascunho(
    *, version: str = "1.0", usage: UsageScope = UsageScope.RESEARCH
) -> HistoricalCanonicalDatasetVersion:
    maior, _, menor = version.partition(".")
    return HistoricalCanonicalDatasetVersion.draft(
        dataset_id=DATASET_ID,
        version=DatasetVersion(major=int(maior), minor=int(menor)),
        scope=escopo(usage),
        inputs=entradas(),
        at=AGORA,
        created_by=PUBLICADOR,
    )


def partida(n: int = 0) -> Match:
    return Match(
        id=match_id(n),
        competition_id=COMPETICAO,
        season_id=TEMPORADA,
        regime=REGIME,
        stage=Stage(type=StageType.LEAGUE, round_number=1 + n % 38),
        home_team_id=CASA,
        away_team_id=FORA,
        scheduled_kickoff=KICKOFF,
        lifecycle=MatchLifecycle.RECONCILED,
    )


def observacao(n: int = 0, *, odds: str = "2.00") -> CanonicalOddsObservation:
    return CanonicalOddsObservation(
        match_id=match_id(n),
        bookmaker=BookmakerRef(code="bet365"),
        market=OddsMarket.MATCH_RESULT_1X2,
        selection=OddsSelection.HOME,
        decimal_odds=Decimal(odds),
        provenance=DataProvenance(
            source_type=SourceType.OPEN_DATA,
            provider_id=PUBLICA,
            source_record_id=f"linha-{n}",
            times=ObservationTimes.at_once(AGORA),
            license_class=LicenseClass.PUBLIC_DOMAIN,
        ),
        # `None` PORQUE A FONTE NÃO DECLARA (§44). Nunca o kickoff.
        observed_at=None,
    )


def fatos(
    n: int = 0,
    *,
    families: tuple[CoverageFamily, ...] = (CoverageFamily.MATCH,),
    home: int = 2,
    away: int = 1,
    build_run_id: str = BUILD_RUN,
) -> MatchCorpusFacts:
    """Os fatos de uma partida, do jeito que o corpus os publica."""
    return MatchCorpusFacts(
        match=partida(n),
        competition=COMPETICAO_CODE,
        season_label=TEMPORADA_LABEL,
        included_families=families,
        build_run_id=build_run_id,
        quality_assessment_id=ASSESSMENT,
        result=MatchResult(regular_time=Score(home=home, away=away)),
        odds=(observacao(n),) if CoverageFamily.ODDS in families else (),
    )


def muitos_fatos(
    quantos: int,
    *,
    families: tuple[CoverageFamily, ...] = (CoverageFamily.MATCH,),
    build_run_id: str = BUILD_RUN,
) -> tuple[MatchCorpusFacts, ...]:
    return tuple(fatos(n, families=families, build_run_id=build_run_id) for n in range(quantos))


def compostos(
    quantos: int,
    *,
    families: tuple[CoverageFamily, ...] = (CoverageFamily.MATCH,),
    build_run_id: str = BUILD_RUN,
) -> tuple[ComposedMatchCorpusFacts, ...]:
    """Os mesmos fatos, já compostos — a forma que o corpus de fato absorve."""
    return tuple(
        ComposedMatchCorpusFacts.of(f)
        for f in muitos_fatos(quantos, families=families, build_run_id=build_run_id)
    )


def membros(
    quantos: int,
    *,
    families: tuple[CoverageFamily, ...] = (CoverageFamily.MATCH,),
) -> tuple[CorpusMember, ...]:
    """As linhas de pertinência, em ordem de `match_id`.

    ORDENADAS AQUI porque a impressão do corpus exige ordem estritamente
    crescente, e `match_id(n)` é derivado por `uuid5` — a ordem numérica de
    `n` não é a ordem dos UUIDs.
    """
    return tuple(
        sorted(
            (f.as_member() for f in compostos(quantos, families=families)),
            key=lambda m: str(m.match_id),
        )
    )


# ============================================ eventos no corpus (PR-04.4.2) ==
#
# TUDO DERIVADO, como o resto deste módulo. O id canônico do evento é derivado
# de `(partida, chave da fonte, revisão)` — o mesmo cálculo do PR-04.4.1 —,
# porque um `uuid4` aqui faria todo teste de determinismo de impressão passar
# ou falhar por acidente.

#: O executante dos eventos dos cenários. Derivado, como tudo aqui.
JOGADOR_DO_EVENTO: Final[PlayerId] = PlayerId.derive("pr0442", "executante")

#: As execuções de canonicalização de evento dos cenários.
EVENT_RUN: Final[str] = "77777777-7777-4777-8777-777777777777"
OUTRA_EVENT_RUN: Final[str] = "88888888-8888-4888-8888-888888888888"


def evento_canonico(
    n: int = 0,
    *,
    match: int = 0,
    tipo: EventType = EventType.SHOT,
    minuto: int = 23,
    stoppage: int = 0,
    sequencia: int = 0,
    periodo: Period = Period.FIRST_HALF,
    ponto: tuple[float, float] | None = (0.88, 0.51),
    jogador: bool = True,
    time: bool = True,
    xg: str | None = "0.34",
    xg_indisponivel: bool = False,
    revision: int = 1,
    supersedes: uuid.UUID | None = None,
    status: EventStatus = EventStatus.ACTIVE,
    license_class: LicenseClass = LicenseClass.PUBLIC_DOMAIN,
    source_key: str | None = None,
) -> CanonicalMatchEvent:
    """Um evento canônico, com identidade DERIVADA.

    `xg` TEM TRÊS ESTADOS aqui de propósito, porque são os três que o corpus
    precisa preservar: número (inclusive `"0"`), indisponível-com-motivo e
    detalhe que não fala de xG.
    """
    partida_id = partida(match).id
    chave = source_key or f"ev-{match}-{n}"
    detalhe: EventDetail | None = None
    if tipo is EventType.SHOT:
        detalhe = ShotDetail(
            outcome=ShotOutcome.SAVED,
            body_part=BodyPart.RIGHT_FOOT,
            xg=(
                FeatureValue.absent(Unavailability.NOT_PUBLISHED)
                if xg_indisponivel
                else (None if xg is None else FeatureValue.of(float(Decimal(xg))))
            ),
        )
    elif tipo is EventType.CARD:
        detalhe = CardDetail(card_type=CardType.YELLOW, reason="falta tática")
    return CanonicalMatchEvent(
        id=canonical_event_id(source_key=chave, revision=revision, match_id=partida_id),
        match_id=partida_id,
        type=tipo,
        clock=MatchClock(period=periodo, minute=minuto, stoppage=stoppage),
        sequence=sequencia,
        provenance=DataProvenance(
            source_type=SourceType.OPEN_DATA,
            provider_id=ProviderId("fonte_de_eventos"),
            source_record_id=f"linha-{n}",
            times=ObservationTimes.at_once(AGORA),
            license_class=license_class,
        ),
        quality=DataQuality(
            completeness=1.0, consistency=1.0, freshness=1.0, identity_confidence=1.0
        ),
        team_id=CASA if time else None,
        player_id=JOGADOR_DO_EVENTO if jogador else None,
        start_location=(
            None if ponto is None else PitchCoordinate(x=ponto[0], y=ponto[1])
        ),
        detail=detalhe,
        revision=revision,
        supersedes=supersedes,
        status=status,
    )


def publicado(
    evento: CanonicalMatchEvent, *, runs: tuple[str, ...] = (EVENT_RUN,)
) -> PublishedEvent:
    return PublishedEvent(event=evento, build_run_ids=runs)


def eventos_de(
    match: int = 0, *, quantos: int = 3, runs: tuple[str, ...] = (EVENT_RUN,)
) -> tuple[PublishedEvent, ...]:
    """Um punhado de eventos de uma partida — tipos variados de propósito.

    A VARIEDADE É O PONTO: um chute com coordenada, um cartão sem coordenada e
    um fim de período estrutural exercitam o denominador espacial do §27, que
    uma lista de chutes idênticos deixaria passar.
    """
    catalogo = [
        (EventType.SHOT, (0.88, 0.51)),
        (EventType.CARD, None),
        (EventType.PERIOD_END, None),
        (EventType.PASS, (0.44, 0.20)),
        (EventType.GOAL, (0.91, 0.49)),
    ]
    escolhidos = [catalogo[i % len(catalogo)] for i in range(quantos)]
    return tuple(
        publicado(
            evento_canonico(
                n=i,
                match=match,
                tipo=tipo,
                ponto=ponto,
                minuto=10 + i,
                sequencia=i,
                jogador=tipo is not EventType.PERIOD_END,
                time=tipo is not EventType.PERIOD_END,
            ),
            runs=runs,
        )
        for i, (tipo, ponto) in enumerate(escolhidos)
    )


def fatos_com_eventos(
    n: int = 0,
    *,
    quantos: int = 3,
    families: tuple[CoverageFamily, ...] = (CoverageFamily.MATCH,),
    runs: tuple[str, ...] = (EVENT_RUN,),
) -> ComposedMatchCorpusFacts:
    """Uma partida composta que JÁ publica eventos."""
    return ComposedMatchCorpusFacts.of(fatos(n, families=families)).with_events(
        eventos_de(n, quantos=quantos, runs=runs)
    )
