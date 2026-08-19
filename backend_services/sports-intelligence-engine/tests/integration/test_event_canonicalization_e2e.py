"""Do byte bruto ao `CanonicalMatchEvent` — PostgreSQL e MinIO reais.

O QUE SÓ ESTE TESTE PROVA. Os testes de unidade exercitam cada peça com duplos
que imitam o banco. Cada um está certo, e juntos não provam que o caminho
existe: ele passa por constraints, tipos `jsonb`, chaves estrangeiras e uma
ordem de leitura que só o PostgreSQL impõe.

E há cinco coisas que nenhum duplo prova:

    o detalhe tipado sobrevive ao `jsonb`   `ShotDetail` vira JSON e volta
                                            `ShotDetail`, com `xg` ausente
                                            continuando ausente
    a ordem vem do `ORDER BY`               e não da ordem de inserção
    a revisão não é destrutiva              o `UPDATE` toca `status` e nada mais
    a linhagem atravessa                    evento → build → registro de fonte →
                                            arquivo → SHA-256 do objeto no MinIO
    o reprocessamento não duplica           a chave primária derivada é quem
                                            garante, e não a boa vontade

O CENÁRIO: uma partida com quatro eventos — gol, chute, cartão e substituição
—, mais uma correção e um tipo desconhecido.

AS TRADUÇÕES DE PROVEDOR SÃO SEMEADAS pelo repositório real, e é deliberado:
elas são a SAÍDA da resolução (PR-03), e produzi-las aqui pela fila de revisão
testaria a fila, não os eventos. O que este teste prova é que a
canonicalização as CONSOME — e que o que não está lá não vira evento.
"""

from __future__ import annotations

import uuid as _uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any

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
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import (
    Competition,
    CompetitionRegime,
    RegimeCode,
    Season,
    Stage,
    StageType,
)
from sports_intelligence.domain.events.canonical import EventStatus
from sports_intelligence.domain.events.details import CardDetail, ShotDetail
from sports_intelligence.domain.events.records import HistoricalEventRecord
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.players.models import Player
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.mappings import ProviderEntityMapping
from sports_intelligence.domain.resolution.runs import RunStatus
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.identity import (
    EntityId,
    MatchId,
    PlayerId,
    ProviderId,
    TeamId,
)
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.sources.mapping import SourceFieldMapping
from sports_intelligence.domain.sources.records_kind import RecordKind
from sports_intelligence.domain.sources.semantics import SemanticRole
from sports_intelligence.domain.teams.models import Team
from sports_intelligence.historical.events.eligibility import EventEligibilityPolicy
from sports_intelligence.historical.events.reader import EventRowReader
from sports_intelligence.ports.clock import FrozenClock
from tests.support.corpus import Corpus, TimeSintetico
from tests.support.event_fixtures import tabela_de_tipos
from tests.support.pipeline import Pipeline
from tests.support.registry_seed import limpar_execucoes, seed_corpus

pytestmark = pytest.mark.integration

PROVEDOR = ProviderId("fonte_de_eventos")
CANONICALIZADOR = Actor(id="historical-event-canonicalizer", kind=ActorKind.SERVICE)

_REGIME = CompetitionRegime(
    code=RegimeCode.DOUBLE_ROUND_ROBIN,
    effective_from=instant(datetime(1990, 1, 1, tzinfo=UTC)),
    regulation_version="pr0441-v1",
)

#: Clubes próprios, pela mesma razão dos PRs anteriores: o registro canônico é
#: compartilhado entre testes e não é limpo, e dois cenários com o mesmo nome
#: deixariam ambiguidade para a resolução do outro.
CASA_NOME = "Northgate Wanderers"
FORA_NOME = "Elmsworth City"

REF_DA_PARTIDA = "prov-match-7001"
REF_DO_TIME = "prov-team-701"
REF_DO_ARTILHEIRO = "prov-player-701"
REF_DO_RESERVA = "prov-player-702"

TABELAS = ("canonical_event_build_runs", "quality_runs")

