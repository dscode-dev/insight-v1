"""O BENCHMARK DA V2: 105 features sobre um corpus de 10.000 partidas.

O QUE ELE MEDE (§177, §178, §179, §220):

    duração e throughput   snapshots/s e features/s com contexto e mercado
    consultas do CONTEXTO  ele acrescenta um número CONSTANTE por lote — duas
                           consultas — e nunca uma por partida
    consultas do MERCADO   ZERO: ele sai do `OddsState` que o estado já
                           reconstruiu
    pico de memória        a prova de que o lote não materializa o corpus

O NÚMERO QUE MAIS IMPORTA É O DE CONSULTAS. Uma leitura de contexto por partida
daria vinte mil consultas para dez mil partidas — e ela é fácil de escrever por
acidente, porque «buscar o jogo anterior deste time» é uma pergunta que se faz
naturalmente uma vez por jogo.

O CRITÉRIO É A FORMA DA CURVA, e nunca o segundo absoluto.
"""

from __future__ import annotations

import uuid as _uuid
from collections.abc import Sequence
from typing import Any, Final

import pytest

from apps.corpus_composition import build_corpus_container
from sports_intelligence.adapters.postgres.feature_context import (
    PostgresHistoricalContextSource,
)
from sports_intelligence.adapters.postgres.feature_state import (
    PostgresHistoricalMatchStateSource,
)
from sports_intelligence.application.use_cases.feature_snapshot import (
    BuildHistoricalFeatureSnapshots,
)
from sports_intelligence.application.use_cases.feature_snapshot_v2 import (
    SNAPSHOT_SAMPLE_LIMIT_V2,
    BuildExtendedFeatureSnapshots,
)
from sports_intelligence.domain.corpus.versions import (
    CORPUS_PUBLISHER,
    DatasetVersionStatus,
)
from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    match_state_raw_space_v2,
)
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.quality.coverage import CoverageFamily, CoverageState
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import Period
from tests.performance.test_event_corpus_scale import (  # noqa: F401 — fixture
    _compor,
    cenario,
)
from tests.performance.test_resolution_100k import _relatar
from tests.support.instrumentation import contando_consultas, medindo

pytestmark = pytest.mark.performance

PUBLICADOR = Actor.service(CORPUS_PUBLISHER)

LOTE: Final[int] = 500
CORTE_MINUTO: Final[int] = 60

#: Quantas consultas cada lote custa: cinco do estado, duas do contexto.
CONSULTAS_POR_LOTE: Final[int] = 7

#: A cobertura é lida UMA vez por versão, fora do custo por lote.
CONSULTAS_DE_COBERTURA: Final[int] = 1


def _um_corte(match_id: MatchId) -> Sequence[FeatureAsOf]:
    return (FeatureAsOf.at(match_id, Period.SECOND_HALF, CORTE_MINUTO),)


async def _publicar(cenario: dict[str, Any]) -> tuple[Any, Any]:  # noqa: F811
    saida, _medida, _consultas = await _compor(
        cenario,
        nome=f"perf-v2-{_uuid.uuid4().hex[:6]}",
        event_runs=(cenario["eventos_grandes"].id,),
    )
    pipeline = cenario["anterior"]["pipeline"]
    contêiner = build_corpus_container(
        database=cenario["banco"],
        clock=pipeline.clock,
        audit=pipeline.audit,
        store=cenario["store"],
    )
    versao = await contêiner.publish_version.execute(
        actor=PUBLICADOR, version_id=saida.version.id
    )
    assert versao.status is DatasetVersionStatus.READY
    return versao, saida.manifest


def _origem(versao: Any, manifesto: Any) -> CorpusSource:
    return CorpusSource.of(
        versao,
        published_families=frozenset(
            CoverageFamily(f.family)
            for f in manifesto.coverage
            if f.state != CoverageState.NOT_DECLARED.value
        ),
    )


async def _todas_as_partidas(
    fonte: PostgresHistoricalMatchStateSource, version_id: str
) -> list[MatchId]:
    todas: list[MatchId] = []
    ultimo: str | None = None
    while True:
        pagina = list(await fonte.match_ids(version_id, limit=2_000, after=ultimo))
        if not pagina:
            return todas
        todas.extend(pagina)
        ultimo = str(pagina[-1])


