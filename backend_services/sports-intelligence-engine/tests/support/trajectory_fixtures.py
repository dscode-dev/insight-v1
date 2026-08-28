"""Cenários de trajetória — pequenos, com movimento deliberado, à mão.

O PERFIL PADRÃO TEM CINCO EIXOS e três horizontes, logo `n = 15` células. O
número é escolhido:

    piso relativo   `5s >= 3·15 = 45`  ->  `s >= 9`
    piso de células `s >= 8`
    piso de horizontes  `>= 2` evidenciais, e um horizonte é evidencial com
                    `>= 4` eixos e `>= 3/5` deles — com `m = 5`, isso é `4`

    3 horizontes cheios  s = 15   completo
    2 horizontes cheios  s = 10   acima do piso, 2 horizontes
    2 horizontes com 4   s =  8   NO piso de células, e no piso de horizontes
    1 horizonte cheio    s =  5   ABAIXO — um horizonte não descreve movimento

A ÂNCORA PADRÃO É `SECOND_HALF 51`, e o minuto tem motivo: com o segundo tempo
começando no 46, os três horizontes cabem (`50`, `48`, `46`). Para exercitar a
fronteira do intervalo há `SECOND_HALF 49` — onde `t-5` cairia no 44, primeiro
tempo — e `SECOND_HALF 47`, onde só `t-1` existe.

AS CURVAS SÃO DECLARADAS POR VALOR, e não geradas. Um cenário de trajetória
precisa de subida, descida e estabilidade explícitas: um gerador aleatório
produziria movimento e não deixaria óbvio, na leitura do teste, qual movimento
é.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, TypedDict

from sports_intelligence.domain.features.dataset.grid import (
    DEFAULT_SNAPSHOT_GRID,
    SnapshotGridPolicy,
)
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.retrieval.trajectory import (
    HistoricalTrajectory,
    TrajectoryRepresentation,
    TrajectoryRow,
    assemble_trajectory,
    build_representation,
)
from sports_intelligence.domain.retrieval.trajectory_coverage import (
    DEFAULT_TRAJECTORY_COVERAGE,
    TrajectoryCoveragePolicy,
)
from sports_intelligence.domain.retrieval.trajectory_distance import (
    TrajectoryDistanceDefinition,
)
from sports_intelligence.domain.retrieval.trajectory_exact import (
    ExactTrajectoryRetriever,
    TrajectoryCandidate,
)
from sports_intelligence.domain.retrieval.trajectory_profile import (
    DEFAULT_TRAJECTORY_PROFILE,
    ResolvedTrajectoryProfile,
    TrajectoryRetrievalProfile,
)
from sports_intelligence.domain.retrieval.trajectory_window import (
    DEFAULT_TRAJECTORY_WINDOW,
    TrajectoryWindowPolicy,
)
from sports_intelligence.domain.shared.temporal import Period
from tests.support.availability_fixtures import CINCO_EIXOS, perfil_ciente
from tests.support.retrieval_fixtures import DISPONIVEL, LIGA_A, SEM_ESCALA, representacao


class Cenario(TypedDict):
    """Os dois lados de uma curva — o agora e o passado por horizonte.

    ELE É UM `TypedDict` E NÃO UM `dict[str, object]` porque os cenários são
    esparramados com `**`, e um `object` ali apaga a checagem de tipos de todo
    chamador — foram duzentos e vinte e seis erros de `mypy` de uma vez.
    """

    agora: Mapping[str, float | None]
    passado: Mapping[int, Mapping[str, float | None]]


GRADE: Final[SnapshotGridPolicy] = DEFAULT_SNAPSHOT_GRID

#: A âncora padrão: os três horizontes cabem no segundo tempo.
ANCORA: Final[GridTimePoint] = GridTimePoint.of(Period.SECOND_HALF, 51)
#: A âncora onde `t-5` cairia no primeiro tempo.
ANCORA_49: Final[GridTimePoint] = GridTimePoint.of(Period.SECOND_HALF, 49)
#: A âncora onde só `t-1` existe.
ANCORA_47: Final[GridTimePoint] = GridTimePoint.of(Period.SECOND_HALF, 47)

MINUTO_POR_HORIZONTE: Final[Mapping[int, int]] = {1: 50, 3: 48, 5: 46}


def perfil_de_trajetoria(
    *,
    competition: str = LIGA_A,
    eixos: Sequence[str] = CINCO_EIXOS,
    profile: TrajectoryRetrievalProfile = DEFAULT_TRAJECTORY_PROFILE,
) -> ResolvedTrajectoryProfile:
    """O perfil de trajetória resolvido — cinco eixos, três horizontes."""
    return profile.resolve(perfil_ciente(competition=competition, eixos=eixos))


def distancia_de_trajetoria(
    profile: ResolvedTrajectoryProfile | None = None,
    *,
    coverage_policy: TrajectoryCoveragePolicy = DEFAULT_TRAJECTORY_COVERAGE,
) -> TrajectoryDistanceDefinition:
    return TrajectoryDistanceDefinition(
        profile=profile or perfil_de_trajetoria(), coverage_policy=coverage_policy
    )


def _mascara(valores: Mapping[str, float | None]) -> dict[str, str]:
    return {
        chave: DISPONIVEL if valor is not None else SEM_ESCALA for chave, valor in valores.items()
    }


def linha(
    *,
    match: str,
    position: GridTimePoint,
    valores: Mapping[str, float | None],
) -> TrajectoryRow:
    """Uma linha de lookback, com o digesto derivado da posição."""
    return TrajectoryRow(
        key=HistoricalFeatureSnapshotKey(match_key=match, grid_index=position.minute),
        position=position,
        row_digest=f"{match}:{position.minute:04d}",
        values=dict(valores),
        availabilities=_mascara(valores),
    )


def trajetoria(
    *,
    match: str = "eva-001",
    anchor: GridTimePoint = ANCORA,
    competition: str = LIGA_A,
    window: TrajectoryWindowPolicy = DEFAULT_TRAJECTORY_WINDOW,
    passado: Mapping[int, Mapping[str, float | None]] | None = None,
) -> tuple[HistoricalTrajectory, dict[GridTimePoint, TrajectoryRow]]:
    """A trajetória e as linhas que a preencheram.

    `passado` É POR HORIZONTE, e não por minuto: o teste declara «o que havia
    três minutos atrás», e a tradução para o minuto da grade é feita aqui.
    Omitir um horizonte que EXISTE estruturalmente faria a montagem falhar com
    `TRAJECTORY_SOURCE_ROW_MISSING` — que é o comportamento certo, e tem teste.
    """
    resolvidos = window.resolve(anchor, grid=GRADE)
    linhas: dict[GridTimePoint, TrajectoryRow] = {}
    for resolvido in resolvidos:
        if resolvido.target is None:
            continue
        valores = (passado or {}).get(resolvido.horizon_minutes)
        if valores is None:
            continue
        linhas[resolvido.target] = linha(match=match, position=resolvido.target, valores=valores)
    chave = HistoricalFeatureSnapshotKey(match_key=match, grid_index=anchor.minute)
    montada = assemble_trajectory(
        policy=window,
        resolved=resolvidos,
        anchor_key=chave,
        match_key=match,
        competition=competition,
        anchor_position=anchor,
        anchor_row_digest=f"{match}:{anchor.minute:04d}",
        rows=linhas,
    )
    return montada, linhas


def representacao_de_trajetoria(
    *,
    match: str = "eva-001",
    anchor: GridTimePoint = ANCORA,
    competition: str = LIGA_A,
    agora: Mapping[str, float | None] | None = None,
    passado: Mapping[int, Mapping[str, float | None]] | None = None,
    profile: ResolvedTrajectoryProfile | None = None,
    window: TrajectoryWindowPolicy = DEFAULT_TRAJECTORY_WINDOW,
) -> TrajectoryRepresentation:
    """A representação completa — âncora, slots e deslocamentos."""
    resolvido = profile or perfil_de_trajetoria(competition=competition)
    valores_agora = dict(agora if agora is not None else dict.fromkeys(CINCO_EIXOS, 0.0))
    montada, linhas = trajetoria(
        match=match,
        anchor=anchor,
        competition=competition,
        window=window,
        passado=passado
        if passado is not None
        else {h: dict.fromkeys(CINCO_EIXOS, 0.0) for h in (1, 3, 5)},
    )
    return build_representation(
        trajectory=montada,
        feature_keys=resolvido.feature_keys,
        horizons=resolvido.horizons,
        profile_fingerprint=resolvido.fingerprint,
        anchor_values=valores_agora,
        anchor_availabilities=_mascara(valores_agora),
        rows=linhas,
    )


def candidato_de_trajetoria(
    *,
    match: str,
    anchor: GridTimePoint = ANCORA,
    competition: str = LIGA_A,
    agora: Mapping[str, float | None] | None = None,
    passado: Mapping[int, Mapping[str, float | None]] | None = None,
    profile: ResolvedTrajectoryProfile | None = None,
    representation_fingerprint: str = "",
    season: str = "2023-24",
) -> TrajectoryCandidate:
    return TrajectoryCandidate(
        match_id=match,
        season=season,
        representation_fingerprint=representation_fingerprint or representacao().fingerprint,
        representation=representacao_de_trajetoria(
            match=match,
            anchor=anchor,
            competition=competition,
            agora=agora,
            passado=passado,
            profile=profile,
        ),
    )


def recuperador_de_trajetoria(
    *,
    profile: ResolvedTrajectoryProfile | None = None,
    coverage_policy: TrajectoryCoveragePolicy = DEFAULT_TRAJECTORY_COVERAGE,
) -> ExactTrajectoryRetriever:
    from sports_intelligence.domain.retrieval.candidate_policy import (
        DEFAULT_CANDIDATE_POLICY,
    )

    resolvido = profile or perfil_de_trajetoria()
    return ExactTrajectoryRetriever(
        policy=DEFAULT_CANDIDATE_POLICY,
        profile=resolvido,
        distance=distancia_de_trajetoria(resolvido, coverage_policy=coverage_policy),
    )


def curva(*, de: float, para: float, eixos: Sequence[str] = CINCO_EIXOS) -> Cenario:
    """Uma curva de `de` até `para`, nos quatro instantes da janela.

    ELA DEVOLVE `agora` E `passado` JUNTOS porque os dois são a mesma curva, e
    declará-los separadamente no teste é como um deles fica desatualizado.

    **OS VALORES SÃO DIÁDICOS DE PROPÓSITO**, e a fração não é `h/5`. Com
    passos de `1/5`, `8 + 2·0,8` e `0 + 2·0,8` arredondam para lugares
    diferentes, e a diferença sobrevive à subtração: a invariância de nível
    saía `2,1e-31` em vez de zero — um artefato do CENÁRIO, e não do motor.

        deslocamentos    2,0 · 1,5 · 0,5      exatos em binary64
        níveis           `para - d`, `para - 0,75d`, `para - 0,25d`

    Com eles a igualdade é EXATA, e o golden do §150 afirma a propriedade em
    vez de uma coincidência de arredondamento. Para valores quaisquer a
    propriedade vale a menos do arredondamento, e o teste de propriedade a
    verifica assim — com tolerância, e dizendo por quê.
    """
    total = para - de
    fracoes = {5: 1.0, 3: 0.75, 1: 0.25}
    return {
        "agora": dict.fromkeys(eixos, para),
        "passado": {
            h: dict.fromkeys(eixos, para - total * fracao) for h, fracao in fracoes.items()
        },
    }


def com_horizontes(
    *,
    agora: Mapping[str, float | None],
    horizontes: Mapping[int, Mapping[str, float | None]],
) -> Cenario:
    """Os dois lados declarados à mão — para os cenários de cobertura."""
    return Cenario(agora=dict(agora), passado={h: dict(v) for h, v in horizontes.items()})