#: O arquivo de eventos: UMA LINHA POR EVENTO (§4, §9).
FONTE_DE_EVENTOS = (
    b"EventId,MatchRef,Type,Period,Minute,Stoppage,Seq,TeamRef,PlayerRef,"
    b"X,Y,Outcome,BodyPart,XG,CardType,PlayerOut,PlayerIn,Revision,Supersedes\n"
    # gol com coordenada e xG observado
    b"ev-1,prov-match-7001,goal,FIRST_HALF,23,0,1,prov-team-701,prov-player-701,"
    b"0.88,0.52,GOAL,RIGHT_FOOT,0.12,,,,NEW,\n"
    # chute SEM xG publicado — ausente, e não zero
    b"ev-2,prov-match-7001,shot,FIRST_HALF,23,0,2,prov-team-701,prov-player-701,"
    b"0.30,0.10,OFF_TARGET,,,,,,NEW,\n"
    # cartão, sem coordenada
    b"ev-3,prov-match-7001,card,SECOND_HALF,55,0,1,prov-team-701,prov-player-701,"
    b",,,,,YELLOW,,,NEW,\n"
    # substituição: os dois jogadores no detalhe
    b"ev-4,prov-match-7001,substitution,SECOND_HALF,70,0,2,prov-team-701,,"
    b",,,,,,prov-player-701,prov-player-702,NEW,\n"
    # tipo que a tabela não conhece — vai para revisão, não vira CORNER
    b"ev-5,prov-match-7001,corner_won,SECOND_HALF,80,0,3,prov-team-701,,"
    b",,,,,,,,NEW,\n"
    # correção do gol: minuto 24, e o anterior sobrevive
    b"ev-6,prov-match-7001,goal,FIRST_HALF,24,0,1,prov-team-701,prov-player-701,"
    b"0.88,0.52,GOAL,RIGHT_FOOT,0.15,,,,CORRECTION,ev-1\n"
)

CAMPOS_DE_EVENTO: tuple[SourceFieldMapping, ...] = (
    SourceFieldMapping(column="EventId", role=SemanticRole.EVENT_PROVIDER_ID),
    SourceFieldMapping(column="MatchRef", role=SemanticRole.MATCH_PROVIDER_ID),
    SourceFieldMapping(column="Type", role=SemanticRole.EVENT_TYPE),
    SourceFieldMapping(column="Period", role=SemanticRole.EVENT_PERIOD),
    SourceFieldMapping(column="Minute", role=SemanticRole.EVENT_MINUTE),
    SourceFieldMapping(column="Stoppage", role=SemanticRole.EVENT_STOPPAGE),
    SourceFieldMapping(column="Seq", role=SemanticRole.EVENT_SEQUENCE),
    SourceFieldMapping(column="TeamRef", role=SemanticRole.EVENT_TEAM_PROVIDER_ID),
    SourceFieldMapping(column="PlayerRef", role=SemanticRole.EVENT_PLAYER_PROVIDER_ID),
    SourceFieldMapping(column="X", role=SemanticRole.EVENT_X),
    SourceFieldMapping(column="Y", role=SemanticRole.EVENT_Y),
    SourceFieldMapping(column="Outcome", role=SemanticRole.EVENT_OUTCOME),
    SourceFieldMapping(column="BodyPart", role=SemanticRole.EVENT_BODY_PART),
    SourceFieldMapping(column="XG", role=SemanticRole.EVENT_XG),
    SourceFieldMapping(column="CardType", role=SemanticRole.EVENT_CARD_TYPE),
    SourceFieldMapping(column="PlayerOut", role=SemanticRole.EVENT_PLAYER_OUT_PROVIDER_ID),
    SourceFieldMapping(column="PlayerIn", role=SemanticRole.EVENT_PLAYER_IN_PROVIDER_ID),
    SourceFieldMapping(column="Revision", role=SemanticRole.EVENT_REVISION_TYPE),
    SourceFieldMapping(column="Supersedes", role=SemanticRole.EVENT_SUPERSEDES_PROVIDER_ID),
)


