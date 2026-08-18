"""Os fixtures do PR-04.3 — fatos de corpus, escopo, versões.

REAPROVEITAM OS IDS DO PR-04.2 (`build_fixtures`) e é deliberado: o corpus é
composto pelo que aquele build produziu, e um cenário com ids próprios testaria
uma integração que não existe.

TUDO DERIVADO, NADA SORTEADO. A impressão do corpus precisa ser a mesma em duas
execuções para que o §89 e o §88 possam ser afirmados — um `uuid4` aqui faria
todo teste de determinismo passar por acidente ou falhar por acidente.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import Stage, StageType
from sports_intelligence.domain.corpus.composition import ComposedMatchCorpusFacts
from sports_intelligence.domain.corpus.facts import MatchCorpusFacts
from sports_intelligence.domain.corpus.membership import CorpusMember
from sports_intelligence.domain.corpus.scope import CorpusScope, ScopeEntry
from sports_intelligence.domain.corpus.versions import (
    HistoricalCanonicalDataset,
    HistoricalCanonicalDatasetVersion,
    VersionInputs,
)
from sports_intelligence.domain.datasets.content import ContentHash
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
from sports_intelligence.domain.shared.provenance import (
    DataProvenance,
    LicenseClass,
    SourceType,
)
from sports_intelligence.domain.shared.temporal import ObservationTimes
from sports_intelligence.domain.shared.versioning import DatasetVersion
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
