"""Do byte bruto ao corpus PUBLICADO — contra PostgreSQL e MinIO reais.

O QUE SÓ ESTE TESTE PROVA. Os testes de unidade do PR-04.3 exercitam a
composição com duplos que imitam o banco. Cada um está certo, e juntos não
provam que o caminho existe: a composição é uma CONSULTA DE INTERSEÇÃO entre o
registro canônico e a linhagem de build, e ela só existe em SQL.

E há cinco coisas que nenhum duplo prova:

    a interseção volta o que o build autorizou   e não «tudo que está no
                                                 registro», que é global
    a pertinência é gravada e relida             com famílias em `text[]` e
                                                 as FKs para avaliação e build
    a impressão sobrevive ao ida-e-volta         os fatos relidos do banco
                                                 produzem a MESMA impressão
    o gate confere contra o BANCO                não contra o que a composição
                                                 disse ter feito
    a travessia fecha                            corpus → membro → build →
                                                 avaliação → fusão → arquivo

O CENÁRIO É O DO PR-04.2 (§103), reaproveitado de propósito: o corpus é
composto pelo que aquele build produziu, e um cenário próprio testaria uma
integração que não existe.
"""

from __future__ import annotations

import json
import uuid as _uuid
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
from sports_intelligence.adapters.postgres.database import Database
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
from sports_intelligence.domain.corpus.fingerprint import (
    FINGERPRINT_ALGORITHM,
    FINGERPRINT_SCHEMA_VERSION,
)
from sports_intelligence.domain.corpus.scope import CorpusScope, ScopeEntry
from sports_intelligence.domain.corpus.versions import (
    CORPUS_PUBLISHER,
    DatasetVersionStatus,
    VersionInputs,
)
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.quality.runs import QUALITY_ASSESSOR
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.mappings import EntityAlias
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import MatchId, ProviderId, TeamId
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.domain.sources.mapping import SourceFieldMapping
from sports_intelligence.domain.sources.semantics import SemanticRole
from sports_intelligence.domain.teams.models import Team
from sports_intelligence.ingestion.normalization.names import NameNormalizer
from tests.support.corpus import Corpus, TimeSintetico
from tests.support.pipeline import Pipeline
from tests.support.registry_seed import limpar_execucoes, seed_corpus

pytestmark = pytest.mark.integration

PUBLICA = ProviderId("fonte_publica")
RESTRITA = ProviderId("fonte_restrita")

AVALIADOR = Actor.service(QUALITY_ASSESSOR)
CONSTRUTOR = Actor.service(CANONICAL_BUILDER)
PUBLICADOR = Actor.service(CORPUS_PUBLISHER)

_NORMALIZADOR = NameNormalizer()
_REGIME = CompetitionRegime(
    code=RegimeCode.DOUBLE_ROUND_ROBIN,
    effective_from=instant(datetime(1990, 1, 1, tzinfo=UTC)),
    regulation_version="pr043-v1",
)

#: As tabelas que uma execução do PR-04.3 suja, mais as do PR-04.2 que ela
#: consome. A ordem não importa — `CASCADE` resolve —, mas a LISTA importa: a
#: composição lê linhagem de build, e um resto de execução anterior faria o
#: corpus conter partidas de outro teste.
TABELAS: tuple[str, ...] = (
    "historical_canonical_datasets",
    "quality_runs",
    "canonical_build_runs",
    "canonical_odds_observations",
    "lineups",
    "match_results",
)

#: O TEMPO DO CENÁRIO. Clubes próprios, pelo mesmo motivo do PR-04.2: o
#: registro canônico é compartilhado entre testes e não é limpo, então dois
#: cenários com o mesmo nome deixariam ambiguidade para a resolução do outro.
CASA_NOME = "Blackmoor Athletic"
FORA_NOME = "Wendholm United"


def _time(nome: str) -> Team:
    return Team(id=TeamId.derive("pr043", nome), canonical_name=nome, country="GB")


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
        id=MatchId.derive("pr043", "blackmoor-wendholm"),
        competition_id=liga.id,
        season_id=temporada.id,
        regime=_REGIME,
        stage=Stage(type=StageType.LEAGUE, round_number=7),
        home_team_id=casa.id,
        away_team_id=fora.id,
        scheduled_kickoff=instant(datetime(2024, 9, 21, 14, 0, tzinfo=UTC)),
        lifecycle=MatchLifecycle.RECONCILED,
    )
    return Corpus(
        competitions=(liga,),
        seasons=(temporada,),
        teams=tuple(
            TimeSintetico(team=t, competition=CompetitionCode.PREMIER_LEAGUE, alias="")
            for t in (casa, fora)
        ),
        aliases=(
            EntityAlias(
                id=str(TeamId.derive("pr043-alias", "blackmoor")),
                entity_type=SubjectType.TEAM,
                entity_id=casa.id,
                alias_original="Blackmoor Ath",
                alias_normalized=_NORMALIZADOR.normalize("Blackmoor Ath"),
                normalizer_version=_NORMALIZADOR.version,
                created_at=instant(datetime(2026, 1, 1, tzinfo=UTC)),
                created_by="pr043",
            ),
        ),
        players=(),
        tenures=(),
        matches=(jogo,),
    )