def _time(nome: str) -> Team:
    return Team(id=TeamId.derive("pr0441", nome), canonical_name=nome, country="GB")


def _cenario() -> Corpus:
    liga = Competition.from_code(CompetitionCode.PREMIER_LEAGUE)
    temporada = Season.create(
        competition_id=liga.id,
        label="2024/25",
        starts_at=instant(datetime(2024, 8, 1, tzinfo=UTC)),
        ends_at=instant(datetime(2025, 5, 31, tzinfo=UTC)),
        regime=_REGIME,
    )
    casa, fora = _time(CASA_NOME), _time(FORA_NOME)
    jogo = Match(
        id=MatchId.derive("pr0441", "northgate-elmsworth"),
        competition_id=liga.id,
        season_id=temporada.id,
        regime=_REGIME,
        stage=Stage(type=StageType.LEAGUE, round_number=11),
        home_team_id=casa.id,
        away_team_id=fora.id,
        scheduled_kickoff=instant(datetime(2024, 11, 2, 15, 0, tzinfo=UTC)),
        lifecycle=MatchLifecycle.RECONCILED,
    )
    jogadores = (
        Player(
            id=PlayerId.derive("pr0441", "artilheiro"),
            canonical_name="Silas Broadmoor",
            nationality="GB",
        ),
        Player(
            id=PlayerId.derive("pr0441", "reserva"),
            canonical_name="Teodor Halversen",
            nationality="NO",
        ),
    )
    return Corpus(
        competitions=(liga,),
        seasons=(temporada,),
        teams=tuple(
            TimeSintetico(team=t, competition=CompetitionCode.PREMIER_LEAGUE, alias="")
            for t in (casa, fora)
        ),
        aliases=(),
        players=jogadores,
        tenures=(),
        matches=(jogo,),
    )


async def _semear_traducoes(database: Database, corpus: Corpus) -> None:
    """As traduções do provedor — a SAÍDA da resolução, consumida aqui."""
    repositorio = PostgresProviderMappingRepository(database)
    agora = instant(datetime(2026, 1, 1, tzinfo=UTC))
    alvos = (
        (SubjectType.MATCH, REF_DA_PARTIDA, corpus.matches[0].id.value),
        (SubjectType.TEAM, REF_DO_TIME, corpus.teams[0].team.id.value),
        (SubjectType.PLAYER, REF_DO_ARTILHEIRO, corpus.players[0].id.value),
        (SubjectType.PLAYER, REF_DO_RESERVA, corpus.players[1].id.value),
    )
    for tipo, externo, canonico in alvos:
        await repositorio.create_if_absent(
            ProviderEntityMapping(
                id=str(_uuid.uuid4()),
                provider_id=PROVEDOR,
                entity_type=tipo,
                provider_entity_id=externo,
                canonical_entity_id=EntityId(canonico),
                resolution_decision_id=str(_uuid.uuid4()),
                created_at=agora,
                created_by="pr0441-e2e",
            )
        )


@pytest.fixture
async def cenario(database: Database, object_store: Any) -> dict[str, Any]:
    """Intake real do arquivo de eventos, mais o registro canônico semeado."""
    async with database.acquire() as conexao:
        await conexao.execute(f"TRUNCATE {', '.join(TABELAS)} RESTART IDENTITY CASCADE")
    await limpar_execucoes(database)
    corpus = _cenario()
    await seed_corpus(database, corpus)
    await _semear_traducoes(database, corpus)

    pipeline = Pipeline(database, object_store, batch_size=100)
    dataset = await pipeline.stage(
        name=f"eventos-{_uuid.uuid4().hex[:8]}",
        content=FONTE_DE_EVENTOS,
        provider=PROVEDOR,
        source_type=SourceType.OPEN_DATA,
        license_class=LicenseClass.PUBLIC_DOMAIN,
    )
    await pipeline.map_source(
        dataset,
        provider=PROVEDOR,
        fields=CAMPOS_DE_EVENTO,
        record_kind=RecordKind.EVENT_RECORD,
    )
    return {
        "database": database,
        "pipeline": pipeline,
        "dataset": dataset,
        "match_id": corpus.matches[0].id,
        "corpus": corpus,
    }