class TestAV2EmVolume:
    async def test_extrair_a_v2_do_corpus_inteiro(
        self,
        cenario: dict[str, Any],  # noqa: F811
    ) -> None:
        """§177 ao §180, §220. Uma travessia, todas as medições."""
        versao, manifesto = await _publicar(cenario)
        banco = cenario["banco"]
        estado = PostgresHistoricalMatchStateSource(banco)
        origem = _origem(versao, manifesto)
        partidas = await _todas_as_partidas(estado, versao.id)
        espaco = match_state_raw_space_v2()
        assert len(partidas) >= 1_000

        def caso_v2() -> BuildExtendedFeatureSnapshots:
            return BuildExtendedFeatureSnapshots(
                state_source=estado,
                context_source=PostgresHistoricalContextSource(banco),
                policy=TemporalAvailabilityPolicy.default(),
                batch_size=LOTE,
            )

        # ---- a V2 sobre o corpus inteiro -----------------------------------
        async with contando_consultas(banco) as consultas_v2:
            with medindo("snapshots V2") as v2:
                saida = await caso_v2().execute(
                    source_corpus=origem, match_ids=partidas, as_of_of=_um_corte
                )

        # ---- a V1, para isolar o que o contexto acrescenta (§178, §179) ----
        async with contando_consultas(banco) as consultas_v1:
            with medindo("snapshots V1") as v1:
                await BuildHistoricalFeatureSnapshots(
                    source=estado,
                    policy=TemporalAvailabilityPolicy.default(),
                    batch_size=LOTE,
                ).execute(
                    source_corpus=origem, match_ids=partidas, as_of_of=_um_corte
                )

        lotes = -(-len(partidas) // LOTE)
        esperadas_v1 = lotes * 5
        esperadas_v2 = lotes * CONSULTAS_POR_LOTE + CONSULTAS_DE_COBERTURA

        _relatar(
            f"PR-05.4 · {saida.built:_} snapshots de {espaco.size} features",
            [
                f"matches            {len(partidas):_}",
                f"snapshots          {saida.built:_}",
                f"features/snapshot  {espaco.size}",
                f"feature values     {saida.feature_values:_} "
                f"({saida.available_values:_} disponíveis)",
                "",
                f"duration           {v2.segundos:.2f}s",
                f"snapshots/sec      {v2.por_segundo(saida.built):.0f}",
                f"features/sec       {v2.por_segundo(saida.feature_values):.0f}",
                f"peak memory        {v2.pico_mb:.0f} MB",
                f"queries            {consultas_v2.total:_} "
                f"({lotes} lotes de {CONSULTAS_POR_LOTE} + 1 cobertura)",
                f"batch              {LOTE}",
                "",
                "── o que o contexto acrescenta (§178, §179) ──",
                f"V1 (75 features)   {v1.segundos:.2f}s · {consultas_v1.total:_} "
                f"consultas · {v1.pico_mb:.0f} MB",
                f"V2 (105 features)  {v2.segundos:.2f}s · {consultas_v2.total:_} "
                f"consultas · {v2.pico_mb:.0f} MB",
                f"delta de consultas {consultas_v2.total - consultas_v1.total:_} "
                f"para {len(partidas):_} partidas",
                "",
                f"por alvo           {consultas_v2.por_alvo}",
                f"indisponíveis      {saida.unavailable_by_reason}",
            ],
        )

        # ---- os critérios --------------------------------------------------

        # §177 — todas as partidas viraram snapshot, com as 105 dimensões.
        assert saida.built == len(partidas)
        assert saida.feature_values == saida.built * espaco.size == saida.built * 105

        # §178 — o CONTEXTO acrescenta um número CONSTANTE por lote. Uma
        # leitura por partida daria vinte mil consultas para dez mil partidas.
        assert consultas_v1.total == esperadas_v1
        assert consultas_v2.total == esperadas_v2, consultas_v2.por_alvo
        acrescimo_por_lote = (consultas_v2.total - CONSULTAS_DE_COBERTURA) / lotes - 5
        assert acrescimo_por_lote == 2.0

        # §179 — o MERCADO acrescenta ZERO. Ele sai do `OddsState`, e o corpus
        # deste cenário nem publica `ODDS` — as vinte e uma dimensões existem e
        # são indisponíveis sem custar consulta nenhuma.
        assert "canonical_odds_observations" in consultas_v2.por_alvo
        assert consultas_v2.por_alvo["canonical_odds_observations"] == lotes

        # O custo é linear na FORMA.
        assert v2.segundos < 900, (
            f"a extração V2 levou {v2.segundos:.0f}s para {saida.built:_} snapshots"
        )

        # §181 — a saída é limitada.
        assert len(saida.snapshots) == SNAPSHOT_SAMPLE_LIMIT_V2
        assert saida.sample_truncated

        # O pico não segue o corpus: a V2 carrega trinta dimensões a mais por
        # snapshot, e um snapshot vivo por vez.
        assert v2.pico_mb < v1.pico_mb * 3, (
            f"V1 {v1.pico_mb:.0f} MB contra V2 {v2.pico_mb:.0f} MB"
        )
