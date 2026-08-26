"""O benchmark da canonicalização de eventos — 100 mil registros.

POR QUE A ESCALA É OUTRA (§70). Uma temporada tem 380 partidas e centenas de
MILHARES de eventos: a ordem de grandeza do fluxo de eventos é três vezes a do
fluxo de partidas, e um desenho que aguenta dez mil partidas pode não aguentar
o mesmo número de eventos por partida.

O QUE ELE MEDE (§107):

    registros lidos, eventos construídos, pulados e em revisão
    duração e eventos por segundo
    pico de memória
    consultas, e como elas escalam
    o tamanho do lote

O CRITÉRIO É O CRESCIMENTO, e não um número absoluto. Uma máquina mais lenta
muda os segundos; o que reprovaria é o pipeline consultar por EVENTO em vez de
por lote — e a diferença entre as duas curvas é grande demais para ser ruído.

O CENÁRIO É SINTÉTICO E DETERMINÍSTICO. Ele não passa pelo intake porque o que
se mede aqui é a CANONICALIZAÇÃO: incluir a leitura de CSV mediria o leitor do
PR-02, que já tem benchmark próprio. A escrita é no PostgreSQL de verdade.
"""

from __future__ import annotations

import uuid as _uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any, Final

import pytest

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
from sports_intelligence.domain.events.records import (
    HistoricalEventRecord,
    RawEventClock,
    RawEventPoint,
)
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.mappings import ProviderEntityMapping
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.identity import (
    DatasetId,
    EntityId,
    ProviderId,
)
from sports_intelligence.domain.shared.provenance import LicenseClass
from sports_intelligence.domain.shared.temporal import Period, instant
from sports_intelligence.domain.sources.records import DatasetRecordRef
from sports_intelligence.historical.events.eligibility import EventEligibilityPolicy
from sports_intelligence.ports.clock import FrozenClock
from tests.performance.test_resolution_100k import _relatar
from tests.support.corpus import Corpus
from tests.support.instrumentation import contando_consultas, medindo

pytestmark = [pytest.mark.performance, pytest.mark.integration]

#: O volume do §106. Cem mil registros de evento — o que uma temporada de uma
#: liga grande de fato tem quando a fonte publica evento a evento.
REGISTROS: Final[int] = 100_000

#: Os lotes do §110. O default sai daqui, e não do maior throughput sozinho.
LOTES: Final[tuple[int, ...]] = (250, 1_000, 5_000)

#: O teto do custo marginal por registro, em bytes. O índice de revisão retém
#: uma chave de origem e um par `(id, revisão)`; o evento canônico inteiro
#: custa mais de 1 KB. O teto fica entre os dois, perto do primeiro — é ele
#: que transforma «acumulou o evento» em falha de teste, e não em um pico que
#: só aparece em produção.
TETO_MARGINAL_B: Final[float] = 400.0

PROVEDOR: Final[ProviderId] = ProviderId("perf_eventos")
CANONICALIZADOR = Actor(id="historical-event-canonicalizer", kind=ActorKind.SERVICE)

#: Quantas partidas o cenário usa. Cem mil eventos em duzentas partidas dá
#: quinhentos por partida — a ordem de grandeza real de um provedor de eventos.
PARTIDAS: Final[int] = 200
JOGADORES_POR_TIME: Final[int] = 22

#: Os tipos do cenário, na proporção aproximada de um jogo real: muito passe,
#: alguns chutes, poucos cartões.
_TIPOS: Final[tuple[tuple[str, int], ...]] = (
    ("pass", 70),
    ("shot", 15),
    ("card", 8),
    ("goal", 7),
)


def _sorteio(indice: int) -> str:
    """O tipo do evento `n`, determinístico e sem `random`.

    SEM SORTEIO DE VERDADE: duas execuções do benchmark que gerem cenários
    diferentes não são comparáveis, e a comparação entre execuções é a única
    coisa que um número de throughput permite fazer.
    """
    posicao = indice % 100
    acumulado = 0
    for tipo, peso in _TIPOS:
        acumulado += peso
        if posicao < acumulado:
            return tipo
    return "pass"


