"""Do corpus PUBLICADO ao estado reconstruído — PostgreSQL e MinIO reais.

O QUE SÓ ESTE TESTE PROVA (§148 ao §152). Os testes de unidade reconstroem
estado a partir de um `CanonicalMatchStateInput` montado à mão; cada um está
certo, e juntos não provam que a LEITURA existe. Ele passa por:

    a PERTINÊNCIA da versão      `historical_canonical_event_members`, e não o
                                 registro global de eventos
    cinco consultas por LOTE     e nunca cinco por partida
    a família PUBLICADA          que separa «zero cartões» de «sem cobertura»
    o corte TEMPORAL             sobre eventos que vieram do banco, e não de
                                 uma fixture
    a CORREÇÃO                   gravada pelo PR-04.4.1 e projetada pelo
                                 PR-05.1, atravessando os dois

O CENÁRIO é o do PR-04.4.2, de propósito: a mesma partida, os mesmos arquivos,
a mesma composição. Se o estado se reconstrói sobre o corpus que aquele PR
publica, o encaixe entre os dois é o real — e não um que só existe no teste.

O QUE ELE NÃO TEM, e a ausência é o dado: NÃO há escalação publicada. O
cenário do PR-04.4.2 nunca ingeriu `LINEUP`, e por isso o estado que sai daqui
tem placar afirmável e campo indisponível. É exatamente a parcialidade do
§105, acontecendo contra um banco de verdade em vez de num duplo.
"""

from __future__ import annotations

