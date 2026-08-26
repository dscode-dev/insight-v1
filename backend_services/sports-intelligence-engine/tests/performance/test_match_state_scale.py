"""O BENCHMARK DO PR-05.2: reconstruir estado sobre um corpus de 10.000 partidas.

O QUE ELE MEDE, e por que cada número está aqui (§155 ao §158):

    duração e throughput      estados por segundo — o custo do reducer sobre
                              uma história inteira, e não sobre um caso
    consultas por LOTE        o número exato — cinco, e nunca seis por acidente
    consultas por partida     ela é CONSTANTE em qualquer volume, e não cresce:
                              com lote fixo, é 5/lote; com N+1, seria 5,0
    pico de memória           a prova de que o lote não materializa o corpus
    determinismo em volume    o tamanho do lote é detalhe de execução, e não
                              pode mudar o que sai

O CRITÉRIO É A FORMA DA CURVA, e nunca o segundo absoluto. Uma máquina mais
lenta muda os tempos e não muda o que reprovaria: a leitura consultar por
PARTIDA em vez de por lote, o pico seguir o tamanho do corpus, ou dois lotes
diferentes produzirem estados diferentes.

ELE NÃO PUBLICA UM CORPUS «DE MENTIRA». O cenário é o do PR-04.4.2 — intake,
resolução, fusão, qualidade, build de partida, canonicalização de evento e
publicação, com PostgreSQL e MinIO reais —, e é sobre o corpus que sai dali
que o estado é reconstruído. Um benchmark montado sobre um duplo mediria o
duplo.

POR QUE UM TESTE SÓ, E NÃO SETE. A fixture `cenario` é por FUNÇÃO: cada teste
que a pede reconstrói o pipeline inteiro — cento e dez mil eventos
canonicalizados e duas versões compostas. Sete testes seriam sete pipelines, e
o benchmark levaria horas para medir o que se mede em minutos. As medições
ficam num teste só, em seções nomeadas, e cada critério continua sendo uma
asserção própria com a sua mensagem.

O QUE ELE NÃO MEDE, e a omissão é deliberada: NADA de feature. O PR-05.2 não
tem feature, e um número de «features por segundo» aqui seria inventado.
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
from sports_intelligence.application.use_cases.feature_state import (
    STATE_SAMPLE_LIMIT,
    BuildHistoricalMatchStates,
)
from sports_intelligence.domain.corpus.versions import (
    CORPUS_PUBLISHER,
    DatasetVersionStatus,
)
from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.context import CorpusSource
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

#: Quem publica. Construído aqui em vez de importado do benchmark do corpus:
#: reexportar um símbolo de outro módulo de teste faz o `mypy` reclamar com
#: razão — a fixture `cenario` é o que se reaproveita, e não a papelada dela.
PUBLICADOR = Actor.service(CORPUS_PUBLISHER)

#: O recorte pequeno do §158. A comparação 1k contra 10k é o que revela a
#: FORMA da curva: com leitura em lote, o número de consultas acompanha os
#: LOTES, e a razão por partida fica igual nas duas escalas.
PARTIDAS_PEQUENAS: Final[int] = 1_000

#: O lote padrão da medição. Ele é o eixo do §158: as consultas crescem com o
#: número de LOTES, e não com o de partidas.
LOTE: Final[int] = 500

#: O corte de referência. Um só, e no meio do segundo tempo: medir vários
#: cortes por partida mediria a multiplicação, e não a reconstrução.
CORTE_MINUTO: Final[int] = 60


def _corte(match_id: MatchId) -> Sequence[FeatureAsOf]:
    return (FeatureAsOf.at(match_id, Period.SECOND_HALF, CORTE_MINUTO),)


async def _publicar(cenario: dict[str, Any]) -> tuple[Any, Any]:  # noqa: F811
    """Compõe e PUBLICA a versão com eventos — o insumo do estado.

    A PUBLICAÇÃO NÃO É OPCIONAL (§2 do PR-05.1). `CorpusSource` recusa versão
    que não seja legível como corpus, e com razão: uma versão em `BUILDING`
    pode estar com a pertinência pela metade, e o estado descreveria um corpus
    que nunca existiu.
    """
    saida, _medida, _consultas = await _compor(
        cenario,
        nome=f"perf-estado-{_uuid.uuid4().hex[:6]}",
        event_runs=(cenario["eventos_grandes"].id,),
    )
    pipeline = cenario["anterior"]["pipeline"]
    contêiner = build_corpus_container(
        database=cenario["banco"],
        clock=pipeline.clock,
        audit=pipeline.audit,
        store=cenario["store"],
    )
    versao = await contêiner.publish_version.execute(actor=PUBLICADOR, version_id=saida.version.id)
    assert versao.status is DatasetVersionStatus.READY
    return versao, saida.manifest


def _origem(versao: Any, manifesto: Any) -> CorpusSource:
    """A origem, montada com as famílias que a versão DE FATO publicou."""
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
    """Percorre a pertinência por keyset — como quem consome faria (§80)."""
    todas: list[MatchId] = []
    ultimo: str | None = None
    while True:
        pagina = list(await fonte.match_ids(version_id, limit=2_000, after=ultimo))
        if not pagina:
            return todas
        todas.extend(pagina)
        ultimo = str(pagina[-1])


class TestOEstadoEmVolume:
    async def test_reconstruir_o_corpus_inteiro(self, cenario: dict[str, Any]) -> None:  # noqa: F811
        """§155 ao §160. Uma travessia do pipeline, todas as medições."""
        versao, manifesto = await _publicar(cenario)
        banco = cenario["banco"]
        fonte = PostgresHistoricalMatchStateSource(banco)
        origem = _origem(versao, manifesto)
        partidas = await _todas_as_partidas(fonte, versao.id)
        assert len(partidas) >= PARTIDAS_PEQUENAS, (
            f"a versão publicou {len(partidas)} partidas, abaixo das "
            f"{PARTIDAS_PEQUENAS} que o benchmark exige"
        )
        pequenas = partidas[:PARTIDAS_PEQUENAS]

        def caso(*, batch_size: int = LOTE) -> BuildHistoricalMatchStates:
            return BuildHistoricalMatchStates(
                source=fonte,
                policy=TemporalAvailabilityPolicy.default(),
                batch_size=batch_size,
            )

        # ---- 1. o corpus inteiro: duração, throughput, memória, consultas --
        async with contando_consultas(banco) as consultas_grandes:
            with medindo("reconstrução do corpus") as grande:
                saida = await caso().execute(
                    source_corpus=origem, match_ids=partidas, as_of_of=_corte
                )

        # ---- 2. um décimo das partidas, para revelar a FORMA da curva ------
        async with contando_consultas(banco) as consultas_pequenas:
            with medindo("reconstrução de mil") as pequena:
                await caso().execute(source_corpus=origem, match_ids=pequenas, as_of_of=_corte)

        # ---- 3. o determinismo sob lotes diferentes ------------------------
        estreito = await caso(batch_size=97).execute(
            source_corpus=origem, match_ids=pequenas, as_of_of=_corte
        )
        largo = await caso(batch_size=1_000).execute(
            source_corpus=origem, match_ids=pequenas, as_of_of=_corte
        )
        de_novo = await caso(batch_size=1_000).execute(
            source_corpus=origem, match_ids=pequenas, as_of_of=_corte
        )

        por_partida_grande = consultas_grandes.total / len(partidas)
        por_partida_pequeno = consultas_pequenas.total / len(pequenas)
        lotes_pequenos = -(-len(pequenas) // LOTE)
        lotes_grandes = -(-len(partidas) // LOTE)
        proporcao = len(partidas) / len(pequenas)

        _relatar(
            f"PR-05.2 · reconstrução de {len(partidas):_} estados",
            [
                f"duração          {grande.segundos:.2f}s · "
                f"{grande.por_segundo(saida.built):.0f} estados/s",
                f"pico de memória  {grande.pico_mb:.0f} MB",
                "",
                f"reconstruídos    {saida.built:_}",
                f"parciais         {saida.partial:_} · completos {saida.complete:_}",
                f"amostra          {len(saida.states):_} "
                f"({'truncada' if saida.sample_truncated else 'completa'})",
                f"problemas        {saida.issues_by_code}",
                "",
                "── escalonamento ──",
                f"{len(pequenas):_} partidas · {lotes_pequenos:_} lotes · "
                f"{consultas_pequenas.total:_} consultas · "
                f"{por_partida_pequeno:.4f} por partida · {pequena.pico_mb:.0f} MB · "
                f"{pequena.segundos:.2f}s",
                f"{len(partidas):_} partidas · {lotes_grandes:_} lotes · "
                f"{consultas_grandes.total:_} consultas · "
                f"{por_partida_grande:.4f} por partida · {grande.pico_mb:.0f} MB · "
                f"{grande.segundos:.2f}s",
                "",
                f"por alvo         {consultas_grandes.por_alvo}",
            ],
        )

        # ---- os critérios, um a um ----------------------------------------

        # §155. Todas as partidas da versão viraram estado.
        assert saida.built == len(partidas)

        # §156. O CUSTO É LINEAR NA FORMA. Um reducer quadrático sobre a
        # história de dez mil partidas não terminaria em minuto nenhum.
        assert grande.segundos < 600, (
            f"a reconstrução levou {grande.segundos:.0f}s para {len(partidas):_} "
            "partidas: o custo deixou de ser linear"
        )

        # §158. A LEITURA É POR LOTE, e o critério certo é o número EXATO —
        # não uma tendência.
        #
        # A primeira versão deste teste exigia que consultas/partida CAÍSSE ao
        # multiplicar o volume por dez. Ela estava errada, e a medição a
        # corrigiu: com o lote fixo em 500, a razão é 5/500 = 0,01 nas DUAS
        # escalas. A constância é justamente a propriedade que se quer — o
        # custo por partida não depende de quantas partidas há. Uma leitura
        # N+1 daria 5,0 por partida, quinhentas vezes mais.
        #
        # Cinco: membros+partidas, escalações, eventos, cotações, resultados.
        # Uma sexta consulta pode ser legítima — desde que seja uma decisão, e
        # não um acidente.
        assert consultas_pequenas.total == lotes_pequenos * 5, (
            f"{consultas_pequenas.total} consultas para {lotes_pequenos} lotes — o "
            f"esperado é {lotes_pequenos * 5}. Por alvo: {consultas_pequenas.por_alvo}"
        )
        assert consultas_grandes.total == lotes_grandes * 5, (
            f"{consultas_grandes.total} consultas para {lotes_grandes} lotes — o "
            f"esperado é {lotes_grandes * 5}. Por alvo: {consultas_grandes.por_alvo}"
        )
        # E ela NUNCA cresce com o volume. Se crescesse, o lote teria deixado
        # de ser o eixo do custo.
        assert por_partida_grande <= por_partida_pequeno
        assert por_partida_grande < 0.1, (
            f"{por_partida_grande:.4f} consultas por partida: a leitura está "
            "consultando por PARTIDA, e não por lote"
        )

        # §157. O pico NÃO segue o corpus. Dez vezes mais partidas não pode
        # custar dez vezes a memória — se custar, o lote virou materialização.
        assert grande.pico_mb < pequena.pico_mb * proporcao, (
            f"o pico foi de {pequena.pico_mb:.0f} MB para {grande.pico_mb:.0f} MB ao "
            f"multiplicar as partidas por {proporcao:.0f}: o lote está materializando "
            "o corpus"
        )

        # §159, §160. A saída é limitada: contagem exata, amostra com teto.
        assert len(saida.states) == STATE_SAMPLE_LIMIT
        assert saida.sample_truncated
        assert saida.built > len(saida.states) * 10

        # §16 do PR-04.4.2, aplicado ao estado: o tamanho do lote é detalhe de
        # execução, e não pode mudar o que sai.
        assert estreito.built == largo.built
        assert [e.fingerprint for e in estreito.states] == [e.fingerprint for e in largo.states]

        # §196. E duas execuções do MESMO lote dão as mesmas impressões.
        assert [e.fingerprint for e in de_novo.states] == [e.fingerprint for e in largo.states]