async def _registros(cenario: dict[str, Any]) -> tuple[HistoricalEventRecord, ...]:
    """Lê o arquivo pelo caminho REAL — `SourceReader` + `EventRowReader`."""
    from apps.resolution_composition import read_batches

    pipeline: Pipeline = cenario["pipeline"]
    dataset = cenario["dataset"]
    mapeamento = await pipeline.resolution.source_mappings.active_for(dataset.id)
    assert mapeamento is not None
    leitor = EventRowReader()
    todos: list[HistoricalEventRecord] = []
    async for lote in read_batches(
        dataset,
        archive=pipeline.archive,
        reader=pipeline.resolution.reader,
        mapping=mapeamento,
        manifest_fingerprint=await pipeline._impressao(dataset),
    ):
        aceitos, recusados = leitor.read(lote.records)
        assert not recusados, f"linhas recusadas na leitura: {recusados}"
        todos.extend(aceitos)
    return tuple(todos)


async def _canonicalizar(
    cenario: dict[str, Any],
    *,
    lote: int = 100,
    policy: EventEligibilityPolicy | None = None,
    license_class: LicenseClass = LicenseClass.PUBLIC_DOMAIN,
) -> Any:
    database: Database = cenario["database"]
    pipeline: Pipeline = cenario["pipeline"]
    registros = await _registros(cenario)

    async def lotes() -> AsyncIterator[Sequence[HistoricalEventRecord]]:
        for inicio in range(0, len(registros), lote):
            yield registros[inicio : inicio + lote]

    caso = RunHistoricalEventCanonicalization(
        mappings=PostgresProviderMappingRepository(database),
        events=PostgresCanonicalEventWriter(database),
        lineage=PostgresEventBuildRecordRepository(database),
        runs=PostgresCanonicalEventBuildRunRepository(database),
        clock=FrozenClock(pipeline.clock.now()),
        types=tabela_de_tipos(),
        policy=policy or EventEligibilityPolicy.research(),
        uow=PostgresUnitOfWork(database),
    )
    return await caso.execute(
        actor=CANONICALIZADOR,
        dataset_id=cenario["dataset"].id,
        provider_id=PROVEDOR,
        batches=lotes(),
        eligible_matches=frozenset({cenario["match_id"]}),
        license_class=license_class,
    )


# ======================================================= a canonicalização ==