import uuid as _uuid
from collections.abc import AsyncIterator, Sequence
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
from sports_intelligence.adapters.postgres.feature_state import (
    PostgresHistoricalMatchStateSource,
)
from sports_intelligence.adapters.postgres.resolution import (
    PostgresProviderMappingRepository,
)
from sports_intelligence.application.use_cases.events import (
    RunHistoricalEventCanonicalization,
)
from sports_intelligence.application.use_cases.feature_state import (
    BuildHistoricalMatchState,
    BuildHistoricalMatchStates,
)
from sports_intelligence.domain.build.policy import (
    CANONICAL_BUILDER,
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
from sports_intelligence.domain.features.availability import (
    FeatureAvailability,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.state.issues import StateIssueCode
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.players.models import Player
from sports_intelligence.domain.quality.coverage import CoverageFamily, CoverageState
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.quality.runs import QUALITY_ASSESSOR
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.mappings import ProviderEntityMapping
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import NotFoundError
from sports_intelligence.domain.shared.identity import (
    EntityId,
    MatchId,
    PlayerId,
    ProviderId,
    TeamId,
)
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import Period, instant
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
EVENTOS = ProviderId("fonte_de_eventos_do_estado")

AVALIADOR = Actor.service(QUALITY_ASSESSOR)
CONSTRUTOR = Actor.service(CANONICAL_BUILDER)
PUBLICADOR = Actor.service(CORPUS_PUBLISHER)
CANONICALIZADOR = Actor(id="historical-event-canonicalizer", kind=ActorKind.SERVICE)

_REGIME = CompetitionRegime(
    code=RegimeCode.DOUBLE_ROUND_ROBIN,
    effective_from=instant(datetime(1990, 1, 1, tzinfo=UTC)),
    regulation_version="pr052-v1",
)

CASA_NOME = "Ashbourne United"
FORA_NOME = "Wexley Athletic"
REF_DA_PARTIDA = "prov-match-5201"
REF_DA_CASA = "prov-team-5201"
REF_DE_FORA = "prov-team-5202"
REF_DO_ARTILHEIRO = "prov-player-5201"
REF_DO_VISITANTE = "prov-player-5202"

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
    b"Premier League,2024/25,2024-11-09T15:00:00+00:00,"
    b"Ashbourne United,Wexley Athletic,2,1\n"
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

_CABECALHO = (
    b"EventId,MatchRef,Type,Period,Minute,Stoppage,Seq,TeamRef,PlayerRef,"
    b"X,Y,Outcome,BodyPart,XG,CardType,Revision,Supersedes\n"
)

#: A HISTÓRIA CANÔNICA da partida, com tudo que o estado precisa distinguir:
#:
#:     18'  GOL da casa                          1-0
#:     33'  GOL de fora                          1-1
#:     44'  amarelo da casa
#:     58'  VERMELHO de fora
#:     ----------------- corte de referência: 60' -----------------
#:     71'  GOL da casa                          2-1   ← futuro
#:     84'  amarelo de fora                            ← futuro
#:
#: E UMA CORREÇÃO do gol dos 18: o minuto muda para 19. O sucessor substitui o
#: anterior sem apagá-lo, e o placar não muda — é o mesmo gol, e não dois.
FONTE_DE_EVENTOS = _CABECALHO + (
    b"e1,prov-match-5201,goal,FIRST_HALF,18,0,1,prov-team-5201,prov-player-5201,"
    b"0.90,0.50,GOAL,RIGHT_FOOT,0.21,,NEW,\n"
    b"e2,prov-match-5201,goal,FIRST_HALF,33,0,2,prov-team-5202,prov-player-5202,"
    b"0.12,0.44,GOAL,LEFT_FOOT,0.30,,NEW,\n"
    b"e3,prov-match-5201,card,FIRST_HALF,44,0,3,prov-team-5201,prov-player-5201,"
    b",,,,,YELLOW,NEW,\n"
    b"e4,prov-match-5201,card,SECOND_HALF,58,0,1,prov-team-5202,prov-player-5202,"
    b",,,,,RED,NEW,\n"
    b"e5,prov-match-5201,goal,SECOND_HALF,71,0,2,prov-team-5201,prov-player-5201,"
    b"0.85,0.55,GOAL,HEAD,0.44,,NEW,\n"
    b"e6,prov-match-5201,card,SECOND_HALF,84,0,3,prov-team-5202,prov-player-5202,"
    b",,,,,YELLOW,NEW,\n"
    b"e7,prov-match-5201,goal,FIRST_HALF,19,0,1,prov-team-5201,prov-player-5201,"
    b"0.90,0.50,GOAL,RIGHT_FOOT,0.24,,CORRECTION,e1\n"
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
    return EventTypeMapping(
        provider_id=EVENTOS,
        entries={"goal": EventType.GOAL, "card": EventType.CARD},
        version=1,
    )


def _time(nome: str) -> Team:
    return Team(id=TeamId.derive("pr052e2e", nome), canonical_name=nome, country="GB")


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
        id=MatchId.derive("pr052e2e", "ashbourne-wexley"),
        competition_id=liga.id,
        season_id=temporada.id,
        regime=_REGIME,
        stage=Stage(type=StageType.LEAGUE, round_number=12),
        home_team_id=casa.id,
        away_team_id=fora.id,
        scheduled_kickoff=instant(datetime(2024, 11, 9, 15, 0, tzinfo=UTC)),
        lifecycle=MatchLifecycle.RECONCILED,
    )
    jogadores = (
        Player(
            id=PlayerId.derive("pr052e2e", "artilheiro-da-casa"),
            canonical_name="Ivar Lundqvist",
            nationality="GB",
        ),
        Player(
            id=PlayerId.derive("pr052e2e", "artilheiro-visitante"),
            canonical_name="Teodor Rask",
            nationality="SE",
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
        (SubjectType.TEAM, REF_DA_CASA, corpus.teams[0].team.id.value),
        (SubjectType.TEAM, REF_DE_FORA, corpus.teams[1].team.id.value),
        (SubjectType.PLAYER, REF_DO_ARTILHEIRO, corpus.players[0].id.value),
        (SubjectType.PLAYER, REF_DO_VISITANTE, corpus.players[1].id.value),
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
                created_by="pr052-e2e",
            )
        )


async def _registros(pipeline: Pipeline, dataset: Any) -> tuple[HistoricalEventRecord, ...]:
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


@pytest.fixture
async def publicado(database: Database, object_store: Any) -> dict[str, Any]:
    return await montar_corpus_publicado(database, object_store)


async def montar_corpus_publicado(
    database: Database, object_store: Any
) -> dict[str, Any]:
    """Um corpus READY, construído pelo caminho inteiro do PR-04.

    ELA É FUNÇÃO, E NÃO SÓ FIXTURE. O E2E do PR-05.3 precisa do MESMO corpus, e
    importar uma fixture de outro módulo de teste faria o parâmetro de cada
    teste sombrear o símbolo importado — vinte e quatro avisos de linter sobre
    uma redefinição que é legítima. Uma função comum não tem esse problema, e o
    encaixe entre as fases continua sendo provado sobre o mesmo corpus.
    """
    async with database.acquire() as conexao:
        await conexao.execute(f"TRUNCATE {', '.join(TABELAS)} RESTART IDENTITY CASCADE")
    await limpar_execucoes(database)
    corpus = _cenario()
    await seed_corpus(database, corpus)
    await _semear_traducoes(database, corpus)

    pipeline = Pipeline(database, object_store, batch_size=200)
    publico = await pipeline.stage(
        name=f"estado-publico-{_uuid.uuid4().hex[:8]}",
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

    arquivo = await pipeline.stage(
        name=f"estado-eventos-{_uuid.uuid4().hex[:8]}",
        content=FONTE_DE_EVENTOS,
        provider=EVENTOS,
        source_type=SourceType.OPEN_DATA,
        license_class=LicenseClass.PUBLIC_DOMAIN,
    )
    await pipeline.map_source(
        arquivo, provider=EVENTOS, fields=CAMPOS_DE_EVENTO, record_kind=RecordKind.EVENT_RECORD
    )
    registros = await _registros(pipeline, arquivo)

    async def lotes() -> AsyncIterator[Sequence[HistoricalEventRecord]]:
        yield registros

    execucao = await RunHistoricalEventCanonicalization(
        mappings=PostgresProviderMappingRepository(database),
        events=PostgresCanonicalEventWriter(database),
        lineage=PostgresEventBuildRecordRepository(database),
        runs=PostgresCanonicalEventBuildRunRepository(database),
        clock=FrozenClock(pipeline.clock.now()),
        types=_tabela_de_tipos(),
        policy=EventEligibilityPolicy.research(),
        uow=PostgresUnitOfWork(database),
    ).execute(
        actor=CANONICALIZADOR,
        dataset_id=arquivo.id,
        provider_id=EVENTOS,
        batches=lotes(),
        eligible_matches=frozenset({corpus.matches[0].id}),
        license_class=LicenseClass.PUBLIC_DOMAIN,
    )

    contêiner = build_corpus_container(
        database=database, clock=pipeline.clock, audit=pipeline.audit, store=object_store
    )
    dataset = await contêiner.create_dataset.execute(
        actor=PUBLICADOR, name=f"estado-historico-{_uuid.uuid4().hex[:6]}"
    )
    escopo = CorpusScope.of(
        ScopeEntry(
            competition=CompetitionCode.PREMIER_LEAGUE,
            season_label="2024/25",
            competition_id=corpus.competitions[0].id,
            season_id=corpus.seasons[0].id,
        ),
        usage=UsageScope.RESEARCH,
    )
    saida = await contêiner.build_version.execute(
        actor=PUBLICADOR,
        dataset_id=dataset.id,
        version=DatasetVersion(major=1, minor=0),
        scope=escopo,
        inputs=VersionInputs(
            build_run_ids=(pesquisa.run.id,),
            quality_run_ids=(qualidade.run.id,),
            fusion_run_ids=(fusao.run.id,),
            resolution_run_ids=(resolucao.run.id,),
            event_build_run_ids=(execucao.run.id,),
        ),
        quality_run_id=qualidade.run.id,
    )
    versao = await contêiner.publish_version.execute(
        actor=PUBLICADOR, version_id=saida.version.id
    )
    assert versao.status is DatasetVersionStatus.READY

    return {
        "database": database,
        "corpus": contêiner,
        "version": versao,
        "manifest": saida.manifest,
        "match_id": corpus.matches[0].id,
        "home_team_id": corpus.teams[0].team.id,
        "away_team_id": corpus.teams[1].team.id,
        "quality_run": qualidade.run,
        "research_build": pesquisa.run,
        "fusion_run_id": fusao.run.id,
        "resolution_run_ids": [resolucao.run.id],
        "scope": escopo,
        "clock": pipeline.clock,
        "audit": pipeline.audit,
        "store": object_store,
    }


def _origem(publicado: dict[str, Any]) -> CorpusSource:
    """A origem, montada a partir do que a versão DE FATO publicou.

    AS FAMÍLIAS VÊM DA COBERTURA DO MANIFESTO, e não de uma lista escrita à
    mão no teste: `NOT_DECLARED` é o que distingue «não publicamos escalação»
    de «publicamos e não veio», e escrever a lista aqui esconderia justamente
    a distinção que este teste existe para provar.
    """
    manifesto = publicado["manifest"]
    return CorpusSource.of(
        publicado["version"],
        published_families=frozenset(
            CoverageFamily(f.family)
            for f in manifesto.coverage
            if f.state != CoverageState.NOT_DECLARED.value
        ),
    )


def _fonte(publicado: dict[str, Any]) -> PostgresHistoricalMatchStateSource:
    return PostgresHistoricalMatchStateSource(publicado["database"])


def _caso(publicado: dict[str, Any]) -> BuildHistoricalMatchState:
    return BuildHistoricalMatchState(
        source=_fonte(publicado), policy=TemporalAvailabilityPolicy.default()
    )


async def _estado(publicado: dict[str, Any], as_of: FeatureAsOf) -> Any:
    return await _caso(publicado).execute(source_corpus=_origem(publicado), as_of=as_of)


# ============================================================ a leitura ==


class TestALeituraVemDaPertinencia:
    """§78 — a versão publica um recorte, e não o registro global."""

    async def test_a_versao_conhece_a_partida(self, publicado: dict[str, Any]) -> None:
        ids = await _fonte(publicado).match_ids(publicado["version"].id)
        assert list(ids) == [publicado["match_id"]]

    async def test_os_insumos_chegam_tipados(self, publicado: dict[str, Any]) -> None:
        insumos = await _fonte(publicado).load(
            publicado["version"].id, [publicado["match_id"]]
        )
        entrada = insumos[publicado["match_id"]]
        assert entrada.match.id == publicado["match_id"]
        assert entrada.competition_code == CompetitionCode.PREMIER_LEAGUE.value
        assert entrada.season_label == "2024/25"
        assert CoverageFamily.EVENT in entrada.published_families
        # SETE CANDIDATOS, e não seis. O corpus publica o gol corrigido E o
        # sucessor: a correção não apaga o que se sabia antes, e é a projeção
        # do PR-05.1 — e não a leitura — que escolhe qual dos dois é efetivo.
        assert len(entrada.candidate_events) == 7

    async def test_o_resultado_publicado_vem_junto(self, publicado: dict[str, Any]) -> None:
        insumos = await _fonte(publicado).load(
            publicado["version"].id, [publicado["match_id"]]
        )
        resultado = insumos[publicado["match_id"]].result
        assert resultado is not None
        assert (resultado.regular_time.home, resultado.regular_time.away) == (2, 1)

    async def test_uma_partida_fora_da_versao_nao_e_estado_vazio(
        self, publicado: dict[str, Any]
    ) -> None:
        """§113 — «não pertence a este corpus» não é «não teve eventos»."""
        outra = MatchId.derive("pr052e2e", "partida-de-outro-corpus")
        with pytest.raises(NotFoundError):
            await _estado(publicado, FeatureAsOf.at(outra, Period.SECOND_HALF, 60))


# ====================================================== a reconstrução ==


class TestOEstadoNoCorte:
    async def test_o_placar_aos_60_e_o_dos_eventos_ate_ali(
        self, publicado: dict[str, Any]
    ) -> None:
        resultado = await _estado(
            publicado,
            FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, 60),
        )
        estado = resultado.state
        assert (estado.score.home, estado.score.away) == (1, 1)
        assert estado.score.is_available

    async def test_o_gol_dos_71_nao_vaza_para_o_estado_dos_60(
        self, publicado: dict[str, Any]
    ) -> None:
        """§195 contra um banco de verdade."""
        resultado = await _estado(
            publicado, FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, 60)
        )
        assert resultado.state.score.home == 1

    async def test_o_resultado_publicado_nao_alimenta_o_placar(
        self, publicado: dict[str, Any]
    ) -> None:
        """§10 — o 2-1 está no banco, e o estado dos 60' continua 1-1."""
        resultado = await _estado(
            publicado, FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, 60)
        )
        assert (resultado.state.score.home, resultado.state.score.away) == (1, 1)

    async def test_no_apito_final_o_placar_bate_com_o_resultado(
        self, publicado: dict[str, Any]
    ) -> None:
        resultado = await _estado(
            publicado, FeatureAsOf.at(publicado["match_id"], Period.FULL_TIME, 90)
        )
        assert (resultado.state.score.home, resultado.state.score.away) == (2, 1)
        assert StateIssueCode.SCORE_RESULT_MISMATCH not in {
            i.code for i in resultado.issues
        }

    async def test_a_disciplina_conta_o_que_ja_aconteceu(
        self, publicado: dict[str, Any]
    ) -> None:
        resultado = await _estado(
            publicado, FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, 60)
        )
        casa = resultado.state.discipline.team(publicado["home_team_id"])
        fora = resultado.state.discipline.team(publicado["away_team_id"])
        assert casa is not None
        assert fora is not None
        assert (casa.yellow_cards, casa.dismissals) == (1, 0)
        assert (fora.yellow_cards, fora.dismissals) == (0, 1)

    async def test_o_amarelo_dos_84_nao_entra_no_estado_dos_60(
        self, publicado: dict[str, Any]
    ) -> None:
        resultado = await _estado(
            publicado, FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, 60)
        )
        fora = resultado.state.discipline.team(publicado["away_team_id"])
        assert fora is not None
        assert fora.yellow_cards == 0

    async def test_o_pre_jogo_nao_ve_evento_nenhum(self, publicado: dict[str, Any]) -> None:
        resultado = await _estado(
            publicado, FeatureAsOf.pre_match(publicado["match_id"])
        )
        assert resultado.state.events.effective_count == 0
        assert (resultado.state.score.home, resultado.state.score.away) == (0, 0)
        assert resultado.state.score.is_available


