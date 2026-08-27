"""Cenários sintéticos de recuperação — pequenos, calculáveis à mão.

ELES NÃO PASSAM PELO PARQUET NEM PELO BANCO de propósito. As invariantes deste
PR são do DOMÍNIO — «a ordem de leitura não muda o top-K», «um candidato
incompleto não recebe distância» —, e prová-las através de uma construção
completa faria cada execução custar minutos e cada falha exigir arqueologia
para separar defeito de leitura de defeito de ranking.

O PERFIL É MONTADO À MÃO, com dois eixos. Dois bastam para calcular a distância
de cabeça — `q=[0,0]`, `c=[3,4]`, `d²=25` — e é isso que torna um golden um
golden: se o teste falhar, o número esperado não precisa ser recalculado por
ninguém.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.normalized.rows import (
    NormalizationAvailability,
)
from sports_intelligence.domain.features.normalized.versions import (
    NormalizedFeatureRepresentationSpec,
)
from sports_intelligence.domain.retrieval.candidate import CandidateRow
from sports_intelligence.domain.retrieval.distance import DistanceDefinition
from sports_intelligence.domain.retrieval.profile import (
    DEFAULT_RETRIEVAL_PROFILE,
    ResolvedRetrievalProfile,
    RetrievalFeatureProfile,
)
from sports_intelligence.domain.retrieval.query import (
    HistoricalRetrievalQuery,
    QuerySnapshot,
)
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.shared.identity import CompetitionId
from sports_intelligence.domain.shared.temporal import Period

#: Os dois eixos do perfil sintético. Eles têm nomes de features de verdade
#: para que nada no cenário dependa de um nome inventado.
EIXO_A: Final[str] = "xg_home_5m"
EIXO_B: Final[str] = "xg_away_5m"

LIGA_A: Final[str] = "PREMIER"
LIGA_B: Final[str] = "LALIGA"

IMPRESSAO: Final[str] = "a" * 64
OUTRA_IMPRESSAO: Final[str] = "b" * 64

#: O instante padrão dos cenários: primeiro tempo, minuto 30.
MINUTO_30: Final[GridTimePoint] = GridTimePoint.of(Period.FIRST_HALF, 30)

DISPONIVEL: Final[str] = NormalizationAvailability.AVAILABLE.value
SEM_ESCALA: Final[str] = NormalizationAvailability.ARTIFACT_DEGENERATE_SCALE.value


def perfil(
    *,
    competition: str = LIGA_A,
    eixos: Sequence[str] = (EIXO_A, EIXO_B),
    bundle_fingerprint: str = IMPRESSAO,
    base: RetrievalFeatureProfile = DEFAULT_RETRIEVAL_PROFILE,
) -> ResolvedRetrievalProfile:
    """Um perfil resolvido com os eixos dados, na ordem dada.

    `base` EXISTE DESDE O PR-06.2. Os dois perfis da V1 resolvem os MESMOS
    eixos e diferem só na política de ausência — e é exatamente essa igualdade
    que a fixture precisa poder construir para que o teste de §10 compare duas
    resoluções, e não duas fixtures escritas separadamente.
    """
    return ResolvedRetrievalProfile(
        base=base,
        competition=competition,
        competition_id=CompetitionId.derive(competition.lower()),
        competition_bundle_fingerprint=bundle_fingerprint,
        plan_fingerprint=IMPRESSAO,
        feature_keys=tuple(eixos),
        feature_fingerprints=tuple(f"{e}-fp".ljust(64, "0") for e in eixos),
    )


def distancia(profile: ResolvedRetrievalProfile | None = None) -> DistanceDefinition:
    return DistanceDefinition(profile=profile or perfil())


def representacao(
    *, artifact_set_fingerprint: str = IMPRESSAO
) -> NormalizedFeatureRepresentationSpec:
    return NormalizedFeatureRepresentationSpec(
        space_name="MATCH_STATE_RAW_V2",
        space_version="2.0",
        space_fingerprint=IMPRESSAO,
        plan_name="MATCH_STATE_NORMALIZATION_PLAN_V1",
        plan_version="1.0",
        plan_fingerprint=IMPRESSAO,
        artifact_set_id="00000000-0000-0000-0000-000000000001",
        artifact_set_fingerprint=artifact_set_fingerprint,
    )


def _mascara(valores: Mapping[str, float | None]) -> dict[str, str]:
    """`AVAILABLE` onde há número; sem escala onde não há.

    O MOTIVO DA AUSÊNCIA É `ARTIFACT_DEGENERATE_SCALE`, e não
    `SOURCE_VALUE_UNAVAILABLE`: os eixos do perfil são `ROBUST` e `FITTED`, e o
    caso que interessa medir é o do PR-05.5.2 — havia valor cru e não havia
    dispersão naquela competição.
    """
    return {
        chave: DISPONIVEL if valor is not None else SEM_ESCALA for chave, valor in valores.items()
    }


def consulta(
    *,
    match: str = "eva-001",
    grid_index: int = 30,
    competition: str = LIGA_A,
    position: GridTimePoint = MINUTO_30,
    valores: Mapping[str, float | None] | None = None,
    representation_fingerprint: str = "",
) -> QuerySnapshot:
    numeros: dict[str, float | None] = dict(valores or {EIXO_A: 0.0, EIXO_B: 0.0})
    return QuerySnapshot(
        key=HistoricalFeatureSnapshotKey(match_key=match, grid_index=grid_index),
        split=DatasetSplit.EVALUATION,
        competition=competition,
        season="2024-25",
        position=position,
        row_digest=f"{match}:{grid_index:04d}",
        representation_fingerprint=representation_fingerprint or representacao().fingerprint,
        plan_fingerprint=IMPRESSAO,
        artifact_set_fingerprint=IMPRESSAO,
        values=numeros,
        availabilities=_mascara(numeros),
    )


def candidato(
    *,
    match: str,
    grid_index: int = 30,
    competition: str = LIGA_A,
    position: GridTimePoint = MINUTO_30,
    valores: Mapping[str, float | None] | None = None,
    representation_fingerprint: str = "",
) -> CandidateRow:
    numeros: dict[str, float | None] = dict(valores or {EIXO_A: 1.0, EIXO_B: 1.0})
    return CandidateRow(
        key=HistoricalFeatureSnapshotKey(match_key=match, grid_index=grid_index),
        split=DatasetSplit.REFERENCE,
        match_id=match,
        competition=competition,
        season="2023-24",
        position=position,
        row_digest=f"{match}:{grid_index:04d}",
        representation_fingerprint=representation_fingerprint or representacao().fingerprint,
        values=numeros,
        availabilities=_mascara(numeros),
    )


def pedido(
    *,
    key: HistoricalFeatureSnapshotKey | None = None,
    k: int = 3,
    representation: NormalizedFeatureRepresentationSpec | None = None,
) -> HistoricalRetrievalQuery:
    return HistoricalRetrievalQuery(
        dataset_version_id="00000000-0000-0000-0000-0000000000aa",
        dataset_name="match-state-normalized",
        dataset_version="v1.0",
        representation=representation or representacao(),
        key=key or HistoricalFeatureSnapshotKey(match_key="eva-001", grid_index=30),
        k=k,
    )
