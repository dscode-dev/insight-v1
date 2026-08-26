"""O BENCHMARK DO PR-04.4.2: 10.000 partidas e 100.000 eventos publicados.

O QUE ELE MEDE, e por que cada número está aqui (§88, §89):

    duração da composição      com e SEM eventos — a diferença é o custo real
                               de publicar evento, e não uma estimativa
    duração da publicação      o gate reconcilia contagens por agregação
    eventos/s                  o throughput da materialização
    bytes e compressão         quanto o `events.parquet` custa em disco
    pico de memória            a prova de que o corpus não é materializado
                               inteiro (§90)
    consultas                  por LOTE, e nunca por evento (§91)

O CRITÉRIO É A FORMA DA CURVA, não o segundo absoluto. Uma máquina mais lenta
muda os tempos e não muda o que reprovaria: a composição consultar por EVENTO
em vez de por lote, ou o pico seguir o volume do corpus.

ELE NÃO PUBLICA UM CORPUS «DE MENTIRA». Passa pelo intake, pela resolução,
pela fusão, pela qualidade, pelo build de partida, pela canonicalização de
evento e pela publicação — com PostgreSQL e object store reais.
"""

from __future__ import annotations

import io
import uuid as _uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

import pytest

from apps.corpus_composition import build_corpus_container
from sports_intelligence.adapters.postgres.database import Database, PostgresUnitOfWork
from sports_intelligence.adapters.postgres.events import (
    PostgresCanonicalEventBuildRunRepository,
    PostgresCanonicalEventWriter,
    PostgresEventBuildRecordRepository,
)
from sports_intelligence.adapters.postgres.resolution import (
    PostgresProviderMappingRepository,
)
from sports_intelligence.application.use_cases.events import (
    RunHistoricalEventCanonicalization,
)
from sports_intelligence.domain.corpus.versions import (
    DatasetVersionStatus,
    VersionInputs,
)
from sports_intelligence.domain.events.records import (
    HistoricalEventRecord,
    RawEventClock,
    RawEventPoint,
)
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.events.typing_map import EventTypeMapping
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.mappings import ProviderEntityMapping
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.identity import (
    DatasetId,
    EntityId,
    MatchId,
    ProviderId,
)
from sports_intelligence.domain.shared.provenance import LicenseClass
from sports_intelligence.domain.shared.temporal import Period, instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.domain.sources.records import DatasetRecordRef
from sports_intelligence.historical.events.eligibility import EventEligibilityPolicy
from sports_intelligence.ports.clock import FrozenClock
from tests.performance.test_historical_corpus_scale import (
    LOTE,
    PARTIDAS_MINIMAS,
    PUBLICADOR,
    REGISTROS,
    _ate_o_build,
    _escopo,
)
from tests.performance.test_resolution_100k import _relatar
from tests.support.corpus import Corpus
from tests.support.instrumentation import contando_consultas, medindo
from tests.support.pipeline import Pipeline

pytestmark = [pytest.mark.performance, pytest.mark.integration]

#: O volume do §88. Dez eventos por partida em dez mil partidas: é a escala em
#: que o corpus deixa de caber na memória se alguém o materializar inteiro.
EVENTOS_POR_PARTIDA: Final[int] = 10

#: O volume MENOR, para a comparação do §91. Ele usa as MESMAS partidas — o
#: que muda é quantas delas têm evento, e é isso que isola o custo do evento
#: do custo da partida.
PARTIDAS_COM_POUCOS_EVENTOS: Final[int] = 1_000

PROVEDOR: Final[ProviderId] = ProviderId("perf_corpus_eventos")
CANONICALIZADOR = Actor(id="historical-event-canonicalizer", kind=ActorKind.SERVICE)

#: Os tipos, na proporção de um jogo real. A mistura importa para o
#: denominador espacial: o cartão não é espacialmente elegível (§27).
_TIPOS: Final[tuple[tuple[str, int], ...]] = (
    ("pass", 60),
    ("shot", 20),
    ("card", 10),
    ("goal", 10),
)


def _tipo(indice: int) -> str:
    """O tipo do evento `n` — determinístico, sem `random`.

    Duas execuções do benchmark que gerem cenários diferentes não são
    comparáveis, e a comparação entre execuções é a única coisa que um número
    de throughput permite fazer.
    """
    posicao = indice % 100
    acumulado = 0
    for nome, peso in _TIPOS:
        acumulado += peso
        if posicao < acumulado:
            return nome
    return "pass"