_CAMPOS_BASE: tuple[SourceFieldMapping, ...] = (
    SourceFieldMapping(column="Competition", role=SemanticRole.COMPETITION_NAME),
    SourceFieldMapping(column="Season", role=SemanticRole.SEASON_LABEL),
    SourceFieldMapping(column="Kickoff", role=SemanticRole.KICKOFF),
    SourceFieldMapping(column="Home", role=SemanticRole.HOME_TEAM_NAME),
    SourceFieldMapping(column="Away", role=SemanticRole.AWAY_TEAM_NAME),
)
CAMPOS_PUBLICOS: tuple[SourceFieldMapping, ...] = (
    *_CAMPOS_BASE,
    SourceFieldMapping(column="HG", role=SemanticRole.HOME_SCORE),
    SourceFieldMapping(column="AG", role=SemanticRole.AWAY_SCORE),
)
CAMPOS_DE_ODDS: tuple[SourceFieldMapping, ...] = (
    *_CAMPOS_BASE,
    SourceFieldMapping(column="Book", role=SemanticRole.BOOKMAKER_NAME),
    SourceFieldMapping(column="OddsH", role=SemanticRole.ODDS_HOME),
    SourceFieldMapping(column="OddsD", role=SemanticRole.ODDS_DRAW),
    SourceFieldMapping(column="OddsA", role=SemanticRole.ODDS_AWAY),
)

FONTE_PUBLICA = (
    b"Competition,Season,Kickoff,Home,Away,HG,AG\n"
    b"Premier League,2024/25,2024-09-21T14:00:00+00:00,"
    b"Blackmoor Ath,Wendholm United,3,0\n"
)

FONTE_DE_ODDS = (
    b"Competition,Season,Kickoff,Home,Away,Book,OddsH,OddsD,OddsA\n"
    b"Premier League,2024/25,2024-09-21T14:00:00+00:00,Blackmoor Athletic,"
    b"Wendholm United,BET365,1.80,3.60,4.20\n"
    b"Premier League,2024/25,2024-09-21T14:00:00+00:00,Blackmoor Athletic,"
    b"Wendholm United,PINNACLE,1.85,3.55,4.10\n"
)