def _registro(n: int, *, dataset: DatasetId, arquivo: str) -> HistoricalEventRecord:
    partida = n % PARTIDAS
    tipo = _sorteio(n)
    minuto = (n // 7) % 90
    return HistoricalEventRecord(
        record_ref=DatasetRecordRef(dataset_id=dataset, file_id=arquivo, record_number=n + 2),
        provider_id=PROVEDOR,
        match_reference=f"perf-match-{partida}",
        raw_type=tipo,
        clock=RawEventClock(
            period=Period.FIRST_HALF if minuto < 45 else Period.SECOND_HALF,
            minute=minuto,
        ),
        provider_event_id=f"perf-ev-{n}",
        sequence=n,
        team_reference=f"perf-team-{partida % 20}",
        player_reference=f"perf-player-{n % JOGADORES_POR_TIME}",
        start_point=RawEventPoint(x=_fracao(n), y=_fracao(n * 7 + 3)),
        details=(
            {"EVENT_OUTCOME": "GOAL" if tipo == "goal" else "SAVED", "EVENT_XG": "0.07"}
            if tipo in ("goal", "shot")
            else {"EVENT_CARD_TYPE": "YELLOW"}
            if tipo == "card"
            else {}
        ),
    )


def _fracao(n: int) -> Any:
    from decimal import Decimal

    return Decimal(n % 100) / Decimal(100)


def _tabela() -> Any:
    from sports_intelligence.domain.events.taxonomy import EventType
    from sports_intelligence.domain.events.typing_map import EventTypeMapping

    return EventTypeMapping(
        provider_id=PROVEDOR,
        entries={
            "pass": EventType.PASS,
            "shot": EventType.SHOT,
            "card": EventType.CARD,
            "goal": EventType.GOAL,
        },
    )


@pytest.fixture
async def cenario(banco_semeado: Database, corpus: Corpus) -> dict[str, Any]:
    """O registro canônico do benchmark, mais as traduções do provedor."""
    partidas = corpus.matches[:PARTIDAS]
    times = [t.team for t in corpus.teams[:20]]
    jogadores = corpus.players[:JOGADORES_POR_TIME]
    assert len(partidas) == PARTIDAS
    assert len(times) == 20
    assert len(jogadores) == JOGADORES_POR_TIME

    dataset_id = await _registrar_dataset(banco_semeado)
    repositorio = PostgresProviderMappingRepository(banco_semeado)
    agora = instant(datetime(2026, 1, 1, tzinfo=UTC))

    async with banco_semeado.acquire() as conexao:
        await conexao.execute(
            "DELETE FROM provider_entity_mappings WHERE provider_id = $1",
            str(PROVEDOR),
        )
    for n, partida in enumerate(partidas):
        await repositorio.create_if_absent(
            _mapeamento(SubjectType.MATCH, f"perf-match-{n}", partida.id.value, agora)
        )
    for n, time in enumerate(times):
        await repositorio.create_if_absent(
            _mapeamento(SubjectType.TEAM, f"perf-team-{n}", time.id.value, agora)
        )
    for n, jogador in enumerate(jogadores):
        await repositorio.create_if_absent(
            _mapeamento(SubjectType.PLAYER, f"perf-player-{n}", jogador.id.value, agora)
        )

    return {
        "database": banco_semeado,
        "dataset_id": dataset_id,
        "elegiveis": frozenset(p.id for p in partidas),
        "arquivo": str(DatasetId.derive("perf", "arquivo-de-eventos")),
    }


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
        created_by="pr0441-perf",
    )


async def _registrar_dataset(banco: Database) -> DatasetId:
    """Um dataset mínimo, só para a chave estrangeira da execução.

    ELE NÃO TEM ARQUIVO, e não precisa ter: o benchmark gera os registros em
    memória. O que a execução exige é um `dataset_id` que exista.
    """
    identificador = DatasetId.derive("perf", "eventos")
    async with banco.acquire() as conexao:
        await conexao.execute(
            """
            INSERT INTO datasets (
                id, name, version_major, version_minor, lifecycle,
                declared_competitions, declared_seasons, created_at, created_by,
                updated_at
            )
            VALUES ($1, 'perf-eventos', 1, 0, 'STAGED', '{PERF}', '{2024}', now(),
                    'pr0441-perf', now())
            ON CONFLICT (id) DO NOTHING
            """,
            identificador.value,
        )
    return identificador


def _caso(banco: Database, *, lote: int) -> RunHistoricalEventCanonicalization:
    return RunHistoricalEventCanonicalization(
        mappings=PostgresProviderMappingRepository(banco),
        events=PostgresCanonicalEventWriter(banco),
        lineage=PostgresEventBuildRecordRepository(banco),
        runs=PostgresCanonicalEventBuildRunRepository(banco),
        clock=FrozenClock(instant(datetime(2026, 8, 18, 12, 0, tzinfo=UTC))),
        types=_tabela(),
        policy=EventEligibilityPolicy.research(),
        uow=PostgresUnitOfWork(banco),
    )