class TestACorrecaoAtravessaOsDoisPRs:
    """§151 — gravada pelo PR-04.4.1, projetada pelo PR-05.1."""

    async def test_o_gol_corrigido_conta_uma_vez_so(
        self, publicado: dict[str, Any]
    ) -> None:
        """Sete publicados, quatro efetivos aos 60' — e o placar é 1-1.

        Os quatro: o gol corrigido dos 19, o gol de fora dos 33, o amarelo dos
        44 e o vermelho dos 58. Fora ficam o gol ORIGINAL dos 18 — substituído
        pelo sucessor — e os dois fatos posteriores ao corte.
        """
        resultado = await _estado(
            publicado, FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, 60)
        )
        assert resultado.state.events.effective_count == 4
        assert (resultado.state.score.home, resultado.state.score.away) == (1, 1)

    async def test_o_estado_aponta_o_gol_efetivo_e_nao_o_corrigido(
        self, publicado: dict[str, Any]
    ) -> None:
        resultado = await _estado(
            publicado, FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, 60)
        )
        assert resultado.state.provenance.score.count == 2


class TestAParcialidadeEHonesta:
    """§105 — o corpus deste cenário não publica escalação, e o estado o diz."""

    async def test_sem_escalacao_o_campo_e_indisponivel(
        self, publicado: dict[str, Any]
    ) -> None:
        resultado = await _estado(
            publicado, FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, 60)
        )
        assert not resultado.state.on_field.is_available
        assert StateIssueCode.LINEUP_UNAVAILABLE in {i.code for i in resultado.issues}

    async def test_o_placar_sobrevive_a_falta_de_escalacao(
        self, publicado: dict[str, Any]
    ) -> None:
        """§106 — a degradação é do componente, e não do estado inteiro."""
        resultado = await _estado(
            publicado, FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, 60)
        )
        assert resultado.state.score.is_available
        assert resultado.state.is_partial

    async def test_sem_odds_publicada_o_componente_e_nao_declarado(
        self, publicado: dict[str, Any]
    ) -> None:
        resultado = await _estado(
            publicado, FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, 60)
        )
        assert resultado.state.odds.availability is FeatureAvailability.NOT_DECLARED


