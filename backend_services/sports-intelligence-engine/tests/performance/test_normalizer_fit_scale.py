"""O BENCHMARK DO AJUSTE — 100.000 valores, mediana e IQR EXATOS.

O QUE ELE MEDE (§181, §182, §184):

    duração        quanto custa ordenar e indexar cem mil decimais
    valores/s      o throughput do ajuste
    pico           a memória, que é `O(N)` por decisão declarada

POR QUE `O(N)` NÃO É DEFEITO (§183, §184). A V1 exige mediana e quartis
EXATOS. Exatidão sobre uma população arbitrária exige a população ordenada —
não há como saber o valor do percentil 25 sem ter visto todos os candidatos.
Um esboço probabilístico (t-digest, GK) resolveria a memória e trocaria a
identidade da escala por uma aproximação com erro dependente da ordem de
chegada. O ajuste é OFFLINE; a memória é o recurso barato aqui.

ELE NÃO PRECISA DE BANCO (§193). O ajustador é puro: recebe a população e
devolve o artefato. Subir PostgreSQL para medi-lo mediria o PostgreSQL.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

import pytest

from sports_intelligence.domain.features.extraction.catalog import (
    production_feature_catalog,
)
from sports_intelligence.domain.features.fitting.artifact import FitStatus
from sports_intelligence.domain.features.fitting.fitter import RobustNormalizerFitter
from sports_intelligence.domain.features.fitting.population import (
    FeatureObservation,
    FeaturePopulation,
)
from sports_intelligence.domain.features.fitting.transformer import (
    RobustNormalizerTransformer,
)
from sports_intelligence.domain.features.normalization import DEFAULT_V1_NORMALIZER
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import Period
from tests.performance.test_resolution_100k import _relatar
from tests.support.instrumentation import medindo
from tests.support.v2_fixtures import COMPETICAO

pytestmark = pytest.mark.performance

#: O volume do §181.
VALORES: Final[int] = 100_000

#: Um a cada vinte é INDISPONÍVEL. Eles entram na população — a contagem total
#: é auditável — e não entram na distribuição (§119, §120).
UM_A_CADA: Final[int] = 20

FEATURE: Final[str] = "shots_home_5m"


def _populacao() -> FeaturePopulation:
    """Cem mil observações derivadas — nada sorteado.

    OS VALORES SÃO UMA RAMPA EMBARALHADA por passo primo. A rampa torna os
    quantis conferíveis à mão; o embaralhamento garante que a ordenação seja
    realmente exercitada, e não pulada por a entrada já vir ordenada.
    """
    observacoes = []
    for n in range(VALORES):
        indisponivel = n % UM_A_CADA == 0
        valor = None if indisponivel else Decimal((n * 7919) % VALORES)
        identificador = MatchId.derive("perf-normalizador", str(n))
        observacoes.append(
            FeatureObservation(
                match_id=identificador,
                as_of=FeatureAsOf.at(identificador, Period.SECOND_HALF, 60),
                value=valor,
                corpus_fingerprint="a" * 64,
            )
        )
    return FeaturePopulation.of(COMPETICAO, FEATURE, observacoes)


class TestOAjusteEmVolume:
    def test_cem_mil_valores(self) -> None:
        """§181, §182, §220."""
        with medindo("construção da população") as construcao:
            populacao = _populacao()

        definicao = production_feature_catalog().spec_of(FEATURE).definition
        fitter = RobustNormalizerFitter(definition=DEFAULT_V1_NORMALIZER)

        with medindo("ajuste exato") as ajuste:
            artefato = fitter.fit(
                populacao,
                feature=definicao,
                source_corpus_fingerprint="a" * 64,
                source_space_fingerprint="b" * 64,
            )

        with medindo("impressão do artefato") as impressao:
            digest = artefato.fingerprint

        transformador = RobustNormalizerTransformer(artifact=artefato)
        with medindo("transformação de mil valores") as transformacao:
            for n in range(1_000):
                transformador.transform(
                    feature_key=FEATURE,
                    feature_fingerprint=artefato.feature_fingerprint,
                    competition_id=COMPETICAO,
                    raw=Decimal(n),
                )

        _relatar(
            f"PR-05.4 · ajuste exato sobre {populacao.size:_} valores",
            [
                f"population size    {populacao.size:_}",
                f"available values   {populacao.available_size:_}",
                "",
                f"duration           {ajuste.segundos:.2f}s",
                f"values/sec         {ajuste.por_segundo(populacao.available_size):.0f}",
                f"peak memory        {ajuste.pico_mb:.0f} MB",
                "",
                f"população          {construcao.segundos:.2f}s · {construcao.pico_mb:.0f} MB",
                f"digest             {impressao.segundos:.3f}s",
                f"transform (1k)     {transformacao.segundos:.3f}s · "
                f"{transformacao.por_segundo(1000):.0f} valores/s",
                "",
                f"status             {artefato.status.value}",
                f"mediana            {artefato.median}",
                f"IQR                {artefato.iqr}",
                f"artefato           {digest[:16]}",
            ],
        )

        # ---- os critérios -------------------------------------------------

        # §119, §120 — os indisponíveis contam no total e não na distribuição.
        assert populacao.size == VALORES
        assert populacao.available_size == VALORES - VALORES // UM_A_CADA

        # §183 — o ajuste é EXATO. A população é a rampa `0..99_999` sem os
        # múltiplos de vinte na ORDEM EMBARALHADA; a mediana de uma rampa
        # quase completa fica no meio do intervalo.
        assert artefato.status is FitStatus.FITTED
        assert artefato.median is not None
        assert Decimal(45_000) < artefato.median < Decimal(55_000)
        assert artefato.iqr is not None
        assert artefato.iqr > 0

        # §184 — o custo é `O(N log N)` na FORMA. Uma implementação quadrática
        # sobre cem mil valores não terminaria em minuto nenhum.
        assert ajuste.segundos < 60, (
            f"o ajuste levou {ajuste.segundos:.1f}s para {populacao.size:_} valores"
        )

        # A impressão do artefato NÃO depende do tamanho da população: ela é o
        # hash de um documento com contagens e parâmetros, e não da população.
        assert impressao.segundos < 1

    def test_o_ajuste_e_reproduzivel_em_volume(self) -> None:
        """§217 — duas execuções sobre a mesma população, mesmo artefato."""
        populacao = _populacao()
        definicao = production_feature_catalog().spec_of(FEATURE).definition
        fitter = RobustNormalizerFitter(definition=DEFAULT_V1_NORMALIZER)
        impressoes = {
            fitter.fit(
                populacao,
                feature=definicao,
                source_corpus_fingerprint="a" * 64,
                source_space_fingerprint="b" * 64,
            ).fingerprint
            for _ in range(3)
        }
        assert len(impressoes) == 1