async def _rodar(cenario: dict[str, Any], *, quantos: int, lote: int) -> Any:
    dataset_id = cenario["dataset_id"]
    arquivo = cenario["arquivo"]

    async def lotes() -> AsyncIterator[Sequence[HistoricalEventRecord]]:
        """GERADOR, e não lista (§69). Cem mil registros materializados de uma
        vez seriam o pico que o §109 proíbe — e o `yield` é o que garante que
        eles não são, não uma promessa em comentário."""
        acumulado: list[HistoricalEventRecord] = []
        for n in range(quantos):
            acumulado.append(_registro(n, dataset=dataset_id, arquivo=arquivo))
            if len(acumulado) >= lote:
                yield acumulado
                acumulado = []
        if acumulado:
            yield acumulado

    return await _caso(cenario["database"], lote=lote).execute(
        actor=CANONICALIZADOR,
        dataset_id=dataset_id,
        provider_id=PROVEDOR,
        batches=lotes(),
        eligible_matches=cenario["elegiveis"],
        license_class=LicenseClass.PUBLIC_DOMAIN,
    )


async def _limpar_eventos(banco: Database) -> None:
    async with banco.acquire() as conexao:
        await conexao.execute("TRUNCATE canonical_event_build_runs CASCADE")


class TestEventosEmVolume:
    async def test_cem_mil_registros_de_evento(self, cenario: dict[str, Any]) -> None:
        await _limpar_eventos(cenario["database"])
        lote = 1_000

        async with contando_consultas(cenario["database"]) as consultas:
            with medindo("canonicalização de eventos") as medida:
                saida = await _rodar(cenario, quantos=REGISTROS, lote=lote)

        contagens = saida.run.counts
        lotes = max(1, -(-REGISTROS // lote))
        _relatar(
            f"PR-04.4.1 · {REGISTROS:_} registros de evento",
            [
                f"duração          {medida.segundos:.1f}s · "
                f"{medida.por_segundo(max(contagens.events_built, 1)):.0f} eventos/s · "
                f"pico {medida.pico_mb:.0f} MB",
                "",
                f"lidos            {contagens.records_read:_}",
                f"construídos      {contagens.events_built:_}",
                f"reusados         {contagens.events_reused:_}",
                f"pulados          {contagens.events_skipped:_}",
                f"em revisão       {contagens.events_review_required:_}",
                f"falhos           {contagens.events_failed:_}",
                "",
                f"lote             {lote} · {lotes} lote(s)",
                f"consultas        {consultas.total:_} "
                f"({consultas.total / lotes:.1f} por lote, "
                f"{consultas.total / REGISTROS:.4f} por registro)",
                f"alvos            {consultas.mais_frequentes}",
                "",
                f"execução         {saida.run.status.value}",
            ],
        )

        assert contagens.records_read == REGISTROS
        assert contagens.events_built > 0
        contagens.assert_consistent()

        # O CRITÉRIO DO §108: as consultas por REGISTRO precisam ser uma
        # fração pequena. Com N+1 seriam >= 1 por registro — cem mil eventos
        # dariam cem mil consultas, e não algumas centenas.
        por_registro = consultas.total / REGISTROS
        assert por_registro < 0.05, (
            f"{consultas.total} consultas para {REGISTROS} registros "
            f"({por_registro:.4f} por registro): a canonicalização está "
            "consultando por evento, não por lote (§68, §108)"
        )

    async def test_as_consultas_escalam_por_lote(self, cenario: dict[str, Any]) -> None:
        """§108. Dez mil e cem mil registros, com o MESMO lote.

        As consultas precisam crescer proporcionalmente ao NÚMERO DE LOTES. Se
        crescessem com os registros, a razão por registro ficaria constante em
        vez de cair — e é a razão que denuncia o N+1.
        """
        medidas: dict[int, tuple[int, float]] = {}
        for quantos in (10_000, 100_000):
            await _limpar_eventos(cenario["database"])
            async with contando_consultas(cenario["database"]) as consultas:
                await _rodar(cenario, quantos=quantos, lote=1_000)
            medidas[quantos] = (consultas.total, consultas.total / quantos)

        _relatar(
            "PR-04.4.1 · escalonamento de consultas · lote 1.000",
            [
                f"{quantos:_} registros · {total:_} consultas · {razao:.4f} por registro"
                for quantos, (total, razao) in medidas.items()
            ],
        )
        assert medidas[100_000][1] <= medidas[10_000][1] * 1.2, (
            "a razão consultas/registro não caiu ao aumentar o volume: as "
            "consultas estão crescendo com os REGISTROS, não com os lotes"
        )

    async def test_o_custo_marginal_por_registro_e_do_indice(self, cenario: dict[str, Any]) -> None:
        """§109. O que cresce com o VOLUME é o índice de revisão — e só ele.

        O PICO NÃO É CONSTANTE NO VOLUME, e afirmar que seria é que estaria
        errado. A execução mantém UM índice `chave de origem → (id, revisão)`
        que atravessa lotes de propósito: uma correção pode referenciar
        qualquer evento anterior da mesma execução, e resolvê-la indo ao banco
        por linha é o N+1 que o §68 proíbe. Esse índice é O(chaves distintas),
        por construção.

        O QUE O TESTE MEDE, ENTÃO, É O CUSTO MARGINAL DE CADA REGISTRO —
        quantos bytes o processo retém a mais por registro adicional. É esse
        número que distingue as duas situações que importam:

            ~200 a 300 B/registro   só a referência está retida (correto)
            >1 KB/registro        o `CanonicalMatchEvent` inteiro voltou a
                                  ser acumulado, com procedência, relógio,
                                  coordenadas e detalhes tipados (regressão)

        A independência em relação ao TAMANHO DO LOTE — que é a outra metade
        do §109 — é provada em `test_os_tres_tamanhos_de_lote`.
        """
        picos: dict[int, float] = {}
        for quantos in (10_000, 100_000):
            await _limpar_eventos(cenario["database"])
            with medindo(f"canonicalização de {quantos}") as medida:
                await _rodar(cenario, quantos=quantos, lote=1_000)
            picos[quantos] = medida.pico_mb

        marginal = (picos[100_000] - picos[10_000]) * 1024 * 1024 / (100_000 - 10_000)
        _relatar(
            "PR-04.4.1 · memória por volume · lote 1.000",
            [
                *(f"{quantos:_} registros → pico {pico:.1f} MB" for quantos, pico in picos.items()),
                f"marginal        {marginal:.0f} B por registro (teto {TETO_MARGINAL_B:.0f} B)",
            ],
        )
        assert marginal < TETO_MARGINAL_B, (
            f"cada registro adicional retém {marginal:.0f} B, acima do teto de "
            f"{TETO_MARGINAL_B:.0f} B. O índice de revisão guarda um par "
            "`(id, revisão)` por chave; um custo desta ordem significa que o "
            "evento canônico inteiro voltou a ser retido — e aí o pico passa a "
            "seguir o volume do arquivo, não o lote (§69, §109)"
        )

    async def test_os_tres_tamanhos_de_lote(self, cenario: dict[str, Any]) -> None:
        """§110. 250, 1.000 e 5.000 — e o default sai desta tabela.

        NÃO SE ESCOLHE PELO MAIOR THROUGHPUT SOZINHO: o lote grande é mais
        rápido e o pico sobe com ele, e um default escolhido só pelo tempo
        troca memória por segundos sem que ninguém tenha decidido isso.
        """
        volume = 20_000
        linhas: list[str] = []
        resultados: dict[int, tuple[float, float, int]] = {}
        for lote in LOTES:
            await _limpar_eventos(cenario["database"])
            async with contando_consultas(cenario["database"]) as consultas:
                with medindo(f"lote {lote}") as medida:
                    saida = await _rodar(cenario, quantos=volume, lote=lote)
            resultados[lote] = (medida.segundos, medida.pico_mb, consultas.total)
            linhas.append(
                f"lote {lote:>5} · {medida.segundos:5.1f}s · "
                f"pico {medida.pico_mb:5.1f} MB · {consultas.total:_} consultas · "
                f"{saida.run.counts.events_built:_} eventos"
            )

        _relatar(f"PR-04.4.1 · tamanho de lote · {volume:_} registros", linhas)

        # AS CONSULTAS CAEM COM O LOTE. É a prova direta de que elas são por
        # lote: mais registros no mesmo lote não custam mais consultas.
        assert resultados[5_000][2] < resultados[250][2]

    async def test_o_lote_nao_muda_o_resultado_canonico(self, cenario: dict[str, Any]) -> None:
        """§104, em volume. Mesmos eventos, qualquer que seja o lote."""
        volume = 5_000
        assinaturas: list[list[str]] = []
        for lote in (250, 5_000):
            await _limpar_eventos(cenario["database"])
            await _rodar(cenario, quantos=volume, lote=lote)
            async with cenario["database"].acquire() as conexao:
                linhas = await conexao.fetch(
                    "SELECT id::text FROM canonical_match_events ORDER BY id"
                )
            assinaturas.append([linha["id"] for linha in linhas])

        _relatar(
            "PR-04.4.1 · determinismo por lote",
            [
                f"lote   250 · {len(assinaturas[0]):_} eventos",
                f"lote 5.000 · {len(assinaturas[1]):_} eventos",
                f"iguais     · {assinaturas[0] == assinaturas[1]}",
            ],
        )
        assert assinaturas[0] == assinaturas[1]