class TestAVersaoSemEventosNaoAfirmaPlacar:
    """§14, §40 — a MESMA partida, num corpus que não publica `EVENT`."""

    @pytest.fixture
    async def sem_eventos(self, publicado: dict[str, Any]) -> dict[str, Any]:
        contêiner = publicado["corpus"]
        dataset = await contêiner.create_dataset.execute(
            actor=PUBLICADOR, name=f"sem-eventos-{_uuid.uuid4().hex[:6]}"
        )
        saida = await contêiner.build_version.execute(
            actor=PUBLICADOR,
            dataset_id=dataset.id,
            version=DatasetVersion(major=1, minor=0),
            scope=publicado["scope"],
            inputs=VersionInputs(
                build_run_ids=(publicado["research_build"].id,),
                quality_run_ids=(publicado["quality_run"].id,),
                fusion_run_ids=(publicado["fusion_run_id"],),
                resolution_run_ids=tuple(publicado["resolution_run_ids"]),
                event_build_run_ids=(),
            ),
            quality_run_id=publicado["quality_run"].id,
        )
        versao = await contêiner.publish_version.execute(
            actor=PUBLICADOR, version_id=saida.version.id
        )
        return {**publicado, "version": versao, "manifest": saida.manifest}

    async def test_a_versao_sem_eventos_nao_traz_evento(
        self, sem_eventos: dict[str, Any]
    ) -> None:
        insumos = await _fonte(sem_eventos).load(
            sem_eventos["version"].id, [sem_eventos["match_id"]]
        )
        assert insumos[sem_eventos["match_id"]].candidate_events == ()

    async def test_sem_a_familia_event_o_placar_nao_e_afirmavel(
        self, sem_eventos: dict[str, Any]
    ) -> None:
        resultado = await _estado(
            sem_eventos, FeatureAsOf.at(sem_eventos["match_id"], Period.SECOND_HALF, 60)
        )
        assert not resultado.state.score.is_available
        assert resultado.state.score.availability is FeatureAvailability.NOT_DECLARED
        assert StateIssueCode.INCOMPLETE_EVENT_HISTORY in {
            i.code for i in resultado.issues
        }

    async def test_os_dois_corpus_dao_estados_com_identidades_diferentes(
        self, publicado: dict[str, Any], sem_eventos: dict[str, Any]
    ) -> None:
        """§8 — o corpus faz parte da identidade do estado."""
        alvo = FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, 60)
        com = await _estado(publicado, alvo)
        sem = await _estado(sem_eventos, alvo)
        assert com.state.fingerprint != sem.state.fingerprint