@pytest.fixture
async def publicado(database: Database, object_store: Any) -> dict[str, Any]:
    """O caminho INTEIRO: bruto → resolução → fusão → qualidade → build →
    corpus composto. Nada é atalhado, e é o que faz este teste falhar quando
    uma constraint quebra.
    """
    async with database.acquire() as conexao:
        await conexao.execute(f"TRUNCATE {', '.join(TABELAS)} RESTART IDENTITY CASCADE")
    await limpar_execucoes(database)
    corpus = _cenario()
    await seed_corpus(database, corpus)

    pipeline = Pipeline(database, object_store, batch_size=200)
    publico = await pipeline.stage(
        name=f"publico-{_uuid.uuid4().hex[:8]}",
        content=FONTE_PUBLICA,
        provider=PUBLICA,
        source_type=SourceType.OPEN_DATA,
        license_class=LicenseClass.PUBLIC_DOMAIN,
    )
    await pipeline.map_source(publico, provider=PUBLICA, fields=CAMPOS_PUBLICOS)
    restrito = await pipeline.stage(
        name=f"restrito-{_uuid.uuid4().hex[:8]}",
        content=FONTE_DE_ODDS,
        provider=RESTRITA,
        source_type=SourceType.OPEN_DATA,
        license_class=LicenseClass.RESEARCH_ONLY,
    )
    await pipeline.map_source(restrito, provider=RESTRITA, fields=CAMPOS_DE_ODDS)

    r1 = await pipeline.resolve(publico.id)
    r2 = await pipeline.resolve(restrito.id)
    run_ids = [r1.run.id, r2.run.id]
    fusao = await pipeline.fuse(run_ids)

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
        resolution_run_ids=run_ids,
        fusion_run_id=fusao.run.id,
    )
    qualidade = await build_container.run_quality.execute(
        actor=AVALIADOR,
        fusion_run_ids=[fusao.run.id],
        batches=evidence_batches(
            resolution=pipeline.resolution,
            groups=grupos,
            candidates=candidatos,
            resolution_run_ids=run_ids,
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
    # UM SEGUNDO BUILD DE PESQUISA, sobre a MESMA avaliação e a mesma política.
    # Ele é o caso A do §24: dois builds que afirmam exatamente o mesmo. No
    # PR-04.3 o `DISTINCT ON` escolheria um deles e a linhagem do outro sumiria.
    segunda_pesquisa = await build_container.build_for(DEFAULT_RESEARCH_BUILD_POLICY).execute(
        actor=CONSTRUTOR,
        quality_run_id=qualidade.run.id,
        batches=candidate_batches(candidates=candidatos),
    )

    corpus_container = build_corpus_container(
        database=database,
        clock=pipeline.clock,
        audit=pipeline.audit,
        store=object_store,
    )
    return {
        "database": database,
        "corpus": corpus_container,
        "quality_run": qualidade.run,
        "research_build": pesquisa.run,
        "second_research_build": segunda_pesquisa.run,
        "commercial_build": comercial.run,
        "match_id": corpus.matches[0].id,
        "competition_id": corpus.competitions[0].id,
        "season_id": corpus.seasons[0].id,
        "fusion_run_id": fusao.run.id,
        "resolution_run_ids": run_ids,
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


def _entradas(publicado: dict[str, Any], *build_runs: Any) -> VersionInputs:
    build_run = build_runs[0]
    return VersionInputs(
        build_run_ids=tuple(b.id for b in build_runs),
        quality_run_ids=(publicado["quality_run"].id,),
        build_output_fingerprints=(
            () if build_run.output_fingerprint is None else (build_run.output_fingerprint,)
        ),
        fusion_run_ids=(publicado["fusion_run_id"],),
        resolution_run_ids=tuple(publicado["resolution_run_ids"]),
    )


async def _compor(
    publicado: dict[str, Any],
    *,
    version: str = "1.0",
    usage: UsageScope = UsageScope.RESEARCH,
    build_runs: tuple[Any, ...] = (),
    dataset_name: str = "historical-core",
    batch_size: int | None = None,
) -> Any:
    contêiner = publicado["corpus"]
    dataset = await contêiner.create_dataset.execute(actor=PUBLICADOR, name=dataset_name)
    execucoes = build_runs or (publicado["research_build"],)
    caso = contêiner.build_version
    if batch_size is not None:
        from dataclasses import replace

        caso = replace(caso, batch_size=batch_size)
    maior, _, menor = version.partition(".")
    saida = await caso.execute(
        actor=PUBLICADOR,
        dataset_id=dataset.id,
        version=DatasetVersion(major=int(maior), minor=int(menor)),
        scope=_escopo(publicado, usage),
        inputs=_entradas(publicado, *execucoes),
        quality_run_id=publicado["quality_run"].id,
    )
    return dataset, saida


# =========================================================== a composição ==


class TestAComposicao:
    async def test_a_interseccao_traz_o_que_o_build_autorizou(
        self, publicado: dict[str, Any]
    ) -> None:
        """A pergunta não é «o que está no registro» — ele é global e contém
        também o que outro build escreveu."""
        _dataset, saida = await _compor(publicado)
        assert saida.members_written == 1
        assert saida.version.status is DatasetVersionStatus.VALIDATING

        membros = await publicado["corpus"].membership.page_members(saida.version.id)
        assert len(membros) == 1
        membro = membros[0]
        assert membro.match_id == publicado["match_id"]
        # O BUILD DE PESQUISA INCLUI AS ODDS (ADR-0025).
        assert CoverageFamily.ODDS in membro.included_families
        assert CoverageFamily.MATCH in membro.included_families

    async def test_a_pertinencia_sobrevive_ao_banco(self, publicado: dict[str, Any]) -> None:
        """As famílias vão como `text[]` e voltam como enum; a linhagem vai
        como FK e volta como id. Um duplo não prova nenhum dos dois."""
        _dataset, saida = await _compor(publicado)
        async with publicado["database"].acquire() as conexao:
            linha = await conexao.fetchrow(
                """
                SELECT included_families, content_fingerprint, competition_code,
                       season_label
                FROM historical_canonical_members WHERE version_id = $1
                """,
                _uuid.UUID(saida.version.id),
            )
            # A LINHAGEM MORA NA TABELA-FILHA desde o PR-04.3.1: um membro pode
            # ter várias contribuições, e uma coluna só guardaria uma delas.
            contribuicoes = await conexao.fetch(
                """
                SELECT build_run_id, quality_assessment_id, included_families
                FROM historical_canonical_member_builds WHERE version_id = $1
                """,
                _uuid.UUID(saida.version.id),
            )
        assert linha is not None
        assert set(linha["included_families"]) == {"MATCH", "ODDS"}
        assert len(linha["content_fingerprint"]) == 64
        assert linha["competition_code"] == "PREMIER_LEAGUE"
        assert linha["season_label"] == "2024/25"
        assert len(contribuicoes) == 1
        assert str(contribuicoes[0]["build_run_id"]) == publicado["research_build"].id
        assert set(contribuicoes[0]["included_families"]) == {"MATCH", "ODDS"}

    async def test_o_lote_nao_muda_a_impressao(self, publicado: dict[str, Any]) -> None:
        """§88, agora contra o banco: a paginação por chave e a impressão
        comutativa juntas.

        A MESMA IDENTIDADE NAS DUAS COMPOSIÇÕES, e é o que torna a comparação
        válida: nome de dataset e versão ENTRAM na impressão (§30), então
        compor sob dois nomes diferentes produziria impressões diferentes por
        um motivo que não é o tamanho do lote. A primeira versão é apagada
        antes da segunda — é a única forma de reusar `1.0`, e o índice único
        do §64 é justamente o que impede o contrário.
        """
        dataset, pequeno = await _compor(publicado, batch_size=1)
        async with publicado["database"].acquire() as conexao:
            await conexao.execute(
                "DELETE FROM historical_canonical_dataset_versions WHERE id = $1",
                _uuid.UUID(pequeno.version.id),
            )
        mesmo, grande = await _compor(publicado, batch_size=500)
        assert pequeno.manifest.corpus_fingerprint == grande.manifest.corpus_fingerprint
        assert mesmo.id == dataset.id

    async def test_pesquisa_e_comercio_produzem_corpus_diferentes(
        self, publicado: dict[str, Any]
    ) -> None:
        """ADR-0025 ponta a ponta: a MESMA avaliação, dois corpus, a mesma
        identidade de partida — e o comercial sem as odds restritas."""
        _d1, pesquisa = await _compor(publicado, dataset_name="corpus-pesquisa")
        _d2, comercial = await _compor(
            publicado,
            dataset_name="corpus-comercial",
            usage=UsageScope.COMMERCIAL,
            build_runs=(publicado["commercial_build"],),
        )
        assert pesquisa.manifest.corpus_fingerprint != comercial.manifest.corpus_fingerprint
        assert pesquisa.manifest.counts.matches == comercial.manifest.counts.matches

        membros_comerciais = await publicado["corpus"].membership.page_members(comercial.version.id)
        assert CoverageFamily.ODDS not in membros_comerciais[0].included_families
        # E a IDENTIDADE é a mesma nos dois — o que muda é o conteúdo.
        membros_de_pesquisa = await publicado["corpus"].membership.page_members(pesquisa.version.id)
        assert membros_comerciais[0].match_id == membros_de_pesquisa[0].match_id

    async def test_o_manifesto_comercial_registra_a_exclusao_com_a_licenca(
        self, publicado: dict[str, Any]
    ) -> None:
        """§26. «ODDS excluída por LICENSE_POLICY, RESEARCH_ONLY, num build
        COMMERCIAL» é a pergunta que uma auditoria jurídica de fato faz."""
        _d, comercial = await _compor(
            publicado,
            dataset_name="corpus-auditavel",
            usage=UsageScope.COMMERCIAL,
            build_runs=(publicado["commercial_build"],),
        )
        licenca = comercial.manifest.license
        assert "ODDS" in licenca.families_excluded
        assert licenca.exclusion_licenses["ODDS"] == LicenseClass.RESEARCH_ONLY.value

        # AS DUAS LISTAS, E É AQUI QUE A FRONTEIRA DO PR-04.2.1 APARECE.
        # A fonte restrita também AFIRMA o kickoff — que é FATO e não rótulo
        # (ADR-0025, emenda) —, então ela alimentou a família MATCH e aparece
        # em `licenses_present`. O que torna o corpus comercialmente
        # publicável é a fonte de domínio público sustentar o núcleo SOZINHA,
        # e é isso que `independent_support` diz.
        assert LicenseClass.RESEARCH_ONLY.value in licenca.licenses_present
        assert LicenseClass.PUBLIC_DOMAIN.value in licenca.independent_support


# ================================================================= o gate ==


class TestOGate:
    async def test_publica_e_o_corpus_fica_ready(self, publicado: dict[str, Any]) -> None:
        _dataset, saida = await _compor(publicado)
        versao = await publicado["corpus"].publish_version.execute(
            actor=PUBLICADOR,
            version_id=saida.version.id,
            reason="corpus histórico 1.0 — E2E",
        )
        assert versao.status is DatasetVersionStatus.READY
        assert versao.manifest_id is not None
        assert versao.corpus_fingerprint == saida.manifest.corpus_fingerprint

        # E O ESTADO CHEGOU AO BANCO — não só ao objeto devolvido.
        async with publicado["database"].acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT status, match_count, corpus_fingerprint, manifest_id "
                "FROM historical_canonical_dataset_versions WHERE id = $1",
                _uuid.UUID(versao.id),
            )
        assert linha is not None
        assert linha["status"] == "READY"
        assert linha["match_count"] == 1
        assert linha["manifest_id"] is not None

    async def test_o_manifesto_gravado_e_o_documento_inteiro(
        self, publicado: dict[str, Any]
    ) -> None:
        """§18. O manifesto é a descrição COMPLETA — escopo, contagens,
        cobertura, qualidade, licença e linhagem, tudo num documento só."""
        _dataset, saida = await _compor(publicado)
        await publicado["corpus"].publish_version.execute(
            actor=PUBLICADOR, version_id=saida.version.id, reason="publicação"
        )
        async with publicado["database"].acquire() as conexao:
            bruto = await conexao.fetchval(
                "SELECT document FROM historical_canonical_manifests WHERE version_id = $1",
                _uuid.UUID(saida.version.id),
            )
        documento = json.loads(bruto) if isinstance(bruto, str) else dict(bruto)
        for secao in (
            "scope",
            "inputs",
            "counts",
            "coverage",
            "quality",
            "license",
            "issues",
            "corpus_fingerprint",
        ):
            assert secao in documento, secao
        assert documento["inputs"]["build_run_ids"] == [publicado["research_build"].id]
        assert documento["counts"]["matches"] == 1

    async def test_o_manifesto_relido_bate_com_o_gravado(self, publicado: dict[str, Any]) -> None:
        """A ida e a volta pelo `jsonb` não podem mudar a impressão — se
        mudassem, comparar dois corpus deixaria de valer."""
        _dataset, saida = await _compor(publicado)
        await publicado["corpus"].publish_version.execute(
            actor=PUBLICADOR, version_id=saida.version.id, reason="publicação"
        )
        relido = await publicado["corpus"].manifests.by_version(saida.version.id)
        assert relido is not None
        assert relido.corpus_fingerprint == saida.manifest.corpus_fingerprint
        assert relido.counts.matches == saida.manifest.counts.matches
        assert relido.scope.usage is saida.manifest.scope.usage

    async def test_a_segunda_publicacao_da_mesma_versao_e_recusada(
        self, publicado: dict[str, Any]
    ) -> None:
        """§84. A serialização é do BANCO — `UPDATE ... WHERE status = $n`."""
        _dataset, saida = await _compor(publicado)
        await publicado["corpus"].publish_version.execute(
            actor=PUBLICADOR, version_id=saida.version.id, reason="primeira"
        )
        with pytest.raises(ConflictError):
            await publicado["corpus"].publish_version.execute(
                actor=PUBLICADOR, version_id=saida.version.id, reason="segunda"
            )

    async def test_a_conferencia_le_o_banco_e_nao_o_que_lhe_contaram(
        self, publicado: dict[str, Any]
    ) -> None:
        """§67. Apagar uma linha de pertinência por fora tem de reprovar a
        publicação — é para isso que a contagem é lida do banco."""
        _dataset, saida = await _compor(publicado)
        async with publicado["database"].acquire() as conexao:
            await conexao.execute(
                "DELETE FROM historical_canonical_members WHERE version_id = $1",
                _uuid.UUID(saida.version.id),
            )
        with pytest.raises(ValidationError, match="partida"):
            await publicado["corpus"].publish_version.execute(
                actor=PUBLICADOR, version_id=saida.version.id, reason="tentativa"
            )

    async def test_impressao_divergente_bloqueia_a_publicacao(
        self, publicado: dict[str, Any]
    ) -> None:
        """§98. Se a impressão gravada na versão não bate com a do manifesto,
        o conteúdo mudou entre compor e publicar — e o que seria publicado não
        é o que foi conferido."""
        _dataset, saida = await _compor(publicado)
        async with publicado["database"].acquire() as conexao:
            await conexao.execute(
                "UPDATE historical_canonical_dataset_versions "
                "SET corpus_fingerprint = $2 WHERE id = $1",
                _uuid.UUID(saida.version.id),
                "0" * 64,
            )
        with pytest.raises(ValidationError, match="impressão"):
            await publicado["corpus"].publish_version.execute(
                actor=PUBLICADOR, version_id=saida.version.id, reason="tentativa"
            )

    async def test_o_manifesto_declara_qual_construcao_produziu_a_impressao(
        self, publicado: dict[str, Any]
    ) -> None:
        """§62. Sem o nome do algoritmo, duas impressões incomparáveis passam
        por comparáveis."""
        _dataset, saida = await _compor(publicado)
        await publicado["corpus"].publish_version.execute(
            actor=PUBLICADOR, version_id=saida.version.id, reason="publicação"
        )
        async with publicado["database"].acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT fingerprint_algorithm, fingerprint_schema_version, document "
                "FROM historical_canonical_manifests WHERE version_id = $1",
                _uuid.UUID(saida.version.id),
            )
        assert linha is not None
        assert linha["fingerprint_algorithm"] == FINGERPRINT_ALGORITHM
        assert linha["fingerprint_schema_version"] == FINGERPRINT_SCHEMA_VERSION
        documento = (
            json.loads(linha["document"])
            if isinstance(linha["document"], str)
            else dict(linha["document"])
        )
        assert documento["fingerprint_algorithm"] == FINGERPRINT_ALGORITHM

    async def test_a_versao_repetida_e_recusada_pelo_indice(
        self, publicado: dict[str, Any]
    ) -> None:
        """§64. «1.0» precisa significar um conteúdo só — e quem arbitra é o
        índice único, não uma consulta-antes-de-inserir."""
        dataset, _saida = await _compor(publicado)
        contêiner = publicado["corpus"]
        with pytest.raises(ConflictError):
            await contêiner.build_version.execute(
                actor=PUBLICADOR,
                dataset_id=dataset.id,
                version=DatasetVersion(major=1, minor=0),
                scope=_escopo(publicado, UsageScope.RESEARCH),
                inputs=_entradas(publicado, publicado["research_build"]),
            )


# ====================================================== composição multi-build ==


class TestComposicaoMultiBuild:
    """Os casos do PR-04.3.1 contra PostgreSQL real (§34, §36, §94)."""

    async def test_caso_a_builds_equivalentes_produzem_um_membro_e_duas_linhagens(
        self, publicado: dict[str, Any]
    ) -> None:
        """§34. Dois builds, os mesmos fatos: UM membro, DUAS linhagens.

        É o teste que o PR-04.3 não podia passar: com `DISTINCT ON`, a
        contribuição do build mais antigo não chegava sequer a ser lida.
        """
        _dataset, saida = await _compor(
            publicado,
            build_runs=(
                publicado["research_build"],
                publicado["second_research_build"],
            ),
        )
        assert saida.members_written == 1

        membros = await publicado["corpus"].membership.page_members(saida.version.id)
        assert len(membros) == 1
        assert set(membros[0].build_run_ids) == {
            publicado["research_build"].id,
            publicado["second_research_build"].id,
        }

        async with publicado["database"].acquire() as conexao:
            contribuicoes = await conexao.fetch(
                "SELECT build_run_id, quality_assessment_id, included_families "
                "FROM historical_canonical_member_builds WHERE version_id = $1 "
                "ORDER BY build_run_id",
                _uuid.UUID(saida.version.id),
            )
        assert len(contribuicoes) == 2
        for linha in contribuicoes:
            assert set(linha["included_families"]) == {"MATCH", "ODDS"}

    async def test_a_impressao_nao_muda_por_ter_vindo_de_dois_builds(
        self, publicado: dict[str, Any]
    ) -> None:
        """A linhagem não é conteúdo: os MESMOS fatos, produzidos por um build
        ou por dois, são o mesmo corpus (§31)."""
        _d1, de_um = await _compor(publicado, dataset_name="de-um-build")
        _d2, de_dois = await _compor(
            publicado,
            dataset_name="de-dois-builds",
            build_runs=(
                publicado["research_build"],
                publicado["second_research_build"],
            ),
        )
        assert de_um.manifest.corpus_fingerprint == de_dois.manifest.corpus_fingerprint

    async def test_a_ordem_dos_builds_nao_muda_o_resultado(self, publicado: dict[str, Any]) -> None:
        """§37, contra o banco."""
        a, b = publicado["research_build"], publicado["second_research_build"]
        _d1, direta = await _compor(publicado, dataset_name="ordem-ab", build_runs=(a, b))
        _d2, invertida = await _compor(publicado, dataset_name="ordem-ba", build_runs=(b, a))
        assert direta.manifest.corpus_fingerprint == invertida.manifest.corpus_fingerprint

    async def test_caso_d_builds_de_escopos_diferentes_bloqueiam_a_publicacao(
        self, publicado: dict[str, Any]
    ) -> None:
        """§27, §36, §95. Um build de pesquisa e um comercial não formam UMA
        versão: a composição uniria as famílias, e a união de um corpus
        comercial com um de pesquisa é um corpus de pesquisa com rótulo
        comercial — as odds restritas voltariam pela porta do outro build.
        """
        contêiner = publicado["corpus"]
        dataset = await contêiner.create_dataset.execute(
            actor=PUBLICADOR, name="corpus-incompativel"
        )
        with pytest.raises(ValidationError, match="rótulo comercial"):
            await contêiner.build_version.execute(
                actor=PUBLICADOR,
                dataset_id=dataset.id,
                version=DatasetVersion(major=1, minor=0),
                scope=_escopo(publicado, UsageScope.COMMERCIAL),
                inputs=_entradas(
                    publicado,
                    publicado["commercial_build"],
                    publicado["research_build"],
                ),
                quality_run_id=publicado["quality_run"].id,
            )

        # E NENHUMA VERSÃO FICOU PARA TRÁS: a recusa acontece antes de escrever.
        versoes, total = await contêiner.datasets.list_versions(dataset.id)
        assert total == 0
        assert not versoes

    async def test_o_sql_nao_deduplica_mais_por_conta_propria(
        self, publicado: dict[str, Any]
    ) -> None:
        """§28. A leitura devolve UMA LINHA POR (PARTIDA, BUILD).

        Sem esta propriedade, a composição do domínio nunca veria a segunda
        contribuição — e o «nenhum build vence» seria uma afirmação sobre
        código que não recebe os dados necessários para cumpri-la.
        """
        leitura = publicado["corpus"].composition
        linhas = await leitura.page_facts(
            [
                publicado["research_build"].id,
                publicado["second_research_build"].id,
            ],
            limit=100,
        )
        assert len(linhas) == 2
        assert len({str(f.match.id) for f in linhas}) == 1
        assert {f.build_run_id for f in linhas} == {
            publicado["research_build"].id,
            publicado["second_research_build"].id,
        }


# ============================================================= a linhagem ==


class TestATravessiaDeLinhagem:
    async def test_do_corpus_ate_o_arquivo_bruto(self, publicado: dict[str, Any]) -> None:
        """§99, §102. «Por que esta partida está no corpus 1.0» tem de ter
        resposta em SQL, sem arqueologia:

            membro → build → avaliação → grupo de fusão → arquivo
        """
        _dataset, saida = await _compor(publicado)
        async with publicado["database"].acquire() as conexao:
            linha = await conexao.fetchrow(
                """
                SELECT m.match_id,
                       b.id            AS build_run,
                       b.quality_run_id,
                       a.fusion_group_id,
                       q.status        AS quality_status
                FROM historical_canonical_members m
                JOIN historical_canonical_member_builds c
                     ON c.version_id = m.version_id AND c.match_id = m.match_id
                JOIN canonical_build_runs b        ON b.id = c.build_run_id
                JOIN match_quality_assessments a   ON a.id = c.quality_assessment_id
                JOIN quality_runs q                ON q.id = b.quality_run_id
                WHERE m.version_id = $1
                """,
                _uuid.UUID(saida.version.id),
            )
        assert linha is not None
        assert str(linha["match_id"]) == str(publicado["match_id"])
        assert str(linha["quality_run_id"]) == publicado["quality_run"].id
        assert linha["fusion_group_id"] is not None
        assert linha["quality_status"].startswith("COMPLETED")

    async def test_a_travessia_multi_build_alcanca_os_dois(self, publicado: dict[str, Any]) -> None:
        """§94. A partida reutilizada de A+B prova os DOIS no traversal."""
        _dataset, saida = await _compor(
            publicado,
            build_runs=(
                publicado["research_build"],
                publicado["second_research_build"],
            ),
        )
        async with publicado["database"].acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT b.id AS build_run, q.id AS quality_run, a.fusion_group_id
                FROM historical_canonical_members m
                JOIN historical_canonical_member_builds c
                     ON c.version_id = m.version_id AND c.match_id = m.match_id
                JOIN canonical_build_runs b      ON b.id = c.build_run_id
                JOIN match_quality_assessments a ON a.id = c.quality_assessment_id
                JOIN quality_runs q              ON q.id = b.quality_run_id
                WHERE m.version_id = $1
                ORDER BY b.id
                """,
                _uuid.UUID(saida.version.id),
            )
        assert {str(linha["build_run"]) for linha in linhas} == {
            publicado["research_build"].id,
            publicado["second_research_build"].id,
        }
        # A MESMA AVALIAÇÃO nos dois: eles rodaram sobre a mesma execução de
        # qualidade, e a travessia continua chegando à fusão pelos dois lados.
        assert all(linha["fusion_group_id"] is not None for linha in linhas)

    async def test_a_travessia_para_frente_encontra_as_versoes(
        self, publicado: dict[str, Any]
    ) -> None:
        """A pergunta inversa: «deste build saíram quais corpus?» (§99)."""
        _dataset, saida = await _compor(publicado)
        versoes = await publicado["corpus"].datasets.versions_using_build(
            publicado["research_build"].id
        )
        assert [v.id for v in versoes] == [saida.version.id]

    async def test_a_partida_sabe_em_quais_corpus_entrou(self, publicado: dict[str, Any]) -> None:
        """A mesma partida em duas versões é o NORMAL, e não uma anomalia."""
        _d1, pesquisa = await _compor(publicado, dataset_name="corpus-a")
        _d2, comercial = await _compor(
            publicado,
            dataset_name="corpus-b",
            usage=UsageScope.COMMERCIAL,
            build_runs=(publicado["commercial_build"],),
        )
        versoes = await publicado["corpus"].membership.versions_containing(publicado["match_id"])
        assert {pesquisa.version.id, comercial.version.id} <= set(versoes)


# ======================================================== a materialização ==


class TestAMaterializacao:
    async def test_escreve_parquet_particionado_e_o_manifesto(
        self, publicado: dict[str, Any], minio_only: Any
    ) -> None:
        """ADR-0027, contra MinIO de verdade: os objetos existem, têm bytes, e
        a chave é a partição Hive que um leitor analítico poda."""
        _dataset, saida = await _compor(publicado)
        assert saida.materialized is True
        assert saida.objects_written >= 2  # MATCH e ODDS

        chaves = [o.object_key for o in saida.manifest.objects]
        assert any("family=MATCH" in c for c in chaves)
        assert any("family=ODDS" in c for c in chaves)
        assert all("competition=PREMIER_LEAGUE" in c for c in chaves)
        assert all("season=2024/25" in c for c in chaves)

        for objeto in saida.manifest.objects:
            metadados = await minio_only.head(objeto.object_key)
            assert metadados is not None, objeto.object_key
            assert metadados.size_bytes == objeto.size_bytes

        await publicado["corpus"].publish_version.execute(
            actor=PUBLICADOR, version_id=saida.version.id, reason="publicação"
        )
        # A CHAVE JÁ VEM COM O `v`. `str(DatasetVersion)` é `"v1.0"`, e não
        # `"1.0"` — acrescentar um segundo prefixo aqui produzia
        # `.../vv1.0/manifest.json`, que não existe, e a asserção reprovava um
        # manifesto que estava gravado no lugar certo.
        manifesto = await minio_only.head(
            f"corpus/historical-core/{saida.version.version}/manifest.json"
        )
        assert manifesto is not None

    async def test_os_objetos_ficam_consultaveis_no_banco(
        self, publicado: dict[str, Any], minio_only: Any
    ) -> None:
        """§55, §118. Sem esta tabela, «o corpus 1.0 escreveu quais arquivos»
        exigiria listar o bucket — e uma versão que falhou no meio deixaria
        órfãos que ninguém encontra."""
        _dataset, saida = await _compor(publicado)
        async with publicado["database"].acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT object_key, family, sha256, size_bytes, row_count
                FROM historical_canonical_objects
                WHERE version_id = $1
                ORDER BY object_key
                """,
                _uuid.UUID(saida.version.id),
            )
        assert len(linhas) == saida.objects_written
        assert {linha["family"] for linha in linhas} == {"MATCH", "ODDS"}
        for linha in linhas:
            assert len(linha["sha256"]) == 64
            # A CONSTRAINT `hco_nao_vazio` recusa objeto de zero linha: um
            # Parquet vazio é indistinguível de uma partição não escrita.
            assert linha["row_count"] > 0
            assert linha["size_bytes"] > 0

    async def test_manifesto_e_tabela_de_objetos_se_reconciliam(
        self, publicado: dict[str, Any], minio_only: Any
    ) -> None:
        """§58. A reconciliação nos DOIS sentidos.

        Um objeto no manifesto sem linha no banco é um arquivo que ninguém
        encontra por consulta; uma linha no banco sem objeto no manifesto é um
        arquivo que o corpus não declara possuir. As duas direções são defeitos
        diferentes, e por isso as duas são afirmadas.
        """
        _dataset, saida = await _compor(publicado)
        do_manifesto = {o.object_key for o in saida.manifest.objects}
        do_banco = {
            o.object_key for o in await publicado["corpus"].manifests.objects_of(saida.version.id)
        }
        assert do_manifesto == do_banco
        assert do_manifesto, "a materialização não escreveu objeto nenhum"

    async def test_o_sha256_gravado_bate_com_o_objeto_real(
        self, publicado: dict[str, Any], minio_only: Any
    ) -> None:
        """§59. O digest é RECALCULADO sobre os bytes que o MinIO devolve.

        Comparar o valor gravado com ele mesmo não prova nada. O que prova é
        baixar o objeto e refazer a conta: se o que subiu não é o que o banco
        diz, a diferença aparece aqui e não numa auditoria seis meses depois.
        """
        import hashlib

        _dataset, saida = await _compor(publicado)
        gravados = await publicado["corpus"].manifests.objects_of(saida.version.id)
        assert gravados

        objeto = gravados[0]
        blocos = [bloco async for bloco in minio_only.open_stream(objeto.object_key)]
        bruto = b"".join(blocos)
        assert hashlib.sha256(bruto).hexdigest() == objeto.sha256.value
        assert len(bruto) == objeto.size_bytes

    async def test_ready_com_materializacao_exige_objetos(
        self, publicado: dict[str, Any], minio_only: Any
    ) -> None:
        """§57. `READY` + materialização ligada ⇒ existem linhas de objeto.

        Sem esta invariante, uma versão poderia se declarar publicada com
        Parquet ligado e nenhum arquivo escrito — e a ausência só apareceria
        para quem tentasse ler o corpus.
        """
        _dataset, saida = await _compor(publicado)
        versao = await publicado["corpus"].publish_version.execute(
            actor=PUBLICADOR, version_id=saida.version.id, reason="publicação"
        )
        assert versao.status is DatasetVersionStatus.READY
        objetos = await publicado["corpus"].manifests.objects_of(versao.id)
        assert objetos, "versão READY com materialização e sem objeto gravado"

    async def test_a_chave_do_manifesto_e_gravada_com_ele(
        self, publicado: dict[str, Any], minio_only: Any
    ) -> None:
        _dataset, saida = await _compor(publicado)
        async with publicado["database"].acquire() as conexao:
            chave = await conexao.fetchval(
                "SELECT object_key FROM historical_canonical_manifests WHERE version_id = $1",
                _uuid.UUID(saida.version.id),
            )
        assert chave is not None
        assert chave.endswith("/manifest.json")

    async def test_o_parquet_carrega_os_tipos_declarados(
        self, publicado: dict[str, Any], minio_only: Any
    ) -> None:
        """§45, §46, §47. Schema explícito, ausente como `NULL`, odds em
        `decimal128` — as três coisas que um schema inferido perde."""
        import io
        from decimal import Decimal

        import pyarrow.parquet as pq

        _dataset, saida = await _compor(publicado)
        chave = next(o.object_key for o in saida.manifest.objects if "family=ODDS" in o.object_key)
        blocos = [bloco async for bloco in minio_only.open_stream(chave)]
        tabela = pq.read_table(io.BytesIO(b"".join(blocos)))
        # DUAS CASAS VEZES TRÊS SELEÇÕES (§42, §93): `2.025` seria um preço
        # que casa nenhuma ofereceu, e colapsar H/D/A perderia dois terços do
        # mercado.
        assert tabela.num_rows == 6
        assert str(tabela.schema.field("decimal_odds").type) == "decimal128(10, 4)"
        assert isinstance(tabela.column("decimal_odds")[0].as_py(), Decimal)
        # A FONTE NÃO DECLARA `observed_at`, e o arquivo diz isso com `NULL`.
        assert tabela.column("observed_at").null_count == 6

    async def test_o_parquet_de_partida_traz_ausencia_como_nulo(
        self, publicado: dict[str, Any], minio_only: Any
    ) -> None:
        import io

        import pyarrow.parquet as pq

        _dataset, saida = await _compor(publicado)
        chave = next(o.object_key for o in saida.manifest.objects if "family=MATCH" in o.object_key)
        blocos = [bloco async for bloco in minio_only.open_stream(chave)]
        tabela = pq.read_table(io.BytesIO(b"".join(blocos)))
        assert tabela.column("home_goals")[0].as_py() == 3
        assert tabela.column("away_goals")[0].as_py() == 0
        # SEM PRORROGAÇÃO: `NULL`, e não `0`. Zero seria «não marcaram».
        assert tabela.column("extra_time_home_goals").null_count == 1
        assert tabela.column("penalty_home_goals").null_count == 1