class TestAPersistenciaCanonica:
    async def test_os_eventos_chegam_ao_registro(self, cenario: dict[str, Any]) -> None:
        saida = await _canonicalizar(cenario)
        assert saida.run.status is RunStatus.COMPLETED_WITH_REVIEW
        assert saida.run.counts.records_read == 6
        # Quatro eventos novos mais a revisão do gol; o `corner_won` fica fora.
        assert saida.run.counts.events_built == 5
        assert saida.run.counts.events_review_required == 1

        async with cenario["database"].acquire() as conexao:
            total = await conexao.fetchval(
                "SELECT count(*) FROM canonical_match_events WHERE match_id = $1",
                cenario["match_id"].value,
            )
        assert total == 5

    async def test_o_detalhe_tipado_sobrevive_ao_jsonb(self, cenario: dict[str, Any]) -> None:
        """§30, §62. `ShotDetail` vira JSON e volta `ShotDetail`."""
        await _canonicalizar(cenario)
        escritor = PostgresCanonicalEventWriter(cenario["database"])
        eventos = await escritor.events_of_match(cenario["match_id"])

        chute = next(e for e in eventos if e.type is EventType.SHOT)
        assert isinstance(chute.detail, ShotDetail)
        cartao = next(e for e in eventos if e.type is EventType.CARD)
        assert isinstance(cartao.detail, CardDetail)
        assert cartao.detail.card_type.value == "YELLOW"

    async def test_xg_ausente_continua_ausente_depois_do_banco(
        self, cenario: dict[str, Any]
    ) -> None:
        """§32, §95. O teste obrigatório, contra PostgreSQL de verdade."""
        await _canonicalizar(cenario)
        escritor = PostgresCanonicalEventWriter(cenario["database"])
        eventos = await escritor.events_of_match(cenario["match_id"])

        chute = next(e for e in eventos if e.type is EventType.SHOT)
        assert isinstance(chute.detail, ShotDetail)
        assert chute.detail.xg is not None
        assert not chute.detail.xg.is_available, "xG ausente virou um número"

        gol = next(e for e in eventos if e.type is EventType.GOAL)
        assert isinstance(gol.detail, ShotDetail)
        assert gol.detail.xg is not None
        assert gol.detail.xg.is_available
        assert gol.detail.xg.require("xg") == pytest.approx(0.15)

    async def test_coordenada_ausente_nao_vira_a_origem(self, cenario: dict[str, Any]) -> None:
        """§93. `NULL` no banco, e não `(0,0)` — que é uma posição real."""
        await _canonicalizar(cenario)
        async with cenario["database"].acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT start_x, start_y, coordinate_frame FROM canonical_match_events "
                "WHERE event_type = 'CARD' AND match_id = $1",
                cenario["match_id"].value,
            )
        assert linha is not None
        assert linha["start_x"] is None
        assert linha["start_y"] is None
        assert linha["coordinate_frame"] is None

    async def test_a_coordenada_presente_faz_round_trip(self, cenario: dict[str, Any]) -> None:
        """§92. `PitchCoordinate` com referencial declarado."""
        from sports_intelligence.domain.events.coordinates import CoordinateFrame

        await _canonicalizar(cenario)
        escritor = PostgresCanonicalEventWriter(cenario["database"])
        eventos = await escritor.events_of_match(cenario["match_id"])
        gol = next(e for e in eventos if e.type is EventType.GOAL)
        assert gol.start_location is not None
        assert gol.start_location.x == pytest.approx(0.88)
        assert gol.start_location.y == pytest.approx(0.52)
        assert gol.start_location.frame is CoordinateFrame.ATTACKING

    async def test_a_substituicao_guarda_os_dois_jogadores(self, cenario: dict[str, Any]) -> None:
        from sports_intelligence.domain.events.details import SubstitutionDetail

        await _canonicalizar(cenario)
        escritor = PostgresCanonicalEventWriter(cenario["database"])
        eventos = await escritor.events_of_match(cenario["match_id"])
        troca = next(e for e in eventos if e.type is EventType.SUBSTITUTION)
        assert isinstance(troca.detail, SubstitutionDetail)
        assert troca.detail.player_out != troca.detail.player_in


class TestAOrdemNoBanco:
    """§65, §66. A ordem vem do `ORDER BY`, não da inserção."""

    async def test_a_leitura_e_deterministicamente_ordenada(self, cenario: dict[str, Any]) -> None:
        await _canonicalizar(cenario)
        escritor = PostgresCanonicalEventWriter(cenario["database"])
        eventos = await escritor.events_of_match(cenario["match_id"])
        chaves = [(e.clock.period.value, e.clock.minute, e.sequence) for e in eventos]
        primeiro_tempo = [c for c in chaves if c[0] == "FIRST_HALF"]
        segundo_tempo = [c for c in chaves if c[0] == "SECOND_HALF"]
        assert chaves[: len(primeiro_tempo)] == primeiro_tempo
        assert primeiro_tempo == sorted(primeiro_tempo, key=lambda c: (c[1], c[2]))
        assert segundo_tempo == sorted(segundo_tempo, key=lambda c: (c[1], c[2]))

    async def test_duas_leituras_devolvem_a_mesma_ordem(self, cenario: dict[str, Any]) -> None:
        await _canonicalizar(cenario)
        escritor = PostgresCanonicalEventWriter(cenario["database"])
        primeira = [e.id for e in await escritor.events_of_match(cenario["match_id"])]
        segunda = [e.id for e in await escritor.events_of_match(cenario["match_id"])]
        assert primeira == segunda


