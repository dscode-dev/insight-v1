"""O BENCHMARK DO PR-05.3: setenta e cinco features sobre 10.000 partidas.

O QUE ELE MEDE, e por que cada número está aqui (§175 ao §181):

    duração e throughput      snapshots/s e features/s — o custo real de
                              produzir setecentos e cinquenta mil valores
    consultas                 a extração precisa acrescentar ZERO ao caminho
                              do estado; se acrescentar, o PR está bloqueado
    pico de memória           a prova de que o lote não materializa o corpus
    dois regimes              10.000 partidas com 1 corte contra 2.000 com 5
                              cortes — os mesmos 10.000 snapshots, e a
                              diferença é quanto do custo é LEITURA

O SEGUNDO REGIME É O QUE PROVA O §113. Cinco cortes da mesma partida
reaproveitam o insumo dentro do lote: se o corpus fosse recarregado por corte,
as consultas quintuplicariam. O benchmark compara os dois e afirma o número.

O CRITÉRIO É A FORMA, e nunca o segundo absoluto. Uma máquina mais lenta muda
os tempos e não muda o que reprovaria: uma consulta por feature, o pico
seguindo o corpus, ou dois lotes produzindo snapshots diferentes.

POR QUE UM TESTE SÓ. A fixture `cenario` é por função e reconstrói o pipeline
inteiro — cento e dez mil eventos canonicalizados e duas versões compostas.
Cada teste que a pedisse pagaria isso de novo.
"""

from __future__ import annotations

import uuid as _uuid
from collections.abc import Sequence
from typing import Any, Final

import pytest