# ============================================================== o limite ==


class TestOLimiteDaFase:
    async def test_o_corpus_pronto_nao_ativa_vetor_nenhum(self, publicado: dict[str, Any]) -> None:
        """§4. HISTORICAL_CANONICAL_READY ≠ HISTORICAL_VECTOR_ACTIVE."""
        from sports_intelligence.domain.corpus.versions import assert_not_vector_active
        from sports_intelligence.domain.shared.errors import InvariantViolationError

        _dataset, saida = await _compor(publicado)
        versao = await publicado["corpus"].publish_version.execute(
            actor=PUBLICADOR, version_id=saida.version.id, reason="publicação"
        )
        with pytest.raises(InvariantViolationError, match="PR-05"):
            assert_not_vector_active(versao)

    async def test_publicar_nao_reavalia_qualidade_nem_reconstroi_fatos(
        self, publicado: dict[str, Any]
    ) -> None:
        """§135. Publicar é LEITURA sobre fatos já construídos. Uma
        reavaliação escondida faria o corpus mudar de conteúdo por ter sido
        publicado."""
        async with publicado["database"].acquire() as conexao:
            antes = await conexao.fetchrow(
                "SELECT (SELECT count(*) FROM quality_runs) AS q, "
                "(SELECT count(*) FROM canonical_build_runs) AS b, "
                "(SELECT count(*) FROM match_quality_assessments) AS a"
            )
        _dataset, saida = await _compor(publicado)
        await publicado["corpus"].publish_version.execute(
            actor=PUBLICADOR, version_id=saida.version.id, reason="publicação"
        )
        async with publicado["database"].acquire() as conexao:
            depois = await conexao.fetchrow(
                "SELECT (SELECT count(*) FROM quality_runs) AS q, "
                "(SELECT count(*) FROM canonical_build_runs) AS b, "
                "(SELECT count(*) FROM match_quality_assessments) AS a"
            )
        assert antes is not None
        assert depois is not None
        assert (antes["q"], antes["b"], antes["a"]) == (
            depois["q"],
            depois["b"],
            depois["a"],
        )