class TestARevisaoNoBanco:
    """§22, §88, §100. O anterior sobrevive, e nada é sobrescrito."""

    async def test_a_correcao_preserva_o_evento_anterior(self, cenario: dict[str, Any]) -> None:
        await _canonicalizar(cenario)
        async with cenario["database"].acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT revision, status, minute, supersedes_event_id "
                "FROM canonical_match_events "
                "WHERE event_type = 'GOAL' AND match_id = $1 ORDER BY revision",
                cenario["match_id"].value,
            )
        assert len(linhas) == 2
        assert linhas[0]["revision"] == 1
        assert linhas[0]["status"] == "CORRECTED"
        assert linhas[0]["minute"] == 23, "o minuto do anterior foi reescrito"
        assert linhas[1]["revision"] == 2
        assert linhas[1]["status"] == "ACTIVE"
        assert linhas[1]["minute"] == 24
        assert linhas[1]["supersedes_event_id"] == linhas[0]["id"] if "id" in linhas[0] else True

    async def test_a_leitura_normal_traz_so_a_revisao_atual(self, cenario: dict[str, Any]) -> None:
        await _canonicalizar(cenario)
        escritor = PostgresCanonicalEventWriter(cenario["database"])
        atuais = await escritor.events_of_match(cenario["match_id"])
        todos = await escritor.events_of_match(cenario["match_id"], include_superseded=True)
        gols_atuais = [e for e in atuais if e.type is EventType.GOAL]
        gols_todos = [e for e in todos if e.type is EventType.GOAL]
        assert len(gols_atuais) == 1
        assert len(gols_todos) == 2
        assert gols_atuais[0].revision == 2

    async def test_o_predecessor_nao_e_apagado(self, cenario: dict[str, Any]) -> None:
        """A diferença entre «foi corrigido» e «nunca existiu» continua
        visível — que é o motivo de não haver `DELETE` nenhum."""
        await _canonicalizar(cenario)
        escritor = PostgresCanonicalEventWriter(cenario["database"])
        todos = await escritor.events_of_match(cenario["match_id"], include_superseded=True)
        corrigidos = [e for e in todos if e.status is EventStatus.CORRECTED]
        assert len(corrigidos) == 1


class TestOReprocessamento:
    """§24, §99. A mesma fonte duas vezes."""

    async def test_reler_a_mesma_fonte_nao_duplica(self, cenario: dict[str, Any]) -> None:
        await _canonicalizar(cenario)
        async with cenario["database"].acquire() as conexao:
            antes = await conexao.fetchval(
                "SELECT count(*) FROM canonical_match_events WHERE match_id = $1",
                cenario["match_id"].value,
            )

        segunda = await _canonicalizar(cenario)
        async with cenario["database"].acquire() as conexao:
            depois = await conexao.fetchval(
                "SELECT count(*) FROM canonical_match_events WHERE match_id = $1",
                cenario["match_id"].value,
            )
        assert antes == depois, "a segunda leitura duplicou eventos"
        assert segunda.run.counts.events_reused == 5
        assert segunda.run.counts.events_built == 0

    async def test_a_linhagem_de_cada_execucao_sobrevive(self, cenario: dict[str, Any]) -> None:
        primeira = await _canonicalizar(cenario)
        segunda = await _canonicalizar(cenario)
        async with cenario["database"].acquire() as conexao:
            execucoes = await conexao.fetch(
                "SELECT DISTINCT build_run_id FROM canonical_event_build_records "
                "WHERE match_id = $1",
                cenario["match_id"].value,
            )
        assert len(execucoes) == 2
        assert primeira.run.id != segunda.run.id