def _tabela() -> EventTypeMapping:
    return EventTypeMapping(
        provider_id=PROVEDOR,
        entries={
            "pass": EventType.PASS,
            "shot": EventType.SHOT,
            "card": EventType.CARD,
            "goal": EventType.GOAL,
        },
    )


def _fracao(n: int) -> Decimal:
    return Decimal(n % 100) / Decimal(100)


def _registro(
    n: int, *, partida: int, prefixo: str, dataset: DatasetId, arquivo: str
) -> HistoricalEventRecord:
    tipo = _tipo(n)
    minuto = (n // 3) % 90
    return HistoricalEventRecord(
        record_ref=DatasetRecordRef(dataset_id=dataset, file_id=arquivo, record_number=n + 2),
        provider_id=PROVEDOR,
        match_reference=f"perf-corpus-match-{partida}",
        raw_type=tipo,
        clock=RawEventClock(
            period=Period.FIRST_HALF if minuto < 45 else Period.SECOND_HALF,
            minute=minuto,
        ),
        provider_event_id=f"{prefixo}-{n}",
        sequence=n,
        team_reference=f"perf-corpus-team-{partida % 20}",
        player_reference=f"perf-corpus-player-{n % 22}",
        # O CARTÃO NÃO TEM COORDENADA — é o que faz o denominador espacial do
        # §27 valer alguma coisa neste benchmark.
        start_point=(None if tipo == "card" else RawEventPoint(x=_fracao(n), y=_fracao(n * 7 + 3))),
        details=(
            {"EVENT_OUTCOME": "GOAL" if tipo == "goal" else "SAVED", "EVENT_XG": "0.07"}
            if tipo in ("goal", "shot")
            else {"EVENT_CARD_TYPE": "YELLOW"}
            if tipo == "card"
            else {}
        ),
    )


async def _semear_traducoes(banco: Database, partidas: Sequence[MatchId], corpus: Corpus) -> None:
    """As traduções do provedor de eventos para as partidas do build."""
    repositorio = PostgresProviderMappingRepository(banco)
    agora = instant(datetime(2026, 1, 1, tzinfo=UTC))
    async with banco.acquire() as conexao:
        await conexao.execute(
            "DELETE FROM provider_entity_mappings WHERE provider_id = $1", str(PROVEDOR)
        )
    for n, partida in enumerate(partidas):
        await repositorio.create_if_absent(
            _mapeamento(SubjectType.MATCH, f"perf-corpus-match-{n}", partida.value, agora)
        )
    for n, time in enumerate([t.team for t in corpus.teams[:20]]):
        await repositorio.create_if_absent(
            _mapeamento(SubjectType.TEAM, f"perf-corpus-team-{n}", time.id.value, agora)
        )
    for n, jogador in enumerate(corpus.players[:22]):
        await repositorio.create_if_absent(
            _mapeamento(SubjectType.PLAYER, f"perf-corpus-player-{n}", jogador.id.value, agora)
        )


def _mapeamento(
    subject: SubjectType, externo: str, canonico: Any, at: Any
) -> ProviderEntityMapping:
    return ProviderEntityMapping(
        id=str(_uuid.uuid4()),
        provider_id=PROVEDOR,
        entity_type=subject,
        provider_entity_id=externo,
        canonical_entity_id=EntityId(canonico),
        resolution_decision_id=str(_uuid.uuid4()),
        created_at=at,
        created_by="pr0442-perf",
    )


async def _registrar_dataset(banco: Database, sufixo: str) -> DatasetId:
    """Um dataset mínimo, só para a chave estrangeira da execução."""
    identificador = DatasetId.derive("perf-corpus", sufixo)
    async with banco.acquire() as conexao:
        await conexao.execute(
            """
            INSERT INTO datasets (
                id, name, version_major, version_minor, lifecycle,
                declared_competitions, declared_seasons, created_at, created_by,
                updated_at
            )
            VALUES ($1, $2, 1, 0, 'STAGED', '{PERF}', '{2024}', now(),
                    'pr0442-perf', now())
            ON CONFLICT (id) DO NOTHING
            """,
            identificador.value,
            f"perf-corpus-eventos-{sufixo}",
        )
    return identificador


async def _canonicalizar(
    *,
    banco: Database,
    pipeline: Pipeline,
    dataset_id: DatasetId,
    elegiveis: frozenset[MatchId],
    registros: Sequence[HistoricalEventRecord],
    lote: int = 1_000,
) -> Any:
    async def lotes() -> AsyncIterator[Sequence[HistoricalEventRecord]]:
        for inicio in range(0, len(registros), lote):
            yield registros[inicio : inicio + lote]

    caso = RunHistoricalEventCanonicalization(
        mappings=PostgresProviderMappingRepository(banco),
        events=PostgresCanonicalEventWriter(banco),
        lineage=PostgresEventBuildRecordRepository(banco),
        runs=PostgresCanonicalEventBuildRunRepository(banco),
        clock=FrozenClock(pipeline.clock.now()),
        types=_tabela(),
        policy=EventEligibilityPolicy.research(),
        uow=PostgresUnitOfWork(banco),
    )
    return await caso.execute(
        actor=CANONICALIZADOR,
        dataset_id=dataset_id,
        provider_id=PROVEDOR,
        batches=lotes(),
        eligible_matches=elegiveis,
        license_class=LicenseClass.PUBLIC_DOMAIN,
    )


@pytest.fixture
async def cenario(banco_semeado: Database, object_store: Any, corpus: Corpus) -> dict[str, Any]:
    """Dez mil partidas construídas, e os eventos canonicalizados sobre elas.

    A CANONICALIZAÇÃO ACONTECE FORA DA MEDIÇÃO. Ela já tem baseline própria
    (PR-04.4.1); o que este arquivo mede é o que vem DEPOIS dela — a
    publicação desses eventos num corpus.
    """
    anterior = await _ate_o_build(banco_semeado, object_store, corpus, registros=REGISTROS)
    pipeline: Pipeline = anterior["pipeline"]

    async with banco_semeado.acquire() as conexao:
        linhas = await conexao.fetch(
            """
            SELECT DISTINCT match_id
            FROM canonical_build_records
            WHERE build_run_id = $1 AND fact_type = 'MATCH' AND status = ANY($2::text[])
            ORDER BY match_id
            """,
            _uuid.UUID(anterior["build_run"].id),
            ["BUILT", "REUSED"],
        )
    partidas = [MatchId(linha["match_id"]) for linha in linhas]
    assert len(partidas) >= PARTIDAS_MINIMAS, (
        f"o build produziu {len(partidas)} partidas, abaixo das {PARTIDAS_MINIMAS} "
        "que o benchmark do corpus exige"
    )
    await _semear_traducoes(banco_semeado, partidas, corpus)

    grande = await _registrar_dataset(banco_semeado, "grande")
    pequeno = await _registrar_dataset(banco_semeado, "pequeno")
    arquivo = str(DatasetId.derive("perf-corpus", "arquivo"))

    # O CONJUNTO GRANDE: todas as partidas, dez eventos cada.
    registros_grandes = [
        _registro(
            n=indice * EVENTOS_POR_PARTIDA + i,
            partida=indice,
            prefixo="g",
            dataset=grande,
            arquivo=arquivo,
        )
        for indice in range(len(partidas))
        for i in range(EVENTOS_POR_PARTIDA)
    ]
    # O CONJUNTO PEQUENO: as MESMAS partidas iniciais, um décimo dos eventos.
    registros_pequenos = [
        _registro(
            n=indice * EVENTOS_POR_PARTIDA + i,
            partida=indice,
            prefixo="p",
            dataset=pequeno,
            arquivo=arquivo,
        )
        for indice in range(PARTIDAS_COM_POUCOS_EVENTOS)
        for i in range(EVENTOS_POR_PARTIDA)
    ]

    elegiveis = frozenset(partidas)
    execucao_grande = await _canonicalizar(
        banco=banco_semeado,
        pipeline=pipeline,
        dataset_id=grande,
        elegiveis=elegiveis,
        registros=registros_grandes,
    )
    execucao_pequena = await _canonicalizar(
        banco=banco_semeado,
        pipeline=pipeline,
        dataset_id=pequeno,
        elegiveis=elegiveis,
        registros=registros_pequenos,
    )
    return {
        "banco": banco_semeado,
        "store": object_store,
        "corpus": corpus,
        "anterior": anterior,
        "partidas": partidas,
        "eventos_grandes": execucao_grande.run,
        "eventos_pequenos": execucao_pequena.run,
        "registros_grandes": len(registros_grandes),
        "registros_pequenos": len(registros_pequenos),
    }


def _entradas(cenario: dict[str, Any], *, event_runs: tuple[str, ...]) -> VersionInputs:
    anterior = cenario["anterior"]
    return VersionInputs(
        build_run_ids=(anterior["build_run"].id,),
        quality_run_ids=(anterior["quality_run"].id,),
        fusion_run_ids=(anterior["fusion_run_id"],),
        resolution_run_ids=tuple(anterior["resolution_run_ids"]),
        event_build_run_ids=event_runs,
    )


async def _compor(
    cenario: dict[str, Any],
    *,
    nome: str,
    event_runs: tuple[str, ...],
    event_rows_batch: int = 20_000,
) -> tuple[Any, Any, Any]:
    """Compõe uma versão e devolve `(saída, medida, consultas)`."""
    pipeline: Pipeline = cenario["anterior"]["pipeline"]
    contêiner = build_corpus_container(
        database=cenario["banco"],
        clock=pipeline.clock,
        audit=pipeline.audit,
        store=cenario["store"],
        batch_size=LOTE,
    )
    # O NOME É ÚNICO POR EXECUÇÃO. `create_dataset` é idempotente por nome — e
    # é certo que seja —, então reaproveitar «perf-com-eventos» faria a segunda
    # rodada do benchmark encontrar a versão 1.0 da primeira e recusar compor.
    # O que se quer medir é a composição, não a colisão de nome.
    dataset = await contêiner.create_dataset.execute(
        actor=PUBLICADOR, name=f"{nome}-{_uuid.uuid4().hex[:8]}"
    )
    caso = replace(contêiner.build_version, event_rows_batch=event_rows_batch)
    async with contando_consultas(cenario["banco"]) as consultas:
        with medindo(f"composição {nome}") as medida:
            saida = await caso.execute(
                actor=PUBLICADOR,
                dataset_id=dataset.id,
                version=DatasetVersion(major=1, minor=0),
                scope=_escopo(cenario["corpus"]),
                inputs=_entradas(cenario, event_runs=event_runs),
                quality_run_id=cenario["anterior"]["quality_run"].id,
            )
    return saida, medida, consultas


def _bytes_de_evento(saida: Any) -> tuple[int, int, int]:
    """`(bytes, linhas, pedaços)` dos objetos da família EVENT.

    O NÚMERO DE PEDAÇOS É REPORTADO (§92) porque ele é consequência de uma
    decisão e não um acaso: cada chamada de materialização escreve UM pedaço
    com as linhas daquele recorte de página, então o tamanho do pedaço sai do
    lote de composição e do teto de eventos — e não de um número escolhido para
    o benchmark ficar bonito.
    """
    de_evento = [o for o in saida.manifest.objects if o.family == CoverageFamily.EVENT.value]
    return (
        sum(o.size_bytes for o in de_evento),
        sum(o.row_count for o in de_evento),
        len(de_evento),
    )


async def _compressao(cenario: dict[str, Any], saida: Any) -> float | None:
    """A razão de compressão REAL do Parquet — lida do rodapé do arquivo."""
    import pyarrow.parquet as pq

    de_evento = [o for o in saida.manifest.objects if o.family == CoverageFamily.EVENT.value]
    if not de_evento:
        return None
    # AS DUAS SOMAS SÃO POR COLUNA, e é a única forma honesta: o
    # `total_byte_size` do grupo de linhas é o tamanho DESCOMPRIMIDO, então
    # compará-lo com a soma dos descomprimidos daria sempre 1,0 — um número
    # que parece medido e não mede nada.
    comprimido = descomprimido = 0
    for objeto in de_evento[:5]:
        bruto = b"".join([p async for p in cenario["store"].open_stream(objeto.object_key)])
        metadados = pq.read_metadata(io.BytesIO(bruto))
        for i in range(metadados.num_row_groups):
            grupo = metadados.row_group(i)
            for c in range(grupo.num_columns):
                coluna = grupo.column(c)
                comprimido += coluna.total_compressed_size
                descomprimido += coluna.total_uncompressed_size
    return None if not comprimido else descomprimido / comprimido


class TestOCorpusComEventosEmVolume:
    async def test_dez_mil_partidas_e_cem_mil_eventos(self, cenario: dict[str, Any]) -> None:
        """§88, §89. O benchmark oficial, com o custo do evento ISOLADO.

        O ISOLAMENTO É A PARTE QUE IMPORTA. Medir só «a composição levou X»
        não diz quanto custou publicar evento — a mesma composição também
        escreve partida, escalação e odds. Compor DUAS vezes sobre o mesmo
        build, uma sem eventos e outra com, transforma a diferença em resposta.
        """
        _sem_eventos, sem_medida, sem_consultas = await _compor(
            cenario, nome="perf-sem-eventos", event_runs=()
        )
        com_eventos, com_medida, com_consultas = await _compor(
            cenario,
            nome="perf-com-eventos",
            event_runs=(cenario["eventos_grandes"].id,),
        )
        pipeline: Pipeline = cenario["anterior"]["pipeline"]
        contêiner = build_corpus_container(
            database=cenario["banco"],
            clock=pipeline.clock,
            audit=pipeline.audit,
            store=cenario["store"],
            batch_size=LOTE,
        )
        async with contando_consultas(cenario["banco"]) as consultas_da_publicacao:
            with medindo("publicação com eventos") as publicacao:
                versao = await contêiner.publish_version.execute(
                    actor=PUBLICADOR,
                    version_id=com_eventos.version.id,
                    reason=f"benchmark PR-04.4.2 · {cenario['registros_grandes']} eventos",
                )

        eventos = com_eventos.manifest.counts.events.total
        partidas = com_eventos.members_written
        lotes = max(1, -(-partidas // LOTE))
        bytes_de_evento, linhas_de_evento, pedacos = _bytes_de_evento(com_eventos)
        compressao = await _compressao(cenario, com_eventos)
        custo_do_evento = com_medida.segundos - sem_medida.segundos

        _relatar(
            f"PR-04.4.2 · {partidas:_} partidas · {eventos:_} eventos publicados",
            [
                f"composição SEM   {sem_medida.segundos:.1f}s · "
                f"pico {sem_medida.pico_mb:.0f} MB · {sem_consultas.total:_} consultas",
                f"composição COM   {com_medida.segundos:.1f}s · "
                f"pico {com_medida.pico_mb:.0f} MB · {com_consultas.total:_} consultas",
                f"custo do evento  {custo_do_evento:.1f}s · "
                f"{eventos / max(custo_do_evento, 0.001):.0f} eventos/s",
                f"publicação       {publicacao.segundos:.2f}s · "
                f"{consultas_da_publicacao.total:_} consultas",
                "",
                f"partidas         {partidas:_} em {lotes} lote(s) de {LOTE}",
                f"eventos          {eventos:_} · {linhas_de_evento:_} linha(s) no Parquet",
                f"pedaços          {pedacos:_} arquivo(s) · "
                f"{linhas_de_evento // max(pedacos, 1):_} linha(s) por pedaço",
                f"bytes de evento  {bytes_de_evento / 1_048_576:.1f} MB "
                f"({bytes_de_evento / max(eventos, 1):.0f} B/evento)",
                "compressão       "
                + ("indisponível" if compressao is None else f"{compressao:.1f}x (zstd)"),
                "",
                f"consultas evento {com_consultas.total - sem_consultas.total:_} a mais "
                f"({(com_consultas.total - sem_consultas.total) / lotes:.1f} por lote)",
                f"alvos            {com_consultas.mais_frequentes}",
                "",
                f"impressão        {versao.corpus_fingerprint}",
                f"estado           {versao.status.value}",
            ],
        )

        assert eventos == cenario["registros_grandes"]
        assert linhas_de_evento == eventos
        assert versao.status is DatasetVersionStatus.READY

        # §91: as consultas de evento crescem com os LOTES, e não com os
        # eventos. Com N+1 seriam >= 1 por evento.
        por_evento = (com_consultas.total - sem_consultas.total) / eventos
        assert por_evento < 0.05, (
            f"{com_consultas.total - sem_consultas.total} consultas a mais para "
            f"{eventos} eventos ({por_evento:.3f} por evento): a composição está "
            "lendo evento a evento, e não por lote (§91)"
        )
        # A PUBLICAÇÃO CONTINUA BARATA. A reconciliação de evento é um
        # `count(*)` e uma soma sobre o manifesto — nunca uma varredura.
        assert consultas_da_publicacao.total < 20, (
            f"{consultas_da_publicacao.total} consultas para publicar: o gate está "
            "varrendo os eventos em vez de conferi-los por agregação (§51)"
        )

    async def test_a_memoria_segue_o_lote_e_nao_o_corpus(self, cenario: dict[str, Any]) -> None:
        """§90. Dez vezes mais eventos não pode multiplicar o pico por dez.

        O QUE ISTO PEGA: um `list(events_of(...))` sobre a versão inteira, ou
        uma página que traga os eventos de todas as partidas de uma vez. Os
        dois passam em todos os outros testes deste arquivo.
        """
        _pequeno, medida_pequena, _c1 = await _compor(
            cenario, nome="perf-mem-pequeno", event_runs=(cenario["eventos_pequenos"].id,)
        )
        _grande, medida_grande, _c2 = await _compor(
            cenario, nome="perf-mem-grande", event_runs=(cenario["eventos_grandes"].id,)
        )
        _relatar(
            "PR-04.4.2 · memória por volume de evento",
            [
                f"{cenario['registros_pequenos']:_} eventos → pico {medida_pequena.pico_mb:.1f} MB",
                f"{cenario['registros_grandes']:_} eventos → pico {medida_grande.pico_mb:.1f} MB",
            ],
        )
        assert medida_grande.pico_mb < medida_pequena.pico_mb * 3, (
            f"pico de {medida_grande.pico_mb:.0f} MB contra "
            f"{medida_pequena.pico_mb:.0f} MB para um décimo dos eventos: o corpus "
            "está sendo materializado além do lote (§90)"
        )

    async def test_as_consultas_escalam_por_lote_e_nao_por_evento(
        self, cenario: dict[str, Any]
    ) -> None:
        """§91. Dez mil contra cem mil eventos, nas MESMAS partidas."""
        _pequeno, _m1, consultas_pequenas = await _compor(
            cenario, nome="perf-q-pequeno", event_runs=(cenario["eventos_pequenos"].id,)
        )
        _grande, _m2, consultas_grandes = await _compor(
            cenario, nome="perf-q-grande", event_runs=(cenario["eventos_grandes"].id,)
        )
        por_evento_pequeno = consultas_pequenas.total / cenario["registros_pequenos"]
        por_evento_grande = consultas_grandes.total / cenario["registros_grandes"]
        _relatar(
            "PR-04.4.2 · escalonamento de consultas",
            [
                f"{cenario['registros_pequenos']:_} eventos · "
                f"{consultas_pequenas.total:_} consultas · {por_evento_pequeno:.4f} por evento",
                f"{cenario['registros_grandes']:_} eventos · "
                f"{consultas_grandes.total:_} consultas · {por_evento_grande:.4f} por evento",
            ],
        )
        assert por_evento_grande < por_evento_pequeno, (
            "a razão consultas/evento não caiu ao multiplicar o volume por dez: as "
            "consultas estão crescendo com os EVENTOS, e não com os lotes (§91)"
        )

    async def test_o_teto_de_evento_nao_muda_a_impressao(self, cenario: dict[str, Any]) -> None:
        """§16, §92. O tamanho do pedaço é detalhe de execução — e por isso ele
        pode ser escolhido por memória, sem mudar o que é publicado."""
        estreito, _m1, _c1 = await _compor(
            cenario,
            nome="perf-det-estreito",
            event_runs=(cenario["eventos_pequenos"].id,),
            event_rows_batch=1_000,
        )
        largo, _m2, _c2 = await _compor(
            cenario,
            nome="perf-det-largo",
            event_runs=(cenario["eventos_pequenos"].id,),
            event_rows_batch=50_000,
        )
        _relatar(
            "PR-04.4.2 · determinismo por teto de evento",
            [
                f"teto  1.000 · {estreito.manifest.counts.events.total:_} eventos",
                f"teto 50.000 · {largo.manifest.counts.events.total:_} eventos",
                f"iguais      · "
                f"{estreito.manifest.corpus_fingerprint == largo.manifest.corpus_fingerprint}",
            ],
        )
        assert estreito.manifest.corpus_fingerprint == largo.manifest.corpus_fingerprint
