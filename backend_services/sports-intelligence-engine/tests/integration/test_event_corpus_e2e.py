"""Do byte bruto ao corpus PUBLICADO COM EVENTOS — PostgreSQL e MinIO reais.

O QUE SÓ ESTE TESTE PROVA (PR-04.4.2 §79 ao §82). Os testes de unidade
exercitam a composição de eventos com duplos; cada um está certo, e juntos não
provam que o caminho existe. Ele passa por:

    uma consulta de INTERSEÇÃO      entre o registro canônico de eventos e a
                                    linhagem das execuções declaradas
    chaves estrangeiras COMPOSTAS   o evento só entra se a PARTIDA dele entrou
    um Parquet REAL                 escrito, lido de volta, e conferido coluna
                                    a coluna — inclusive `NULL` contra zero
    um SHA-256 de bytes REAIS       recalculado do objeto no MinIO
    duas licenças                   pesquisa publica o restrito, comércio não

O CENÁRIO: uma partida construída pelo caminho inteiro do PR-04.2, mais dois
arquivos de evento — um público e um `RESEARCH_ONLY` —, mais uma correção.
"""

from __future__ import annotations

import hashlib
import io
import uuid as _uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from apps.build_composition import (
    build_build_container,
    candidate_batches,
    evidence_batches,
    rebuild_fusion_output,
)
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
from sports_intelligence.domain.build.policy import (
    CANONICAL_BUILDER,
    DEFAULT_COMMERCIAL_BUILD_POLICY,
    DEFAULT_RESEARCH_BUILD_POLICY,
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
from sports_intelligence.domain.corpus.scope import CorpusScope, ScopeEntry
from sports_intelligence.domain.corpus.versions import (
    CORPUS_PUBLISHER,
    DatasetVersionStatus,
    VersionInputs,
)
from sports_intelligence.domain.events.records import HistoricalEventRecord
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.events.typing_map import EventTypeMapping
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.players.models import Player
from sports_intelligence.domain.quality.coverage import CoverageFamily, CoverageState
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.quality.runs import QUALITY_ASSESSOR
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.mappings import ProviderEntityMapping
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import (
    EntityId,
    MatchId,
    PlayerId,
    ProviderId,
    TeamId,
)
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.domain.sources.mapping import SourceFieldMapping
from sports_intelligence.domain.sources.records_kind import RecordKind
from sports_intelligence.domain.sources.semantics import SemanticRole
from sports_intelligence.domain.teams.models import Team
from sports_intelligence.historical.events.eligibility import EventEligibilityPolicy
from sports_intelligence.historical.events.reader import EventRowReader
from sports_intelligence.ports.clock import FrozenClock
from tests.support.corpus import Corpus, TimeSintetico
from tests.support.pipeline import Pipeline
from tests.support.registry_seed import limpar_execucoes, seed_corpus

pytestmark = pytest.mark.integration

PUBLICA = ProviderId("fonte_publica")
EVENTOS = ProviderId("fonte_de_eventos_do_corpus")

AVALIADOR = Actor.service(QUALITY_ASSESSOR)
CONSTRUTOR = Actor.service(CANONICAL_BUILDER)
PUBLICADOR = Actor.service(CORPUS_PUBLISHER)
CANONICALIZADOR = Actor(id="historical-event-canonicalizer", kind=ActorKind.SERVICE)

_REGIME = CompetitionRegime(
    code=RegimeCode.DOUBLE_ROUND_ROBIN,
    effective_from=instant(datetime(1990, 1, 1, tzinfo=UTC)),
    regulation_version="pr0442-v1",
)

CASA_NOME = "Harrowfield Rangers"
FORA_NOME = "Castlebrook Town"
REF_DA_PARTIDA = "prov-match-9001"
REF_DO_TIME = "prov-team-901"
REF_DO_ARTILHEIRO = "prov-player-901"

TABELAS: tuple[str, ...] = (
    "historical_canonical_datasets",
    "canonical_event_build_runs",
    "quality_runs",
    "canonical_build_runs",
    "canonical_odds_observations",
    "lineups",
    "match_results",
)

FONTE_PUBLICA = (
    b"Competition,Season,Kickoff,Home,Away,HG,AG\n"
    b"Premier League,2024/25,2024-10-05T14:00:00+00:00,"
    b"Harrowfield Rangers,Castlebrook Town,2,1\n"
)

CAMPOS_PUBLICOS: tuple[SourceFieldMapping, ...] = (
    SourceFieldMapping(column="Competition", role=SemanticRole.COMPETITION_NAME),
    SourceFieldMapping(column="Season", role=SemanticRole.SEASON_LABEL),
    SourceFieldMapping(column="Kickoff", role=SemanticRole.KICKOFF),
    SourceFieldMapping(column="Home", role=SemanticRole.HOME_TEAM_NAME),
    SourceFieldMapping(column="Away", role=SemanticRole.AWAY_TEAM_NAME),
    SourceFieldMapping(column="HG", role=SemanticRole.HOME_SCORE),
    SourceFieldMapping(column="AG", role=SemanticRole.AWAY_SCORE),
)

_CABECALHO_DE_EVENTO = (
    b"EventId,MatchRef,Type,Period,Minute,Stoppage,Seq,TeamRef,PlayerRef,"
    b"X,Y,Outcome,BodyPart,XG,CardType,Revision,Supersedes\n"
)

#: O ARQUIVO PÚBLICO. Ele tem, de propósito:
#:   · um gol com coordenada e xG observado
#:   · um chute SEM xG — ausente, e não zero (§24)
#:   · um chute com xG ZERO — observado, e não ausente (§24)
#:   · um cartão sem coordenada, que NÃO conta no denominador espacial (§27)
#:   · uma correção do gol, que preserva o anterior (§81)
FONTE_DE_EVENTOS_PUBLICA = _CABECALHO_DE_EVENTO + (
    b"ev-1,prov-match-9001,goal,FIRST_HALF,23,0,1,prov-team-901,prov-player-901,"
    b"0.88,0.52,GOAL,RIGHT_FOOT,0.12,,NEW,\n"
    b"ev-2,prov-match-9001,shot,FIRST_HALF,31,0,2,prov-team-901,prov-player-901,"
    b"0.30,0.10,OFF_TARGET,,,,NEW,\n"
    b"ev-3,prov-match-9001,shot,FIRST_HALF,38,0,3,prov-team-901,prov-player-901,"
    b"0.20,0.40,OFF_TARGET,,0,,NEW,\n"
    b"ev-4,prov-match-9001,card,SECOND_HALF,55,0,1,prov-team-901,prov-player-901,"
    b",,,,,YELLOW,NEW,\n"
    b"ev-5,prov-match-9001,goal,FIRST_HALF,24,0,1,prov-team-901,prov-player-901,"
    b"0.88,0.52,GOAL,RIGHT_FOOT,0.15,,CORRECTION,ev-1\n"
)

#: O ARQUIVO RESTRITO. Mesmo formato, licença `RESEARCH_ONLY` — é ele que o
#: corpus comercial NÃO pode publicar (§34, §35, §73).
FONTE_DE_EVENTOS_RESTRITA = _CABECALHO_DE_EVENTO + (
    b"rx-1,prov-match-9001,pass,FIRST_HALF,12,0,1,prov-team-901,prov-player-901,"
    b"0.51,0.33,,,,,NEW,\n"
    b"rx-2,prov-match-9001,tackle,SECOND_HALF,66,0,1,prov-team-901,prov-player-901,"
    b"0.41,0.62,,,,,NEW,\n"
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
    SourceFieldMapping(column="Revision", role=SemanticRole.EVENT_REVISION_TYPE),
    SourceFieldMapping(column="Supersedes", role=SemanticRole.EVENT_SUPERSEDES_PROVIDER_ID),
)


def _tabela_de_tipos() -> EventTypeMapping:
    """A tradução do provedor deste cenário. DECLARADA, nunca heurística.

    Ela é própria e não a do PR-04.4.1 porque o provedor é outro e os tipos
    são outros: `pass` e `tackle` aparecem aqui para que o arquivo restrito
    tenha eventos de verdade — e não eventos recusados por tipo desconhecido,
    que confundiriam a contagem de exclusão por LICENÇA (§37).
    """
    return EventTypeMapping(
        provider_id=EVENTOS,
        entries={
            "goal": EventType.GOAL,
            "shot": EventType.SHOT,
            "card": EventType.CARD,
            "pass": EventType.PASS,
            "tackle": EventType.TACKLE,
        },
        version=1,
    )


def _time(nome: str) -> Team:
    return Team(id=TeamId.derive("pr0442", nome), canonical_name=nome, country="GB")


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
        id=MatchId.derive("pr0442", "harrowfield-castlebrook"),
        competition_id=liga.id,
        season_id=temporada.id,
        regime=_REGIME,
        stage=Stage(type=StageType.LEAGUE, round_number=9),
        home_team_id=casa.id,
        away_team_id=fora.id,
        scheduled_kickoff=instant(datetime(2024, 10, 5, 14, 0, tzinfo=UTC)),
        lifecycle=MatchLifecycle.RECONCILED,
    )
    jogadores = (
        Player(
            id=PlayerId.derive("pr0442", "artilheiro"),
            canonical_name="Aurel Vantoft",
            nationality="GB",
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
    """As traduções do provedor de eventos — a SAÍDA da resolução (PR-03)."""
    repositorio = PostgresProviderMappingRepository(database)
    agora = instant(datetime(2026, 1, 1, tzinfo=UTC))
    alvos = (
        (SubjectType.MATCH, REF_DA_PARTIDA, corpus.matches[0].id.value),
        (SubjectType.TEAM, REF_DO_TIME, corpus.teams[0].team.id.value),
        (SubjectType.PLAYER, REF_DO_ARTILHEIRO, corpus.players[0].id.value),
    )
    for tipo, externo, canonico in alvos:
        await repositorio.create_if_absent(
            ProviderEntityMapping(
                id=str(_uuid.uuid4()),
                provider_id=EVENTOS,
                entity_type=tipo,
                provider_entity_id=externo,
                canonical_entity_id=EntityId(canonico),
                resolution_decision_id=str(_uuid.uuid4()),
                created_at=agora,
                created_by="pr0442-e2e",
            )
        )


async def _registros(pipeline: Pipeline, dataset: Any) -> tuple[HistoricalEventRecord, ...]:
    """Lê o arquivo pelo caminho REAL — `SourceReader` + `EventRowReader`."""
    from apps.resolution_composition import read_batches

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
        assert not recusados, f"linhas recusadas: {recusados}"
        todos.extend(aceitos)
    return tuple(todos)


async def _canonicalizar(
    *,
    database: Database,
    pipeline: Pipeline,
    dataset: Any,
    match_id: MatchId,
    policy: EventEligibilityPolicy,
    license_class: LicenseClass,
) -> Any:
    registros = await _registros(pipeline, dataset)

    async def lotes() -> AsyncIterator[Sequence[HistoricalEventRecord]]:
        yield registros

    caso = RunHistoricalEventCanonicalization(
        mappings=PostgresProviderMappingRepository(database),
        events=PostgresCanonicalEventWriter(database),
        lineage=PostgresEventBuildRecordRepository(database),
        runs=PostgresCanonicalEventBuildRunRepository(database),
        clock=FrozenClock(pipeline.clock.now()),
        types=_tabela_de_tipos(),
        policy=policy,
        uow=PostgresUnitOfWork(database),
    )
    return await caso.execute(
        actor=CANONICALIZADOR,
        dataset_id=dataset.id,
        provider_id=EVENTOS,
        batches=lotes(),
        eligible_matches=frozenset({match_id}),
        license_class=license_class,
    )


@pytest.fixture
async def publicado(database: Database, object_store: Any) -> dict[str, Any]:
    """O caminho INTEIRO: partida construída, eventos canonicalizados.

    NADA É ATALHADO. A partida vem do pipeline do PR-04.2 e os eventos vêm do
    do PR-04.4.1; o que este módulo testa é o encontro dos dois no corpus.
    """
    async with database.acquire() as conexao:
        await conexao.execute(f"TRUNCATE {', '.join(TABELAS)} RESTART IDENTITY CASCADE")
    await limpar_execucoes(database)
    corpus = _cenario()
    await seed_corpus(database, corpus)
    await _semear_traducoes(database, corpus)

    pipeline = Pipeline(database, object_store, batch_size=200)
    publico = await pipeline.stage(
        name=f"publico-{_uuid.uuid4().hex[:8]}",
        content=FONTE_PUBLICA,
        provider=PUBLICA,
        source_type=SourceType.OPEN_DATA,
        license_class=LicenseClass.PUBLIC_DOMAIN,
    )
    await pipeline.map_source(publico, provider=PUBLICA, fields=CAMPOS_PUBLICOS)
    resolucao = await pipeline.resolve(publico.id)
    fusao = await pipeline.fuse([resolucao.run.id])

    build_container = build_build_container(
        database=database,
        resolution=pipeline.resolution,
        clock=pipeline.clock,
        audit=pipeline.audit,
    )
    grupos, candidatos = await rebuild_fusion_output(
        resolution=pipeline.resolution,
        datasets=pipeline.datasets,
        archive=pipeline.archive,
        resolution_run_ids=[resolucao.run.id],
        fusion_run_id=fusao.run.id,
    )
    qualidade = await build_container.run_quality.execute(
        actor=AVALIADOR,
        fusion_run_ids=[fusao.run.id],
        batches=evidence_batches(
            resolution=pipeline.resolution,
            groups=grupos,
            candidates=candidatos,
            resolution_run_ids=[resolucao.run.id],
        ),
    )
    pesquisa = await build_container.build_for(DEFAULT_RESEARCH_BUILD_POLICY).execute(
        actor=CONSTRUTOR,
        quality_run_id=qualidade.run.id,
        batches=candidate_batches(candidates=candidatos),
    )
    comercial = await build_container.build_for(DEFAULT_COMMERCIAL_BUILD_POLICY).execute(
        actor=CONSTRUTOR,
        quality_run_id=qualidade.run.id,
        batches=candidate_batches(candidates=candidatos),
    )

    # ---- os eventos, por dois arquivos com licenças diferentes -------------
    arquivo_publico = await pipeline.stage(
        name=f"eventos-pub-{_uuid.uuid4().hex[:8]}",
        content=FONTE_DE_EVENTOS_PUBLICA,
        provider=EVENTOS,
        source_type=SourceType.OPEN_DATA,
        license_class=LicenseClass.PUBLIC_DOMAIN,
    )
    await pipeline.map_source(
        arquivo_publico,
        provider=EVENTOS,
        fields=CAMPOS_DE_EVENTO,
        record_kind=RecordKind.EVENT_RECORD,
    )
    arquivo_restrito = await pipeline.stage(
        name=f"eventos-res-{_uuid.uuid4().hex[:8]}",
        content=FONTE_DE_EVENTOS_RESTRITA,
        provider=EVENTOS,
        source_type=SourceType.OPEN_DATA,
        license_class=LicenseClass.RESEARCH_ONLY,
    )
    await pipeline.map_source(
        arquivo_restrito,
        provider=EVENTOS,
        fields=CAMPOS_DE_EVENTO,
        record_kind=RecordKind.EVENT_RECORD,
    )

    match_id = corpus.matches[0].id
    evento_publico = await _canonicalizar(
        database=database,
        pipeline=pipeline,
        dataset=arquivo_publico,
        match_id=match_id,
        policy=EventEligibilityPolicy.research(),
        license_class=LicenseClass.PUBLIC_DOMAIN,
    )
    evento_restrito = await _canonicalizar(
        database=database,
        pipeline=pipeline,
        dataset=arquivo_restrito,
        match_id=match_id,
        policy=EventEligibilityPolicy.research(),
        license_class=LicenseClass.RESEARCH_ONLY,
    )
    # A MESMA FONTE PÚBLICA, DE NOVO, SOB A MESMA POLÍTICA DE PESQUISA. É
    # reprocessamento: os ids são derivados, então ela produz os MESMOS
    # eventos — e é o cenário do §68, uma pertinência com duas linhagens.
    evento_publico_de_novo = await _canonicalizar(
        database=database,
        pipeline=pipeline,
        dataset=arquivo_publico,
        match_id=match_id,
        policy=EventEligibilityPolicy.research(),
        license_class=LicenseClass.PUBLIC_DOMAIN,
    )
    # A MESMA FONTE PÚBLICA SOB POLÍTICA COMERCIAL. Ela produz os MESMOS
    # eventos — os ids são derivados —, e é isso que faz o corpus comercial
    # publicar os públicos e nada mais.
    evento_comercial = await _canonicalizar(
        database=database,
        pipeline=pipeline,
        dataset=arquivo_publico,
        match_id=match_id,
        policy=EventEligibilityPolicy.commercial(),
        license_class=LicenseClass.PUBLIC_DOMAIN,
    )
    # E A RESTRITA SOB POLÍTICA COMERCIAL: nenhum evento entra, e a linhagem
    # grava o motivo. É o §37 acontecendo de verdade.
    evento_restrito_comercial = await _canonicalizar(
        database=database,
        pipeline=pipeline,
        dataset=arquivo_restrito,
        match_id=match_id,
        policy=EventEligibilityPolicy.commercial(),
        license_class=LicenseClass.RESEARCH_ONLY,
    )

    corpus_container = build_corpus_container(
        database=database,
        clock=pipeline.clock,
        audit=pipeline.audit,
        store=object_store,
    )
    return {
        "database": database,
        "store": object_store,
        "corpus": corpus_container,
        "quality_run": qualidade.run,
        "research_build": pesquisa.run,
        "commercial_build": comercial.run,
        "event_run_public": evento_publico.run,
        "event_run_public_again": evento_publico_de_novo.run,
        "event_run_restricted": evento_restrito.run,
        "event_run_commercial": evento_comercial.run,
        "event_run_restricted_commercial": evento_restrito_comercial.run,
        "match_id": match_id,
        "competition_id": corpus.competitions[0].id,
        "season_id": corpus.seasons[0].id,
        "fusion_run_id": fusao.run.id,
        "resolution_run_ids": [resolucao.run.id],
        "event_dataset": arquivo_publico,
    }


def _escopo(publicado: dict[str, Any], usage: UsageScope) -> CorpusScope:
    return CorpusScope.of(
        ScopeEntry(
            competition=CompetitionCode.PREMIER_LEAGUE,
            season_label="2024/25",
            competition_id=publicado["competition_id"],
            season_id=publicado["season_id"],
        ),
        usage=usage,
    )


async def _compor(
    publicado: dict[str, Any],
    *,
    version: str = "1.0",
    usage: UsageScope = UsageScope.RESEARCH,
    event_runs: tuple[str, ...] | None = None,
    dataset_name: str = "historical-core",
    batch_size: int | None = None,
    event_rows_batch: int | None = None,
) -> Any:
    contêiner = publicado["corpus"]
    dataset = await contêiner.create_dataset.execute(actor=PUBLICADOR, name=dataset_name)
    build = (
        publicado["research_build"]
        if usage is UsageScope.RESEARCH
        else publicado["commercial_build"]
    )
    if event_runs is None:
        event_runs = (
            (publicado["event_run_public"].id, publicado["event_run_restricted"].id)
            if usage is UsageScope.RESEARCH
            else (
                publicado["event_run_commercial"].id,
                publicado["event_run_restricted_commercial"].id,
            )
        )
    caso = contêiner.build_version
    if batch_size is not None:
        caso = replace(caso, batch_size=batch_size)
    if event_rows_batch is not None:
        caso = replace(caso, event_rows_batch=event_rows_batch)
    maior, _, menor = version.partition(".")
    saida = await caso.execute(
        actor=PUBLICADOR,
        dataset_id=dataset.id,
        version=DatasetVersion(major=int(maior), minor=int(menor)),
        scope=_escopo(publicado, usage),
        inputs=VersionInputs(
            build_run_ids=(build.id,),
            quality_run_ids=(publicado["quality_run"].id,),
            fusion_run_ids=(publicado["fusion_run_id"],),
            resolution_run_ids=tuple(publicado["resolution_run_ids"]),
            event_build_run_ids=event_runs,
        ),
        quality_run_id=publicado["quality_run"].id,
    )
    return dataset, saida


async def _linhas_do_parquet(publicado: dict[str, Any], version_id: str) -> list[dict[str, Any]]:
    """Lê o `events.parquet` DE VOLTA do MinIO. Nada de confiar no que escreveu."""
    import pyarrow.parquet as pq

    contêiner = publicado["corpus"]
    objetos = [
        o
        for o in await contêiner.manifests.objects_of(version_id)
        if o.family == CoverageFamily.EVENT.value
    ]
    linhas: list[dict[str, Any]] = []
    for objeto in objetos:
        bruto = b"".join([p async for p in publicado["store"].open_stream(objeto.object_key)])
        tabela = pq.read_table(io.BytesIO(bruto))
        linhas.extend(tabela.to_pylist())
    return linhas


# ================================================ a pertinência de evento ==


class TestOsEventosEntramNoCorpus:
    async def test_a_versao_de_pesquisa_publica_os_eventos(self, publicado: dict[str, Any]) -> None:
        """§79. O caminho inteiro: arquivo → evento canônico → corpus."""
        _dataset, saida = await _compor(publicado)
        # Cinco linhas no arquivo público: quatro eventos mais a correção (que
        # cria um evento novo e corrige o anterior). Mais dois do restrito.
        assert saida.event_members_written == 7
        assert saida.manifest.counts.events.total == 7
        gravados = await publicado["corpus"].membership.count_event_members(saida.version.id)
        assert gravados == 7

    async def test_a_pertinencia_sobrevive_ao_banco(self, publicado: dict[str, Any]) -> None:
        """§6. Ela é RELIDA, com a linhagem de cada evento."""
        _dataset, saida = await _compor(publicado)
        membros = await publicado["corpus"].membership.event_members_of_match(
            saida.version.id, publicado["match_id"]
        )
        assert len(membros) == 7
        assert all(m.event_build_run_ids for m in membros)
        assert all(len(m.content_digest.value) == 64 for m in membros)

    async def test_uma_versao_sem_execucao_de_evento_nao_publica_eventos(
        self, publicado: dict[str, Any]
    ) -> None:
        """§5, §52. As MESMAS partidas, e nenhum evento. É a diferença que
        derivar pertinência de «a partida está no corpus» apagaria."""
        _dataset, saida = await _compor(publicado, event_runs=())
        assert saida.event_members_written == 0
        assert saida.manifest.counts.events.total == 0
        objetos = await publicado["corpus"].manifests.objects_of(saida.version.id)
        assert not [o for o in objetos if o.family == CoverageFamily.EVENT.value]

    async def test_o_evento_sabe_em_quais_corpus_entrou(self, publicado: dict[str, Any]) -> None:
        """A travessia para frente (§65)."""
        _dataset, saida = await _compor(publicado)
        membros = await publicado["corpus"].membership.event_members_of_match(
            saida.version.id, publicado["match_id"]
        )
        versoes = await publicado["corpus"].membership.versions_containing_event(
            membros[0].event_id
        )
        assert saida.version.id in versoes


# ======================================================== a revisão no corpus ==


class TestARevisaoPublicada:
    async def test_o_predecessor_corrigido_e_o_sucessor_estao_no_corpus(
        self, publicado: dict[str, Any]
    ) -> None:
        """§81. «O que sabíamos antes» continua tendo resposta dentro da
        versão publicada — e não só no registro."""
        _dataset, saida = await _compor(publicado)
        linhas = await _linhas_do_parquet(publicado, saida.version.id)
        por_estado = {linha["status"] for linha in linhas}
        assert "CORRECTED" in por_estado
        assert "ACTIVE" in por_estado
        corrigidos = [linha for linha in linhas if linha["status"] == "CORRECTED"]
        sucessores = [linha for linha in linhas if linha["supersedes_event_id"] is not None]
        assert len(corrigidos) == 1
        assert len(sucessores) == 1
        assert sucessores[0]["supersedes_event_id"] == corrigidos[0]["event_id"]
        assert sucessores[0]["revision"] == 2

    async def test_as_contagens_por_estado_contam_o_que_foi_publicado(
        self, publicado: dict[str, Any]
    ) -> None:
        """§53. Não chamamos de «eventos efetivos» um número que inclui
        predecessores corrigidos — o manifesto conta o que existe."""
        _dataset, saida = await _compor(publicado)
        por_estado = saida.manifest.counts.events.by_status
        assert por_estado["CORRECTED"] == 1
        assert por_estado["ACTIVE"] == 6


# ============================================================ o Parquet ==


class TestOEventsParquet:
    async def test_o_arquivo_existe_e_tem_uma_linha_por_evento(
        self, publicado: dict[str, Any]
    ) -> None:
        """§18, §45. Batch chunks, e nunca um arquivo por evento."""
        _dataset, saida = await _compor(publicado)
        objetos = [
            o
            for o in await publicado["corpus"].manifests.objects_of(saida.version.id)
            if o.family == CoverageFamily.EVENT.value
        ]
        assert len(objetos) == 1
        assert objetos[0].row_count == 7
        assert (
            "family=EVENT/competition=PREMIER_LEAGUE/season=2024%2F25"
            in objetos[0]
            .object_key.replace("/", "%2F")
            .replace("corpus%2F", "corpus/")
            .replace("%2Ffamily=", "/family=")
            or "family=EVENT" in objetos[0].object_key
        )

    async def test_o_sha256_gravado_bate_com_os_bytes_reais(
        self, publicado: dict[str, Any]
    ) -> None:
        """§50. O hash é recalculado dos BYTES do MinIO, e não do que a
        materialização afirmou ter escrito."""
        _dataset, saida = await _compor(publicado)
        objetos = [
            o
            for o in await publicado["corpus"].manifests.objects_of(saida.version.id)
            if o.family == CoverageFamily.EVENT.value
        ]
        for objeto in objetos:
            bruto = b"".join([p async for p in publicado["store"].open_stream(objeto.object_key)])
            assert hashlib.sha256(bruto).hexdigest() == objeto.sha256.value
            assert len(bruto) == objeto.size_bytes

    async def test_coordenada_ausente_e_null_no_arquivo(self, publicado: dict[str, Any]) -> None:
        """§23, §25. O cartão não tem coordenada, e `0.0` seria o canto do
        campo — uma posição perfeitamente válida."""
        _dataset, saida = await _compor(publicado)
        linhas = await _linhas_do_parquet(publicado, saida.version.id)
        cartao = next(linha for linha in linhas if linha["event_type"] == "CARD")
        assert cartao["start_x"] is None
        assert cartao["start_y"] is None
        assert cartao["coordinate_frame"] is None

    async def test_xg_zero_e_xg_ausente_sao_diferentes_no_arquivo(
        self, publicado: dict[str, Any]
    ) -> None:
        """§24. O teste que o §110 pede, feito no arquivo relido."""
        _dataset, saida = await _compor(publicado)
        linhas = await _linhas_do_parquet(publicado, saida.version.id)
        chutes = [linha for linha in linhas if linha["event_type"] == "SHOT"]
        assert len(chutes) == 2
        valores = {linha["xg"] for linha in chutes}
        assert None in valores
        assert 0.0 in valores
        ausente = next(linha for linha in chutes if linha["xg"] is None)
        assert ausente["xg_unavailable_reason"] == "NOT_PUBLISHED"
        medido = next(linha for linha in chutes if linha["xg"] == 0.0)
        assert medido["xg_unavailable_reason"] is None

    async def test_o_detalhe_tipado_volta_como_json_canonico_versionado(
        self, publicado: dict[str, Any]
    ) -> None:
        """§20. Nada de `repr()` de objeto Python dentro do corpus."""
        import json

        _dataset, saida = await _compor(publicado)
        linhas = await _linhas_do_parquet(publicado, saida.version.id)
        cartao = next(linha for linha in linhas if linha["event_type"] == "CARD")
        assert cartao["detail_kind"] == "CARD"
        assert cartao["detail_schema_version"] == "1.0"
        assert json.loads(cartao["detail"])["card_type"] == "YELLOW"

    async def test_o_schema_declara_os_tipos_e_nao_os_infere(
        self, publicado: dict[str, Any]
    ) -> None:
        """§19. Uma coluna toda nula continua sendo do tipo declarado — é o
        defeito que só aparece quando alguém lê dois arquivos juntos."""
        import io as _io

        import pyarrow.parquet as pq

        _dataset, saida = await _compor(publicado)
        objeto = next(
            o
            for o in await publicado["corpus"].manifests.objects_of(saida.version.id)
            if o.family == CoverageFamily.EVENT.value
        )
        bruto = b"".join([p async for p in publicado["store"].open_stream(objeto.object_key)])
        schema = pq.read_schema(_io.BytesIO(bruto))
        assert str(schema.field("minute").type) == "int32"
        assert str(schema.field("start_x").type) == "double"
        assert str(schema.field("xg").type) == "double"
        assert str(schema.field("event_id").type) == "string"


# ==================================================== manifesto e cobertura ==


class TestOManifestoPublicado:
    async def test_as_contagens_de_evento_estao_no_documento(
        self, publicado: dict[str, Any]
    ) -> None:
        """§31."""
        _dataset, saida = await _compor(publicado)
        documento = saida.manifest.as_canonical()
        eventos = dict(documento["counts"])["events"]
        assert eventos["total"] == 7
        assert eventos["by_type"]["GOAL"] == 2
        assert eventos["with_coordinates"] == 6

    async def test_a_cobertura_de_evento_e_espacial_aparecem(
        self, publicado: dict[str, Any]
    ) -> None:
        """§32. E a espacial é MEDIDA, sobre o denominador honesto."""
        _dataset, saida = await _compor(publicado)
        por_familia = {c.family: c for c in saida.manifest.coverage}
        assert por_familia["EVENT"].state == CoverageState.AVAILABILITY_ONLY.value
        assert por_familia["EVENT"].available_total == 7
        assert por_familia["SPATIAL"].state == CoverageState.MEASURED.value
        # Seis eventos espacialmente elegíveis (o cartão não conta), e os seis
        # têm coordenada.
        assert por_familia["SPATIAL"].expected_total == 6
        assert por_familia["SPATIAL"].available_total == 6

    async def test_a_familia_event_aparece_na_licenca(self, publicado: dict[str, Any]) -> None:
        """§33. Um corpus que publica eventos `RESEARCH_ONLY` declara isso."""
        _dataset, saida = await _compor(publicado)
        assert "EVENT" in saida.manifest.license.families_included
        assert "RESEARCH_ONLY" in saida.manifest.license.licenses_present

    async def test_a_procedencia_das_execucoes_de_evento_esta_no_manifesto(
        self, publicado: dict[str, Any]
    ) -> None:
        _dataset, saida = await _compor(publicado)
        forma = saida.manifest.inputs.as_canonical()
        assert len(list(forma["event_build_run_ids"])) == 2
        assert forma["event_policy_versions"] == [1]


# ================================================ pesquisa contra comércio ==


class TestPesquisaContraComercio:
    async def test_o_comercial_nao_publica_os_eventos_restritos(
        self, publicado: dict[str, Any]
    ) -> None:
        """§73. O mesmo arquivo, a mesma partida, dois eventos a menos."""
        _dataset, comercial = await _compor(
            publicado, usage=UsageScope.COMMERCIAL, dataset_name="comercial"
        )
        assert comercial.manifest.counts.events.total == 5

    async def test_o_matchid_e_o_mesmo_e_a_impressao_nao(self, publicado: dict[str, Any]) -> None:
        """§74, §75."""
        _d1, pesquisa = await _compor(publicado, dataset_name="pesquisa")
        _d2, comercial = await _compor(
            publicado, usage=UsageScope.COMMERCIAL, dataset_name="comercial"
        )
        assert pesquisa.manifest.corpus_fingerprint != comercial.manifest.corpus_fingerprint
        de_pesquisa = await publicado["corpus"].membership.page_members(pesquisa.version.id)
        de_comercio = await publicado["corpus"].membership.page_members(comercial.version.id)
        assert [m.match_id for m in de_pesquisa] == [m.match_id for m in de_comercio]

    async def test_a_exclusao_por_licenca_e_explicavel(self, publicado: dict[str, Any]) -> None:
        """§37. `events=0` não explica; «excluído por LICENSE_POLICY, sob
        RESEARCH_ONLY, num build COMMERCIAL» explica."""
        _dataset, comercial = await _compor(
            publicado, usage=UsageScope.COMMERCIAL, dataset_name="comercial"
        )
        licenca = comercial.manifest.license
        assert "EVENT" in licenca.families_excluded
        assert licenca.exclusion_reasons["EVENT"]["LICENSE_POLICY"] == 2
        assert "RESEARCH_ONLY" in licenca.exclusion_licenses["EVENT"]

    async def test_o_match_core_do_comercial_continua_intacto(
        self, publicado: dict[str, Any]
    ) -> None:
        """§78. Excluir EVENT por licença NÃO degrada o núcleo da partida."""
        _dataset, comercial = await _compor(
            publicado, usage=UsageScope.COMMERCIAL, dataset_name="comercial"
        )
        assert comercial.members_written == 1
        assert "MATCH" in comercial.manifest.license.families_included

    async def test_a_cobertura_espacial_pode_diferir_entre_escopos(
        self, publicado: dict[str, Any]
    ) -> None:
        """§77. Se só os restritos tivessem coordenada, as duas coberturas
        seriam diferentes — e isso é correto, não um defeito."""
        _d1, pesquisa = await _compor(publicado, dataset_name="pesquisa")
        _d2, comercial = await _compor(
            publicado, usage=UsageScope.COMMERCIAL, dataset_name="comercial"
        )
        de_pesquisa = next(c for c in pesquisa.manifest.coverage if c.family == "SPATIAL")
        de_comercio = next(c for c in comercial.manifest.coverage if c.family == "SPATIAL")
        assert de_pesquisa.expected_total == 6
        assert de_comercio.expected_total == 4


# ============================================================== o gate ==


class TestOGateComEventos:
    async def test_publica_e_o_corpus_fica_ready(self, publicado: dict[str, Any]) -> None:
        """§51. A reconciliação dos três números passa, e a versão congela."""
        _dataset, saida = await _compor(publicado)
        versao = await publicado["corpus"].publish_version.execute(
            actor=PUBLICADOR, version_id=saida.version.id, reason="publicação com eventos"
        )
        assert versao.status is DatasetVersionStatus.READY

    async def test_a_pertinencia_de_evento_alterada_bloqueia_a_publicacao(
        self, publicado: dict[str, Any]
    ) -> None:
        """§121. Membership contra manifesto: uma discordância aqui significa
        lote perdido, e publicar assim faria a descrição mentir para sempre."""
        _dataset, saida = await _compor(publicado)
        async with publicado["database"].acquire() as conexao:
            await conexao.execute(
                "DELETE FROM historical_canonical_event_members WHERE version_id = $1 "
                "AND event_id = (SELECT event_id FROM historical_canonical_event_members "
                "WHERE version_id = $1 LIMIT 1)",
                _uuid.UUID(saida.version.id),
            )
        with pytest.raises(ValidationError, match="evento"):
            await publicado["corpus"].publish_version.execute(
                actor=PUBLICADOR, version_id=saida.version.id, reason="deveria falhar"
            )

    async def test_manifesto_e_objetos_se_reconciliam(self, publicado: dict[str, Any]) -> None:
        """§49. Nos dois sentidos: todo objeto do manifesto está no banco, e
        todo objeto do banco está no manifesto."""
        _dataset, saida = await _compor(publicado)
        do_banco = {
            o.object_key for o in await publicado["corpus"].manifests.objects_of(saida.version.id)
        }
        do_manifesto = {o.object_key for o in saida.manifest.objects}
        assert do_banco == do_manifesto

    async def test_a_soma_das_linhas_bate_com_o_manifesto(self, publicado: dict[str, Any]) -> None:
        """§51. `manifest.events == Σ row_count == pertinência gravada`."""
        _dataset, saida = await _compor(publicado)
        objetos = [
            o
            for o in await publicado["corpus"].manifests.objects_of(saida.version.id)
            if o.family == CoverageFamily.EVENT.value
        ]
        gravados = await publicado["corpus"].membership.count_event_members(saida.version.id)
        assert sum(o.row_count for o in objetos) == saida.manifest.counts.events.total
        assert gravados == saida.manifest.counts.events.total


# ================================================== determinismo e memória ==


class TestODeterminismo:
    async def test_o_lote_de_evento_nao_muda_a_impressao(self, publicado: dict[str, Any]) -> None:
        """§16. Publicar os mesmos eventos com tetos diferentes de fatiamento
        produz o MESMO corpus."""
        _d1, estreito = await _compor(publicado, event_rows_batch=2, dataset_name="estreito")
        _d2, largo = await _compor(publicado, event_rows_batch=10_000, dataset_name="largo")
        assert estreito.manifest.corpus_fingerprint == largo.manifest.corpus_fingerprint
        assert estreito.manifest.counts.events.total == largo.manifest.counts.events.total

    async def test_o_lote_da_composicao_tambem_nao_muda(self, publicado: dict[str, Any]) -> None:
        _d1, pequeno = await _compor(publicado, batch_size=1, dataset_name="pequeno")
        _d2, grande = await _compor(publicado, batch_size=500, dataset_name="grande")
        assert pequeno.manifest.corpus_fingerprint == grande.manifest.corpus_fingerprint


# ============================================== imutabilidade das versões ==


class TestAsVersoesAntigas:
    async def test_uma_versao_sem_eventos_nao_muda_quando_outra_os_publica(
        self, publicado: dict[str, Any]
    ) -> None:
        """§62, §117, §118. `OldReadyCorpus + NewEventCapability ⇏ Mutation`.

        A versão 1.0 é publicada SEM eventos; a 1.1 os inclui. A primeira
        continua com a mesma impressão, a mesma contagem e o mesmo manifesto —
        e é isso que faz um resultado calculado sobre ela continuar explicável.
        """
        contêiner = publicado["corpus"]
        dataset, sem_eventos = await _compor(
            publicado, version="1.0", event_runs=(), dataset_name="historico"
        )
        primeira = await contêiner.publish_version.execute(
            actor=PUBLICADOR, version_id=sem_eventos.version.id, reason="sem eventos"
        )
        impressao_de_antes = primeira.corpus_fingerprint
        manifesto_de_antes = await contêiner.manifests.by_version(primeira.id)
        assert manifesto_de_antes is not None
        bytes_de_antes = manifesto_de_antes.to_json()

        caso = contêiner.build_version
        segunda = await caso.execute(
            actor=PUBLICADOR,
            dataset_id=dataset.id,
            version=DatasetVersion(major=1, minor=1),
            scope=_escopo(publicado, UsageScope.RESEARCH),
            inputs=VersionInputs(
                build_run_ids=(publicado["research_build"].id,),
                quality_run_ids=(publicado["quality_run"].id,),
                event_build_run_ids=(publicado["event_run_public"].id,),
            ),
            quality_run_id=publicado["quality_run"].id,
        )
        await contêiner.publish_version.execute(
            actor=PUBLICADOR, version_id=segunda.version.id, reason="com eventos"
        )

        relida = await contêiner.datasets.version_by_id(primeira.id)
        assert relida is not None
        assert relida.corpus_fingerprint == impressao_de_antes
        assert await contêiner.membership.count_event_members(primeira.id) == 0
        manifesto_de_agora = await contêiner.manifests.by_version(primeira.id)
        assert manifesto_de_agora is not None
        assert manifesto_de_agora.to_json() == bytes_de_antes
        # E a 1.1 de fato publica eventos — senão o teste passaria por engano.
        assert segunda.manifest.counts.events.total == 5

    async def test_a_versao_com_eventos_supera_a_anterior_sem_apagar(
        self, publicado: dict[str, Any]
    ) -> None:
        """§64. Superada continua legível: um resultado calculado sobre a 1.0
        continua explicável pela 1.0."""
        contêiner = publicado["corpus"]
        dataset, primeira = await _compor(
            publicado, version="1.0", event_runs=(), dataset_name="sucessao"
        )
        await contêiner.publish_version.execute(
            actor=PUBLICADOR, version_id=primeira.version.id, reason="primeira"
        )
        segunda = await contêiner.build_version.execute(
            actor=PUBLICADOR,
            dataset_id=dataset.id,
            version=DatasetVersion(major=1, minor=1),
            scope=_escopo(publicado, UsageScope.RESEARCH),
            inputs=VersionInputs(
                build_run_ids=(publicado["research_build"].id,),
                quality_run_ids=(publicado["quality_run"].id,),
                event_build_run_ids=(publicado["event_run_public"].id,),
            ),
            quality_run_id=publicado["quality_run"].id,
        )
        await contêiner.publish_version.execute(
            actor=PUBLICADOR, version_id=segunda.version.id, reason="segunda"
        )
        anterior = await contêiner.datasets.version_by_id(primeira.version.id)
        assert anterior is not None
        assert anterior.status is DatasetVersionStatus.SUPERSEDED
        assert anterior.status.is_readable_corpus


# =========================================================== a linhagem ==


class TestATravessiaDeLinhagem:
    async def test_do_corpus_ate_o_arquivo_bruto(self, publicado: dict[str, Any]) -> None:
        """§65, §80. `versão → pertinência → evento canônico → linhagem de
        build → registro de fonte → arquivo → SHA-256`.

        NENHUM DEGRAU PODE FALTAR. Uma travessia que para no meio é uma
        auditoria que não termina — e «de onde veio este gol» é exatamente a
        pergunta que o corpus existe para responder.
        """
        _dataset, saida = await _compor(publicado)
        database: Database = publicado["database"]
        membros = await publicado["corpus"].membership.event_members_of_match(
            saida.version.id, publicado["match_id"]
        )
        assert membros
        async with database.acquire() as conexao:
            linha = await conexao.fetchrow(
                """
                SELECT e.id AS event_id, e.match_id, e.source_event_key, e.record_ref,
                       r.build_run_id, r.status,
                       run.dataset_id, f.sha256, f.object_key
                FROM historical_canonical_event_members m
                JOIN canonical_match_events e ON e.id = m.event_id
                JOIN canonical_event_build_records r ON r.event_id = e.id
                JOIN canonical_event_build_runs run ON run.id = r.build_run_id
                JOIN dataset_files f ON f.dataset_id = run.dataset_id
                WHERE m.version_id = $1 AND m.event_id = $2
                LIMIT 1
                """,
                _uuid.UUID(saida.version.id),
                membros[0].event_id,
            )
        assert linha is not None
        assert linha["source_event_key"]
        assert linha["record_ref"]
        assert len(linha["sha256"]) == 64
        bruto = b"".join([p async for p in publicado["store"].open_stream(linha["object_key"])])
        assert hashlib.sha256(bruto).hexdigest() == linha["sha256"]

    async def test_a_linhagem_de_evento_e_plural_quando_duas_execucoes_o_produzem(
        self, publicado: dict[str, Any]
    ) -> None:
        """§66, §68. A execução de pesquisa e a comercial produziram os MESMOS
        eventos públicos — ids derivados. Uma pertinência, duas linhagens."""
        _dataset, saida = await _compor(
            publicado,
            event_runs=(
                publicado["event_run_public"].id,
                publicado["event_run_public_again"].id,
            ),
        )
        membros = await publicado["corpus"].membership.event_members_of_match(
            saida.version.id, publicado["match_id"]
        )
        assert saida.event_members_written == 5
        assert all(len(m.event_build_run_ids) == 2 for m in membros)


# ============================================================= o conflito ==


class TestOConflitoDeEvento:
    async def test_o_registro_recusa_outro_conteudo_sob_a_mesma_identidade(
        self, publicado: dict[str, Any]
    ) -> None:
        """§69, §115. A identidade canônica diz «é o mesmo evento» e o conteúdo
        diz que não. Sobrescrever escolheria qual história é verdade."""
        database: Database = publicado["database"]
        escritor = PostgresCanonicalEventWriter(database)
        async with database.acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT id FROM canonical_match_events WHERE match_id = $1 LIMIT 1",
                publicado["match_id"].value,
            )
        assert linha is not None
        gravados = await escritor.events_of_match(publicado["match_id"], include_superseded=True)
        original = next(e for e in gravados if e.id == linha["id"])
        divergente = replace(original, clock=replace(original.clock, minute=99))
        with pytest.raises(ConflictError, match="outro conteúdo"):
            await escritor.persist_events(
                [divergente],
                build_run_id=publicado["event_run_public"].id,
                source_keys={divergente.id: "conflito"},
            )

    async def test_reescrever_o_mesmo_conteudo_continua_idempotente(
        self, publicado: dict[str, Any]
    ) -> None:
        """A guarda recusa CONFLITO, e não reprocessamento — que é o caso
        comum e precisa continuar barato."""
        database: Database = publicado["database"]
        escritor = PostgresCanonicalEventWriter(database)
        gravados = await escritor.events_of_match(publicado["match_id"], include_superseded=True)
        desfechos = await escritor.persist_events(
            list(gravados[:2]),
            build_run_id=publicado["event_run_public"].id,
            source_keys={e.id: "reprocessamento" for e in gravados[:2]},
        )
        assert all(d.value == "REUSED" for d in desfechos.values())


# ================================================= o limite deste PR ==


class TestOLimiteDoPR05:
    async def test_nada_aqui_calcula_feature(self, publicado: dict[str, Any]) -> None:
        """§3, §119. O corpus publica xG OBSERVADO; xG calculado é feature
        derivada, tem versão de modelo e mora no PR-05."""
        _dataset, saida = await _compor(publicado)
        linhas = await _linhas_do_parquet(publicado, saida.version.id)
        colunas = set(linhas[0])
        proibidas = {
            "xg_model_version",
            "shots_last_5m",
            "pressure",
            "field_tilt",
            "event_rate",
            "embedding",
        }
        assert not (colunas & proibidas)
        assert "xg" in colunas  # o observado, esse sim
