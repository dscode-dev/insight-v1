"""Cenários sintéticos para o dataset normalizado — pequenos e controláveis.

ELES NÃO PASSAM PELO PARQUET NEM PELO BANCO de propósito. As invariantes que
importam neste PR são do DOMÍNIO — «mexer na avaliação não muda o ajuste» —, e
prová-las através de uma construção completa faria cada execução custar minutos
e cada falha exigir arqueologia para separar defeito de escala de defeito de
causalidade.

O CENÁRIO É PARAMÉTRICO NA AVALIAÇÃO. É essa forma que torna a mutação da
avaliação uma operação de uma linha: o mesmo gerador, com a metade de avaliação
diferente, produz dois datasets cuja REFERÊNCIA é literalmente a mesma.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Final

from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    extended_feature_catalog,
)
from sports_intelligence.domain.features.normalized.normalizer import (
    causal_dataset_normalizer,
)
from sports_intelligence.domain.features.normalized.plan import (
    NormalizationPlan,
    plan_for,
)
from sports_intelligence.domain.features.normalized.transform import RawFeatureRowView
from sports_intelligence.domain.shared.identity import CompetitionId
from sports_intelligence.domain.shared.temporal import Instant, instant

#: A fronteira das duas metades. Ela é fixa nos cenários porque a invariante
#: sob mutação da avaliação só faz sentido com a fronteira PARADA.
FRONTEIRA: Final[Instant] = instant(datetime(2025, 6, 1, tzinfo=UTC))

DIVISAO: Final[str] = "d" * 64

#: Duas ligas, para que o isolamento entre competições seja testável.
LIGA_A: Final[str] = "PREMIER"
LIGA_B: Final[str] = "LALIGA"

COMPETICOES: Final[Mapping[str, CompetitionId]] = {
    LIGA_A: CompetitionId.derive("premier-league"),
    LIGA_B: CompetitionId.derive("la-liga"),
}


def plano() -> NormalizationPlan:
    """O plano de produção, cortado na fronteira dos cenários."""
    return plan_for(
        reference_end_exclusive_normalizer=causal_dataset_normalizer(
            reference_end_exclusive=FRONTEIRA
        ),
        catalog=extended_feature_catalog(),
    )


def linha(
    *,
    match: str,
    grid_index: int,
    split: DatasetSplit,
    competition: str = LIGA_A,
    season: str = "2024-25",
    valores: Mapping[str, float] | None = None,
    plan: NormalizationPlan | None = None,
) -> RawFeatureRowView:
    """Uma linha crua sintética — todos os eixos do plano, valores explícitos.

    O QUE NÃO ESTÁ EM `valores` SAI `SOURCE_UNAVAILABLE`, e não zero. É a mesma
    distinção do dataset cru: um eixo sem valor não é um eixo que mediu zero, e
    um cenário que os confundisse provaria a invariante errada.
    """
    plano_efetivo = plan or plano()
    dados = dict(valores or {})
    numeros: dict[str, float | None] = {}
    mascara: dict[str, str] = {}
    for transformacao in plano_efetivo.transforms:
        chave = transformacao.feature_key
        if chave in dados:
            numeros[chave] = dados[chave]
            mascara[chave] = FeatureAvailability.AVAILABLE.value
        else:
            numeros[chave] = None
            mascara[chave] = FeatureAvailability.SOURCE_UNAVAILABLE.value
    return RawFeatureRowView(
        key=HistoricalFeatureSnapshotKey(match_key=match, grid_index=grid_index),
        split=split,
        competition=competition,
        season=season,
        grid_index=grid_index,
        grid_label=f"MIN_{grid_index:02d}",
        period="FIRST_HALF" if grid_index else "PRE_MATCH",
        minute=grid_index,
        row_digest=f"{match}:{grid_index:04d}:{competition}",
        values=numeros,
        availabilities=mascara,
    )


def referencia(
    *,
    matches: int = 40,
    competition: str = LIGA_A,
    eixo: str = "xg_home_5m",
    deslocamento: float = 0.0,
    plan: NormalizationPlan | None = None,
) -> list[RawFeatureRowView]:
    """Uma metade de REFERÊNCIA determinística e ordenada.

    QUARENTA PARTIDAS porque o mínimo do ajustador são trinta observações
    disponíveis: um cenário com menos produziria só `INSUFFICIENT_SAMPLE`, e
    provaria a invariante sobre artefatos que nunca ajustaram nada.
    """
    plano_efetivo = plan or plano()
    return [
        linha(
            match=f"{competition.lower()}-ref-{i:03d}",
            grid_index=0,
            split=DatasetSplit.REFERENCE,
            competition=competition,
            valores={eixo: deslocamento + float(i % 17) + 0.5},
            plan=plano_efetivo,
        )
        for i in range(matches)
    ]


def avaliacao(
    *,
    matches: int,
    competition: str = LIGA_A,
    eixo: str = "xg_home_5m",
    semente: float = 100.0,
    plan: NormalizationPlan | None = None,
) -> list[RawFeatureRowView]:
    """Uma metade de AVALIAÇÃO — é ELA que muda entre os dois cenários.

    OS VALORES SÃO ABSURDOS DE PROPÓSITO (a partir de cem). Se algum deles
    entrasse no ajuste, a mediana saltaria de forma inconfundível: a invariante
    passaria a falhar por um número, e não por um dígito de hash.
    """
    plano_efetivo = plan or plano()
    return [
        linha(
            match=f"{competition.lower()}-eva-{i:03d}",
            grid_index=0,
            split=DatasetSplit.EVALUATION,
            competition=competition,
            valores={eixo: semente + float(i)},
            plan=plano_efetivo,
        )
        for i in range(matches)
    ]


def em_ordem(views: Sequence[RawFeatureRowView]) -> list[RawFeatureRowView]:
    """A ordem canônica de leitura — partição primeiro, chave depois.

    ELA NÃO É A ORDEM DA CHAVE, e a diferença é a que o benchmark do PR-05.5.2
    revelou: o leitor entrega partição a partição, e `split=EVALUATION` vem
    ANTES de `split=REFERENCE` porque as chaves de objeto são ordenadas como
    texto. Ordenar só pela chave aqui produziria um fluxo que o motor recusa —
    e um cenário de teste que não é o que a produção entrega.
    """
    return sorted(views, key=lambda v: (v.split.value, v.competition, v.season, v.key))