class TestOLote:
    """§162 — o caminho em lote produz o mesmo que o individual."""

    async def test_o_lote_reconstroi_a_partida_da_versao(
        self, publicado: dict[str, Any]
    ) -> None:
        alvo = FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, 60)
        saida = await BuildHistoricalMatchStates(
            source=_fonte(publicado), policy=TemporalAvailabilityPolicy.default()
        ).execute(
            source_corpus=_origem(publicado),
            match_ids=[publicado["match_id"]],
            as_of_of=lambda _: (alvo,),
        )
        assert saida.built == 1
        assert saida.partial == 1
        assert not saida.sample_truncated
        assert saida.states[0].fingerprint == (await _estado(publicado, alvo)).state.fingerprint

    async def test_varios_cortes_da_mesma_partida_sao_varios_estados(
        self, publicado: dict[str, Any]
    ) -> None:
        cortes = tuple(
            FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, m)
            for m in (50, 60, 75)
        )
        saida = await BuildHistoricalMatchStates(
            source=_fonte(publicado), policy=TemporalAvailabilityPolicy.default()
        ).execute(
            source_corpus=_origem(publicado),
            match_ids=[publicado["match_id"]],
            as_of_of=lambda _: cortes,
        )
        assert saida.built == 3
        assert len({e.fingerprint for e in saida.states}) == 3

    async def test_o_lote_agrega_os_problemas_por_codigo(
        self, publicado: dict[str, Any]
    ) -> None:
        saida = await BuildHistoricalMatchStates(
            source=_fonte(publicado), policy=TemporalAvailabilityPolicy.default()
        ).execute(
            source_corpus=_origem(publicado),
            match_ids=[publicado["match_id"]],
            as_of_of=lambda m: (FeatureAsOf.at(m, Period.SECOND_HALF, 60),),
        )
        assert saida.issues_by_code[StateIssueCode.LINEUP_UNAVAILABLE.value] == 1


class TestAReprodutibilidadeSobreOBanco:
    """§196 — o mesmo corpus, o mesmo corte, a mesma impressão."""

    async def test_duas_leituras_produzem_a_mesma_impressao(
        self, publicado: dict[str, Any]
    ) -> None:
        alvo = FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, 60)
        primeira = await _estado(publicado, alvo)
        segunda = await _estado(publicado, alvo)
        assert primeira.state.fingerprint == segunda.state.fingerprint

    async def test_a_politica_entra_na_identidade(
        self, publicado: dict[str, Any]
    ) -> None:
        alvo = FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, 60)
        padrao = await _estado(publicado, alvo)
        estrita = await BuildHistoricalMatchState(
            source=_fonte(publicado),
            policy=TemporalAvailabilityPolicy.strict_observed(),
        ).execute(source_corpus=_origem(publicado), as_of=alvo)
        assert padrao.state.fingerprint != estrita.state.fingerprint
