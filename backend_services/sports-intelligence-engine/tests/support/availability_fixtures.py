"""Cenários de cobertura — pequenos, com ausência deliberada, calculáveis à mão.

DOIS PERFIS, PORQUE OS DOIS PISOS MORDEM EM TAMANHOS DIFERENTES.

    CINCO_EIXOS   `m = 5`. O MÍNIMO ABSOLUTO decide: `s ≥ 4`. A razão `3/5`
                  admitiria `s = 3`, e o mínimo de quatro eixos o recusa
    DEZ_EIXOS     `m = 10`. A RAZÃO decide: `s ≥ 6`. O mínimo de quatro já foi
                  ultrapassado, e `s = 5` é recusado só pela razão

    m = 5    s=5 completo · s=4 no piso (pelo mínimo) · s=3 recusado
    m = 10   s=10 completo · s=6 no piso (pela razão) · s=5 recusado

TER OS DOIS É O QUE PROVA QUE OS DOIS PISOS SÃO NECESSÁRIOS. Com um perfil só,
metade da política ficaria sem teste que a distinga da outra metade.

UM PERFIL DE DOIS EIXOS NÃO SERVIRIA para nada disto: ele é menor que o mínimo
absoluto da política, e toda competição com ele é recusada antes da primeira
query. Por isso as fixtures do PR-06.1 continuam com dois e estas têm cinco —
as duas medem coisas diferentes.

A AUSÊNCIA É EXPRESSA OMITINDO A CHAVE, e não passando `None` explícito. As
duas formas produzem o mesmo resultado; omitir é o que a linha de um Parquet
sem aquele eixo faz, e escrever `None` num dicionário de valores com a máscara
dizendo `AVAILABLE` é a contradição que `availability_mask` recusa — e há teste
separado para ela.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.availability_distance import (
    AvailabilityAwareDistanceDefinition,
)
from sports_intelligence.domain.retrieval.availability_exact import (
    AvailabilityAwareHistoricalRetriever,
)
from sports_intelligence.domain.retrieval.candidate import CandidateRow
from sports_intelligence.domain.retrieval.candidate_policy import (
    DEFAULT_CANDIDATE_POLICY,
)
from sports_intelligence.domain.retrieval.coverage import (
    DEFAULT_COVERAGE_POLICY,
    AvailabilityCoveragePolicy,
)
from sports_intelligence.domain.retrieval.profile import (
    AVAILABILITY_AWARE_RETRIEVAL_PROFILE,
    ResolvedRetrievalProfile,
)
from sports_intelligence.domain.retrieval.query import (
    HistoricalRetrievalQuery,
    QuerySnapshot,
)
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from tests.support.retrieval_fixtures import (
    LIGA_A,
    MINUTO_30,
    candidato,
    consulta,
    perfil,
    representacao,
)

#: Os cinco eixos do perfil sintético. Nomes de features de verdade, para que
#: nada no cenário dependa de um nome inventado.
CINCO_EIXOS: Final[tuple[str, ...]] = (
    "xg_home_1m",
    "xg_away_1m",
    "xg_diff_1m",
    "xg_home_3m",
    "xg_away_3m",
)

#: O perfil onde a RAZÃO decide: `3/5` de dez é seis.
DEZ_EIXOS: Final[tuple[str, ...]] = (
    *CINCO_EIXOS,
    "xg_diff_3m",
    "xg_home_5m",
    "xg_away_5m",
    "xg_diff_5m",
    "xg_home_10m",
)

#: `q = [0, 0, 0, 0, 0]` — a query completa dos goldens.
QUERY_ZERADA: Final[Mapping[str, float]] = dict.fromkeys(CINCO_EIXOS, 0.0)


def perfil_ciente(
    *,
    competition: str = LIGA_A,
    eixos: Sequence[str] = CINCO_EIXOS,
) -> ResolvedRetrievalProfile:
    """O perfil resolvido sob a política de ausência do PR-06.2."""
    return perfil(
        competition=competition,
        eixos=eixos,
        base=AVAILABILITY_AWARE_RETRIEVAL_PROFILE,
    )


def distancia_ciente(
    profile: ResolvedRetrievalProfile | None = None,
    *,
    coverage_policy: AvailabilityCoveragePolicy = DEFAULT_COVERAGE_POLICY,
) -> AvailabilityAwareDistanceDefinition:
    return AvailabilityAwareDistanceDefinition(
        profile=profile or perfil_ciente(),
        coverage_policy=coverage_policy,
    )


def consulta_ciente(
    *,
    match: str = "eva-001",
    grid_index: int = 30,
    competition: str = LIGA_A,
    position: GridTimePoint = MINUTO_30,
    valores: Mapping[str, float | None] | None = None,
) -> QuerySnapshot:
    """A query dos cenários. Por padrão ela tem os cinco eixos zerados."""
    return consulta(
        match=match,
        grid_index=grid_index,
        competition=competition,
        position=position,
        valores=dict(QUERY_ZERADA) if valores is None else dict(valores),
    )


def candidato_ciente(
    *,
    match: str,
    grid_index: int = 30,
    competition: str = LIGA_A,
    position: GridTimePoint = MINUTO_30,
    valores: Mapping[str, float | None] | None = None,
    representation_fingerprint: str = "",
) -> CandidateRow:
    """Um candidato. OMITIR uma chave de `valores` é o que torna o eixo ausente."""
    return candidato(
        match=match,
        grid_index=grid_index,
        competition=competition,
        position=position,
        valores=dict.fromkeys(CINCO_EIXOS, 0.0) if valores is None else dict(valores),
        representation_fingerprint=representation_fingerprint,
    )


def pedido_ciente(
    *,
    key: HistoricalFeatureSnapshotKey | None = None,
    k: int = 3,
) -> HistoricalRetrievalQuery:
    """O pedido, sob o perfil ciente de disponibilidade."""
    return HistoricalRetrievalQuery(
        dataset_version_id="00000000-0000-0000-0000-0000000000aa",
        dataset_name="match-state-normalized",
        dataset_version="v1.0",
        representation=representacao(),
        key=key or HistoricalFeatureSnapshotKey(match_key="eva-001", grid_index=30),
        k=k,
        profile=AVAILABILITY_AWARE_RETRIEVAL_PROFILE,
    )


def recuperador(
    *,
    profile: ResolvedRetrievalProfile | None = None,
    coverage_policy: AvailabilityCoveragePolicy = DEFAULT_COVERAGE_POLICY,
) -> AvailabilityAwareHistoricalRetriever:
    resolvido = profile or perfil_ciente()
    return AvailabilityAwareHistoricalRetriever(
        policy=DEFAULT_CANDIDATE_POLICY,
        profile=resolvido,
        distance=distancia_ciente(resolvido, coverage_policy=coverage_policy),
    )


def primeiros(
    n: int, valor: float = 0.0, *, eixos: Sequence[str] = CINCO_EIXOS
) -> dict[str, float | None]:
    """Os `n` primeiros eixos, com o mesmo valor. O resto fica AUSENTE.

    ELA É O ATALHO DOS CENÁRIOS DE FRONTEIRA: sobre `CINCO_EIXOS`,
    `primeiros(4)` está no piso e `primeiros(3)` está abaixo dele.
    """
    return dict.fromkeys(eixos[:n], valor)