from apps.corpus_composition import build_corpus_container
from sports_intelligence.adapters.postgres.feature_state import (
    PostgresHistoricalMatchStateSource,
)
from sports_intelligence.application.use_cases.feature_snapshot import (
    SNAPSHOT_SAMPLE_LIMIT,
    BuildHistoricalFeatureSnapshots,
)
from sports_intelligence.application.use_cases.feature_state import (
    BuildHistoricalMatchStates,
)
from sports_intelligence.domain.corpus.versions import (
    CORPUS_PUBLISHER,
    DatasetVersionStatus,
)
from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.extraction.catalog import (
    match_state_raw_space_v1,
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

#: O lote de leitura. Ele é o eixo do §180: as consultas seguem os LOTES.
LOTE: Final[int] = 500

#: O segundo regime do §177: menos partidas, mais cortes por partida — e o
#: mesmo total de snapshots, para que os dois números sejam comparáveis.
PARTIDAS_MULTICORTE: Final[int] = 2_000
CORTES_POR_PARTIDA: Final[tuple[int, ...]] = (50, 55, 60, 65, 70)

#: O corte único do primeiro regime.
CORTE_UNICO: Final[int] = 60


def _um_corte(match_id: MatchId) -> Sequence[FeatureAsOf]:
    return (FeatureAsOf.at(match_id, Period.SECOND_HALF, CORTE_UNICO),)


def _cinco_cortes(match_id: MatchId) -> Sequence[FeatureAsOf]:
    return tuple(
        FeatureAsOf.at(match_id, Period.SECOND_HALF, m) for m in CORTES_POR_PARTIDA
    )


async def _publicar(cenario: dict[str, Any]) -> tuple[Any, Any]:  # noqa: F811
    saida, _medida, _consultas = await _compor(
        cenario,
        nome=f"perf-snapshot-{_uuid.uuid4().hex[:6]}",
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


class TestOSnapshotEmVolume:
    async def test_extrair_features_do_corpus_inteiro(
        self,
        cenario: dict[str, Any],  # noqa: F811
    ) -> None:
        """§175 ao §181. Uma travessia do pipeline, todas as medições."""
        versao, manifesto = await _publicar(cenario)
        banco = cenario["banco"]
        fonte = PostgresHistoricalMatchStateSource(banco)
        origem = _origem(versao, manifesto)
        partidas = await _todas_as_partidas(fonte, versao.id)
        espaco = match_state_raw_space_v1()
        assert len(partidas) >= PARTIDAS_MULTICORTE

        def caso(*, batch_size: int = LOTE) -> BuildHistoricalFeatureSnapshots:
            return BuildHistoricalFeatureSnapshots(
                source=fonte,
                policy=TemporalAvailabilityPolicy.default(),
                batch_size=batch_size,
            )

        # ---- regime A: 10.000 partidas, um corte cada (§176) ---------------
        async with contando_consultas(banco) as consultas_a:
            with medindo("snapshots · um corte por partida") as regime_a:
                saida_a = await caso().execute(
                    source_corpus=origem, match_ids=partidas, as_of_of=_um_corte
                )

        # ---- regime B: 2.000 partidas, cinco cortes cada (§177) ------------
        recorte = partidas[:PARTIDAS_MULTICORTE]
        async with contando_consultas(banco) as consultas_b:
            with medindo("snapshots · cinco cortes por partida") as regime_b:
                saida_b = await caso().execute(
                    source_corpus=origem, match_ids=recorte, as_of_of=_cinco_cortes
                )

        # ---- o custo do ESTADO sozinho, para isolar o da extração (§179) ---
        async with contando_consultas(banco) as consultas_estado:
            with medindo("só estado") as so_estado:
                await BuildHistoricalMatchStates(
                    source=fonte,
                    policy=TemporalAvailabilityPolicy.default(),
                    batch_size=LOTE,
                ).execute(
                    source_corpus=origem, match_ids=partidas, as_of_of=_um_corte
                )

        # ---- determinismo sob lotes diferentes -----------------------------
        estreito = await caso(batch_size=97).execute(
            source_corpus=origem, match_ids=recorte[:500], as_of_of=_um_corte
        )
        largo = await caso(batch_size=1_000).execute(
            source_corpus=origem, match_ids=recorte[:500], as_of_of=_um_corte
        )

        lotes_a = -(-len(partidas) // LOTE)
        lotes_b = -(-len(recorte) // LOTE)

        _relatar(
            f"PR-05.3 · {saida_a.built:_} snapshots de {espaco.size} features",
            [
                f"matches            {len(partidas):_}",
                f"snapshots          {saida_a.built:_}",
                f"features/snapshot  {espaco.size}",
                f"feature values     {saida_a.feature_values:_} "
                f"({saida_a.available_values:_} disponíveis)",
                f"events             {cenario['registros_grandes']:_}",
                "",
                f"duration           {regime_a.segundos:.2f}s",
                f"snapshots/sec      {regime_a.por_segundo(saida_a.built):.0f}",
                f"features/sec       {regime_a.por_segundo(saida_a.feature_values):.0f}",
                f"peak memory        {regime_a.pico_mb:.0f} MB",
                f"queries            {consultas_a.total:_} ({lotes_a} lotes de 5)",
                f"batch              {LOTE}",
                "",
                "── extração contra estado puro (§179) ──",
                f"só estado          {so_estado.segundos:.2f}s · "
                f"{consultas_estado.total:_} consultas · {so_estado.pico_mb:.0f} MB",
                f"estado + features  {regime_a.segundos:.2f}s · "
                f"{consultas_a.total:_} consultas · {regime_a.pico_mb:.0f} MB",
                "",
                "── regime B: cinco cortes por partida (§177) ──",
                f"matches            {len(recorte):_}",
                f"snapshots          {saida_b.built:_}",
                f"duration           {regime_b.segundos:.2f}s · "
                f"{regime_b.por_segundo(saida_b.built):.0f} snapshots/s",
                f"queries            {consultas_b.total:_} ({lotes_b} lotes de 5)",
                f"peak memory        {regime_b.pico_mb:.0f} MB",
                "",
                f"indisponíveis      {saida_a.unavailable_by_reason}",
            ],
        )

        # ---- os critérios --------------------------------------------------

        # §176 — todas as partidas viraram snapshot.
        assert saida_a.built == len(partidas)
        assert saida_a.feature_values == saida_a.built * espaco.size

        # §177 — dois mil por cinco dá os mesmos dez mil snapshots.
        assert saida_b.built == len(recorte) * len(CORTES_POR_PARTIDA)

        # §179, §180 — A EXTRAÇÃO NÃO ACRESCENTA CONSULTA NENHUMA. Este é o
        # bloqueio do §95: uma consulta por feature daria setenta e cinco por
        # corte, e setecentas e cinquenta mil no lote.
        assert consultas_a.total == consultas_estado.total == lotes_a * 5, (
            f"estado {consultas_estado.total}, estado+features {consultas_a.total}, "
            f"esperado {lotes_a * 5}. Por alvo: {consultas_a.por_alvo}"
        )

        # §113 — cinco cortes por partida NÃO recarregam o corpus cinco vezes.
        assert consultas_b.total == lotes_b * 5, (
            f"{consultas_b.total} consultas para {lotes_b} lotes e "
            f"{saida_b.built} snapshots — o insumo está sendo relido por corte"
        )

        # §175 — o custo é linear na forma. Um extrator `O(E * F)` sobre
        # setecentos e cinquenta mil valores não terminaria em minuto nenhum.
        assert regime_a.segundos < 900, (
            f"a extração levou {regime_a.segundos:.0f}s para {saida_a.built:_} "
            "snapshots: o custo deixou de ser linear"
        )

        # §181 — a saída é limitada: contagem exata, amostra com teto.
        assert len(saida_a.snapshots) == SNAPSHOT_SAMPLE_LIMIT
        assert saida_a.sample_truncated

        # E o pico NÃO segue o corpus: o custo da extração sobre o do estado é
        # o de um snapshot vivo por vez, e não de dez mil.
        assert regime_a.pico_mb < so_estado.pico_mb * 10, (
            f"o pico foi de {so_estado.pico_mb:.0f} MB (estado) para "
            f"{regime_a.pico_mb:.0f} MB (estado + features): a extração está "
            "acumulando snapshots"
        )

        # §162, §203 — o tamanho do lote é detalhe de execução.
        assert estreito.built == largo.built
        assert [s.fingerprint for s in estreito.snapshots] == [
            s.fingerprint for s in largo.snapshots
        ]