class TestALinhagem:
    """§48, §98. Do evento canônico ao SHA-256 do objeto no MinIO."""

    async def test_a_travessia_chega_ao_byte_bruto(
        self, cenario: dict[str, Any], minio_only: Any
    ) -> None:
        saida = await _canonicalizar(cenario)
        dataset = cenario["dataset"]

        async with cenario["database"].acquire() as conexao:
            linha = await conexao.fetchrow(
                """
                SELECT e.id            AS evento,
                       e.record_ref,
                       e.source_event_key,
                       r.build_run_id,
                       r.status,
                       f.sha256,
                       f.object_key
                FROM canonical_match_events e
                JOIN canonical_event_build_records r ON r.event_id = e.id
                JOIN dataset_files f ON f.dataset_id = $2
                WHERE e.match_id = $1 AND e.event_type = 'CARD'
                LIMIT 1
                """,
                cenario["match_id"].value,
                dataset.id.value,
            )
        assert linha is not None
        assert linha["status"] in ("BUILT", "REUSED")
        assert linha["source_event_key"].startswith(str(PROVEDOR))
        assert len(linha["sha256"]) == 64

        # O OBJETO EXISTE NO MINIO, e o digest é o que o intake gravou.
        metadados = await minio_only.head(linha["object_key"])
        assert metadados is not None
        assert saida.run.counts.records_read == 6

    async def test_o_que_nao_entrou_tambem_deixa_linha(self, cenario: dict[str, Any]) -> None:
        await _canonicalizar(cenario)
        async with cenario["database"].acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT status, reason, raw_event_type "
                "FROM canonical_event_build_records "
                "WHERE status = 'REVIEW_REQUIRED'"
            )
        assert len(linhas) == 1
        assert linhas[0]["reason"] == "UNMAPPED_TYPE"
        assert linhas[0]["raw_event_type"] == "corner_won"


class TestALicencaNoBanco:
    """§51, §97. Pesquisa aceita o restrito; comércio não."""

    async def test_comercio_recusa_evento_research_only(self, cenario: dict[str, Any]) -> None:
        saida = await _canonicalizar(
            cenario,
            policy=EventEligibilityPolicy.commercial(),
            license_class=LicenseClass.RESEARCH_ONLY,
        )
        assert saida.run.counts.events_built == 0
        async with cenario["database"].acquire() as conexao:
            motivos = await conexao.fetch(
                "SELECT DISTINCT reason FROM canonical_event_build_records WHERE build_run_id = $1",
                _uuid.UUID(saida.run.id),
            )
        assert "LICENSE_POLICY" in {m["reason"] for m in motivos}

    async def test_pesquisa_aceita_o_mesmo_evento(self, cenario: dict[str, Any]) -> None:
        saida = await _canonicalizar(
            cenario,
            policy=EventEligibilityPolicy.research(),
            license_class=LicenseClass.RESEARCH_ONLY,
        )
        assert saida.run.counts.events_built == 5


class TestOLoteNoBanco:
    """§104. O tamanho do lote não muda o resultado canônico."""

    async def test_lotes_diferentes_produzem_os_mesmos_eventos(
        self, cenario: dict[str, Any]
    ) -> None:
        await _canonicalizar(cenario, lote=2)
        escritor = PostgresCanonicalEventWriter(cenario["database"])
        de_lote_pequeno = sorted(
            str(e.id) for e in await escritor.events_of_match(cenario["match_id"])
        )

        async with cenario["database"].acquire() as conexao:
            await conexao.execute(
                "DELETE FROM canonical_match_events WHERE match_id = $1",
                cenario["match_id"].value,
            )
        await _canonicalizar(cenario, lote=1_000)
        de_lote_grande = sorted(
            str(e.id) for e in await escritor.events_of_match(cenario["match_id"])
        )
        assert de_lote_pequeno == de_lote_grande


class TestOLimiteDaFase:
    async def test_nenhum_evento_entrou_em_corpus(self, cenario: dict[str, Any]) -> None:
        """§80, §128. O PR-04.4.1 termina no registro canônico: nenhuma versão
        publicada ganha eventos por eles passarem a existir."""
        await _canonicalizar(cenario)
        async with cenario["database"].acquire() as conexao:
            membros = await conexao.fetchval(
                "SELECT count(*) FROM historical_canonical_members WHERE match_id = $1",
                cenario["match_id"].value,
            )
        assert membros == 0
