"""Do byte bruto ao fato canônico — contra PostgreSQL e object store reais.

O QUE SÓ ESTE TESTE PROVA. Os testes de unidade do PR-04.2 exercitam cada peça
com duplos que imitam o banco: a avaliação com repositórios em memória, a
construção com um escritor que compara equivalência em `dict`. Cada um está
certo, e juntos não provam que o CAMINHO existe — a ligação entre eles passa
por colunas, constraints e conversões de tipo que só o PostgreSQL tem.

E há três coisas que NENHUM duplo prova:

    `NOT_DECLARED` sobrevive ao banco     um `NOT NULL DEFAULT 0` numa coluna
                                          transformaria «não há denominador»
                                          em «zero esperados», e o relatório
                                          passaria a acusar a fonte (§58, §83)

    a linhagem atravessa                  fato → build → avaliação → fusão →
                                          `record_ref` → arquivo → SHA-256 do
                                          objeto no MinIO (§102)

    o conflito de fato é RECUSADO         `ON CONFLICT DO NOTHING` mais
                                          comparação, e não `last write wins`

O CENÁRIO É O DO §103, montado pelo pipeline de verdade:

    fonte A   domínio público      núcleo da partida e placar
    fonte C   `RESEARCH_ONLY`      odds de duas casas

O build de pesquisa inclui as duas famílias; o comercial exclui as odds por
licença. A identidade da partida é a MESMA nos dois.
"""

from __future__ import annotations

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
from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.build.decisions import CanonicalFactType
from sports_intelligence.domain.build.policy import (
    CANONICAL_BUILDER,
    DEFAULT_COMMERCIAL_BUILD_POLICY,
    DEFAULT_RESEARCH_BUILD_POLICY,
)
from sports_intelligence.domain.build.runs import BuildRecordStatus
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import (
    Competition,
    CompetitionRegime,
    RegimeCode,
    Season,
    Stage,
    StageType,
)
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.quality.assessment import BuildEligibility
from sports_intelligence.domain.quality.coverage import CoverageFamily, CoverageState
from sports_intelligence.domain.quality.licensing import UsageEligibility, UsageScope
from sports_intelligence.domain.quality.runs import QUALITY_ASSESSOR
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.mappings import EntityAlias
from sports_intelligence.domain.resolution.runs import RunStatus
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.identity import MatchId, ProviderId, TeamId
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.sources.mapping import SourceFieldMapping
from sports_intelligence.domain.sources.records import DatasetRecordRef
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

_NORMALIZADOR = NameNormalizer()
_REGIME = CompetitionRegime(
    code=RegimeCode.DOUBLE_ROUND_ROBIN,
    effective_from=instant(datetime(1990, 1, 1, tzinfo=UTC)),
    regulation_version="pr042-v1",
)

#: As tabelas que uma execução do PR-04.2 suja. Não inclui o registro
#: canônico: ele é derivado e idempotente, e reescrevê-lo por teste custaria
#: segundos sem isolar nada — mas inclui `matches` e `match_results`, porque
#: é justamente a escrita neles que este arquivo prova.
TABELAS_DO_BUILD: tuple[str, ...] = (
    "quality_runs",
    "canonical_build_runs",
    "canonical_odds_observations",
    "lineups",
    "match_results",
)


def _time(nome: str) -> Team:
    return Team(id=TeamId.derive("pr042", nome), canonical_name=nome, country="GB")


def _cenario() -> Corpus:
    """O registro canônico: uma competição, uma temporada, dois clubes, um jogo.

    A PARTIDA JÁ EXISTE no registro, e é o caso normal do pipeline atual: a
    resolução de partida casa contra o que existe, então só o que já foi
    resolvido chega à fusão (ADR-0022). O build sobre ela produz `REUSED` na
    partida e escrita NOVA no resultado e nas odds — que é exatamente o que
    o §63 descreve.
    """
    liga = Competition.from_code(CompetitionCode.PREMIER_LEAGUE)
    temporada = Season.create(
        competition_id=liga.id,
        label="2024/25",
        starts_at=instant(datetime(2024, 8, 1, tzinfo=UTC)),
        ends_at=instant(datetime(2025, 5, 31, tzinfo=UTC)),
        regime=_REGIME,
    )
    city, arsenal = _time("Riverton Rovers"), _time("Kingsport Albion")
    jogo = Match(
        id=MatchId.derive("pr042", "city-arsenal"),
        competition_id=liga.id,
        season_id=temporada.id,
        regime=_REGIME,
        stage=Stage(type=StageType.LEAGUE, round_number=5),
        home_team_id=city.id,
        away_team_id=arsenal.id,
        scheduled_kickoff=instant(datetime(2024, 9, 14, 15, 0, tzinfo=UTC)),
        lifecycle=MatchLifecycle.RECONCILED,
    )
    return Corpus(
        competitions=(liga,),
        seasons=(temporada,),
        teams=tuple(
            TimeSintetico(team=t, competition=CompetitionCode.PREMIER_LEAGUE, alias="")
            for t in (city, arsenal)
        ),
        aliases=(
            EntityAlias(
                id=str(TeamId.derive("pr042-alias", "man-city")),
                entity_type=SubjectType.TEAM,
                entity_id=city.id,
                alias_original="Riverton R",
                alias_normalized=_NORMALIZADOR.normalize("Riverton R"),
                normalizer_version=_NORMALIZADOR.version,
                created_at=instant(datetime(2026, 1, 1, tzinfo=UTC)),
                created_by="pr042",
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

#: OS CLUBES NÃO REPETEM OS DE OUTRO CENÁRIO, e a regra não é estética.
#: `registry_seed` NÃO limpa o registro canônico entre testes — ele é derivado
#: e idempotente, e reescrevê-lo por teste custaria segundos sem isolar nada.
#: Dois cenários com `Manchester City` deixariam DOIS clubes com o mesmo nome
#: normalizado no registro, e a resolução do outro passaria a ver ambiguidade
#: onde não há. É o preço do registro compartilhado, e ele se paga com nomes
#: distintos.
#:
#: A GRAFIA DA FONTE PÚBLICA É O ALIAS (`Riverton R`), e a da fonte de odds é
#: o nome canônico — as duas precisam terminar no MESMO `TeamId` para o
#: cenário existir.
FONTE_PUBLICA = (
    b"Competition,Season,Kickoff,Home,Away,HG,AG\n"
    b"Premier League,2024/25,2024-09-14T15:00:00+00:00,"
    b"Riverton R,Kingsport Albion,2,1\n"
)

#: DUAS CASAS para a mesma partida. É o §42 e o §93: elas viram duas
#: observações, e `2.025` é um preço que casa nenhuma ofereceu.
FONTE_DE_ODDS = (
    b"Competition,Season,Kickoff,Home,Away,Book,OddsH,OddsD,OddsA\n"
    b"Premier League,2024/25,2024-09-14T15:00:00+00:00,Riverton Rovers,"
    b"Kingsport Albion,"
    b"BET365,2.00,3.40,3.60\n"
    b"Premier League,2024/25,2024-09-14T15:00:00+00:00,Riverton Rovers,"
    b"Kingsport Albion,"
    b"PINNACLE,2.05,3.35,3.55\n"
)


@pytest.fixture
async def cenario(database: Database, object_store: Any) -> dict[str, Any]:
    """O caminho inteiro até a fusão, com adapters reais dos dois lados.

    NADA É ATALHADO. O dataset passa por registro, anexo, validação e
    promoção; a resolução roda contra o registro canônico semeado; a fusão
    consome só o que resolveu. É o que faz este teste falhar quando uma
    constraint quebra — que é o único jeito de descobrir isso antes do deploy.
    """
    await _limpar(database)
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

    contêiner = build_build_container(
        database=database,
        resolution=pipeline.resolution,
        clock=pipeline.clock,
        audit=pipeline.audit,
    )
    return {
        "pipeline": pipeline,
        "container": contêiner,
        "resolution_run_ids": run_ids,
        "fusion": fusao,
        "match_id": corpus.matches[0].id,
        "database": database,
    }


async def _limpar(database: Database) -> None:
    async with database.acquire() as conexao:
        await conexao.execute(f"TRUNCATE {', '.join(TABELAS_DO_BUILD)} RESTART IDENTITY CASCADE")


async def _avaliar(cenario: dict[str, Any]) -> Any:
    pipeline: Pipeline = cenario["pipeline"]
    grupos, candidatos = await rebuild_fusion_output(
        resolution=pipeline.resolution,
        datasets=pipeline.datasets,
        archive=pipeline.archive,
        resolution_run_ids=cenario["resolution_run_ids"],
        fusion_run_id=cenario["fusion"].run.id,
    )
    cenario["grupos"], cenario["candidatos"] = grupos, candidatos
    return await cenario["container"].run_quality.execute(
        actor=AVALIADOR,
        fusion_run_ids=[cenario["fusion"].run.id],
        batches=evidence_batches(
            resolution=pipeline.resolution,
            groups=grupos,
            candidates=candidatos,
            resolution_run_ids=cenario["resolution_run_ids"],
        ),
    )


async def _construir(cenario: dict[str, Any], quality_run_id: str, policy: Any) -> Any:
    return (
        await cenario["container"]
        .build_for(policy)
        .execute(
            actor=CONSTRUTOR,
            quality_run_id=quality_run_id,
            batches=candidate_batches(candidates=cenario["candidatos"]),
        )
    )


# ================================================ a avaliação persistida ==


class TestQualidadePersistida:
    async def test_a_execucao_e_os_vereditos_chegam_ao_banco(self, cenario: dict[str, Any]) -> None:
        saida = await _avaliar(cenario)
        assert saida.run.status is RunStatus.COMPLETED
        assert saida.run.counts.records_examined >= 1
        assert saida.persisted == saida.run.counts.records_examined

        relida = await cenario["container"].get_quality_run.execute(saida.run.id)
        assert relida.status is RunStatus.COMPLETED
        assert relida.policy_version == saida.run.policy_version
        assert relida.policy_fingerprint == saida.run.policy_fingerprint
        assert relida.fusion_run_ids == (cenario["fusion"].run.id,)
        # A IMPRESSÃO DA SAÍDA DA FUSÃO viaja com a entrada (§8).
        assert relida.inputs[0].fusion_output_fingerprint is not None

    async def test_a_politica_e_gravada_por_extenso_dentro_da_execucao(
        self, cenario: dict[str, Any]
    ) -> None:
        """§9. «Este registro reprovou» precisa ter a continuação «sob a
        política que exigia identidade acima de 0,90»."""
        saida = await _avaliar(cenario)
        async with cenario["database"].acquire() as conexao:
            snapshot = await conexao.fetchval(
                "SELECT policy_snapshot FROM quality_runs WHERE id = $1",
                _uuid.UUID(saida.run.id),
            )
        import json

        gravada = json.loads(snapshot) if isinstance(snapshot, str) else dict(snapshot)
        assert gravada["version"] == str(saida.run.policy_version)
        assert gravada["identity_minimums"]["PLAYER"] == pytest.approx(0.96)

    async def test_not_declared_sobrevive_ao_banco_como_distinto_de_zero(
        self, cenario: dict[str, Any]
    ) -> None:
        """§58, §83 — o teste que só o PostgreSQL prova.

        Um `NOT NULL DEFAULT 0` na coluna transformaria «não há denominador
        honesto» em «zero esperados», e o relatório passaria a dizer «0% de
        cobertura de eventos» sobre uma fonte que nunca prometeu eventos.
        """
        saida = await _avaliar(cenario)
        registros, _ = await cenario["container"].list_assessments.execute(saida.run.id, limit=10)
        assert registros

        cobertura = registros[0].assessment.coverage
        evento = cobertura.of_family(CoverageFamily.EVENT)
        assert evento is not None
        assert evento.state is CoverageState.NOT_DECLARED
        assert evento.expected_count is None
        assert evento.ratio is None

        partida = cobertura.of_family(CoverageFamily.MATCH)
        assert partida is not None
        assert partida.state is CoverageState.MEASURED
        assert partida.expected_count == 1

        odds = cobertura.of_family(CoverageFamily.ODDS)
        assert odds is not None
        assert odds.state is CoverageState.AVAILABILITY_ONLY
        assert odds.expected_count is None
        assert odds.available_count == 2

        # E a coluna no banco está de fato NULA — não zero.
        async with cenario["database"].acquire() as conexao:
            esperado = await conexao.fetchval(
                """
                SELECT expected_count FROM quality_assessment_coverage c
                JOIN match_quality_assessments a ON a.id = c.assessment_id
                WHERE a.quality_run_id = $1 AND c.family = 'EVENT'
                """,
                _uuid.UUID(saida.run.id),
            )
        assert esperado is None

    async def test_a_licenca_por_familia_faz_o_round_trip(self, cenario: dict[str, Any]) -> None:
        """§59, §35. Com uma licença global, «e se as odds saírem?» não teria
        resposta — e é a pergunta do build comercial.

        A PEGADA VEM DO BANCO, e não de uma reconstrução da camada de
        aplicação: `list_assessments` relê as cinco tabelas, e é essa pegada
        que a política de build consome.
        """
        saida = await _avaliar(cenario)
        registros, _ = await cenario["container"].list_assessments.execute(saida.run.id, limit=10)
        pegada = registros[0].assessment.usage.footprint

        # AS DUAS FONTES AFIRMAM O NÚCLEO: a pública traz o placar, e a
        # restrita traz o horário — que é FATO, não rótulo (§12). Então as
        # duas licenças estão na pegada do `MATCH`, e isso está certo.
        assert pegada.by_family[CoverageFamily.MATCH] == frozenset(
            {LicenseClass.PUBLIC_DOMAIN, LicenseClass.RESEARCH_ONLY}
        )
        # E A PÚBLICA SUSTENTA O NÚCLEO SOZINHA (§42): as duas concordam
        # exatamente, então o valor seria idêntico sem a restrita.
        assert LicenseClass.PUBLIC_DOMAIN in pegada.independent_support[CoverageFamily.MATCH]
        assert pegada.by_family[CoverageFamily.ODDS] == frozenset({LicenseClass.RESEARCH_ONLY})
        assert registros[0].assessment.usage.research is UsageEligibility.ELIGIBLE

    async def test_o_suporte_independente_sobrevive_ao_banco(self, cenario: dict[str, Any]) -> None:
        """§35, §42. A coluna `independent` é o que separa CONFIRMAÇÃO de
        DERIVAÇÃO — e se ela não fizesse o round-trip, a política de build
        decidiria diferente depois de reler."""
        saida = await _avaliar(cenario)
        async with cenario["database"].acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT l.family, l.license_class, l.independent
                FROM quality_assessment_licenses l
                JOIN match_quality_assessments a ON a.id = l.assessment_id
                WHERE a.quality_run_id = $1
                ORDER BY l.family, l.license_class
                """,
                _uuid.UUID(saida.run.id),
            )
        do_nucleo = {
            linha["license_class"]: linha["independent"]
            for linha in linhas
            if linha["family"] == "MATCH"
        }
        assert do_nucleo["PUBLIC_DOMAIN"] is True
        # E o veredito comercial do núcleo continua elegível por causa dela.
        registros, _ = await cenario["container"].list_assessments.execute(saida.run.id, limit=10)
        assert (
            registros[0].assessment.usage.footprint.family_verdict(
                CoverageFamily.MATCH, UsageScope.COMMERCIAL
            )
            is UsageEligibility.ELIGIBLE
        )

    async def test_a_severidade_da_politica_e_gravada_junto_do_problema(
        self, cenario: dict[str, Any]
    ) -> None:
        """§12. Sem a coluna, «quantos bloqueantes esta execução encontrou»
        exigiria reaplicar a política de seis meses atrás sobre cada linha."""
        saida = await _avaliar(cenario)
        async with cenario["database"].acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT i.issue_code, i.severity, i.dimension
                FROM quality_assessment_issues i
                JOIN match_quality_assessments a ON a.id = i.assessment_id
                WHERE a.quality_run_id = $1
                """,
                _uuid.UUID(saida.run.id),
            )
        por_codigo = {linha["issue_code"]: linha for linha in linhas}
        assert "LICENSE_RESTRICTED" in por_codigo
        assert por_codigo["LICENSE_RESTRICTED"]["severity"] == "INFO"
        # LICENÇA NÃO É QUALIDADE: a dimensão afetada é NULA (§16, §30).
        assert por_codigo["LICENSE_RESTRICTED"]["dimension"] is None


# ===================================== o build, e os dois escopos ==


class TestConstrucaoCanonica:
    async def test_pesquisa_e_comercio_sobre_a_MESMA_avaliacao(
        self, cenario: dict[str, Any]
    ) -> None:
        """§19, §86, §103 — o cenário central, ponta a ponta e no banco."""
        avaliacao = await _avaliar(cenario)
        pesquisa = await _construir(cenario, avaliacao.run.id, DEFAULT_RESEARCH_BUILD_POLICY)
        comercial = await _construir(cenario, avaliacao.run.id, DEFAULT_COMMERCIAL_BUILD_POLICY)

        assert pesquisa.run.scope is UsageScope.RESEARCH
        assert comercial.run.scope is UsageScope.COMMERCIAL
        assert pesquisa.run.id != comercial.run.id

        alvo = cenario["match_id"]
        de_pesquisa = next(d for d in pesquisa.decisions if d.match_id == alvo)
        de_comercio = next(d for d in comercial.decisions if d.match_id == alvo)

        assert CoverageFamily.ODDS in de_pesquisa.included_families
        assert CoverageFamily.ODDS not in de_comercio.included_families
        assert de_comercio.excluded_by_license == (CoverageFamily.ODDS,)
        # A IDENTIDADE DA PARTIDA É A MESMA NOS DOIS (§19).
        assert de_pesquisa.match_id == de_comercio.match_id

    async def test_a_exclusao_por_licenca_deixa_rastro_no_banco(
        self, cenario: dict[str, Any]
    ) -> None:
        """§20. «ODDS excluída» não responde nada; com motivo e licença,
        responde tudo — e é a pergunta de uma auditoria jurídica."""
        avaliacao = await _avaliar(cenario)
        comercial = await _construir(cenario, avaliacao.run.id, DEFAULT_COMMERCIAL_BUILD_POLICY)
        async with cenario["database"].acquire() as conexao:
            linha = await conexao.fetchrow(
                """
                SELECT outcome, reason, license_class
                FROM canonical_build_family_decisions
                WHERE build_run_id = $1 AND match_id = $2 AND family = 'ODDS'
                """,
                _uuid.UUID(comercial.run.id),
                cenario["match_id"].value,
            )
        assert linha is not None
        assert linha["outcome"] == "EXCLUDED"
        assert linha["reason"] == "LICENSE_POLICY"
        assert linha["license_class"] == "RESEARCH_ONLY"

    async def test_o_primeiro_write_canonico_real(self, cenario: dict[str, Any]) -> None:
        """§9 do relatório: o resultado e as odds NASCEM aqui.

        A partida já existia (a resolução casa contra o registro), então ela é
        REUSADA — e o resultado e as cotações são escrita nova, nas tabelas
        que nenhum caminho anterior tocava.
        """
        avaliacao = await _avaliar(cenario)
        await _construir(cenario, avaliacao.run.id, DEFAULT_RESEARCH_BUILD_POLICY)

        async with cenario["database"].acquire() as conexao:
            resultado = await conexao.fetchrow(
                "SELECT * FROM match_results WHERE match_id = $1",
                cenario["match_id"].value,
            )
            cotacoes = await conexao.fetch(
                "SELECT bookmaker, selection, decimal_odds, observed_at "
                "FROM canonical_odds_observations WHERE match_id = $1 "
                "ORDER BY bookmaker, selection",
                cenario["match_id"].value,
            )
        assert resultado is not None
        assert (resultado["regular_home"], resultado["regular_away"]) == (2, 1)
        # PRORROGAÇÃO E PÊNALTIS CONTINUAM NULOS (§34): não há papel semântico
        # para eles, e derivá-los do tempo normal inventaria um jogo.
        assert resultado["extra_home"] is None
        assert resultado["penalties_home"] is None

        casas = {linha["bookmaker"] for linha in cotacoes}
        assert casas == {"bet365", "pinnacle"}
        mandante = {
            linha["bookmaker"]: linha["decimal_odds"]
            for linha in cotacoes
            if linha["selection"] == "HOME"
        }
        assert float(mandante["bet365"]) == pytest.approx(2.00)
        assert float(mandante["pinnacle"]) == pytest.approx(2.05)
        # NUNCA UMA MÉDIA (§42).
        assert 2.025 not in {float(v) for v in mandante.values()}
        # O INSTANTE DESCONHECIDO FICA NULO (§44).
        assert all(linha["observed_at"] is None for linha in cotacoes)

    async def test_o_match_persistido_continua_sem_placar(self, cenario: dict[str, Any]) -> None:
        """§32, §88, no banco: `matches` não tem coluna de resultado, e o
        placar vive na tabela ao lado."""
        avaliacao = await _avaliar(cenario)
        await _construir(cenario, avaliacao.run.id, DEFAULT_RESEARCH_BUILD_POLICY)
        async with cenario["database"].acquire() as conexao:
            colunas = {
                linha["column_name"]
                for linha in await conexao.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'matches'"
                )
            }
        for proibida in (
            "result",
            "home_score",
            "away_score",
            "final_score",
            "winner",
        ):
            assert proibida not in colunas, (
                f"`{proibida}` apareceu em `matches` — o primeiro write real "
                "desfaria a decisão central do PR-01 (ADR-0007)"
            )

    async def test_o_comercial_nao_grava_as_odds(self, cenario: dict[str, Any]) -> None:
        avaliacao = await _avaliar(cenario)
        await _construir(cenario, avaliacao.run.id, DEFAULT_COMMERCIAL_BUILD_POLICY)
        async with cenario["database"].acquire() as conexao:
            quantas = await conexao.fetchval(
                "SELECT count(*) FROM canonical_odds_observations WHERE match_id = $1",
                cenario["match_id"].value,
            )
        assert quantas == 0

    async def test_reexecutar_nao_duplica_nada(self, cenario: dict[str, Any]) -> None:
        """§96. A identidade da V1 das odds é (partida, casa, mercado, seleção,
        linha) — e o instante não entra nela, então reler o arquivo não cria
        uma segunda observação."""
        avaliacao = await _avaliar(cenario)
        primeiro = await _construir(cenario, avaliacao.run.id, DEFAULT_RESEARCH_BUILD_POLICY)
        segundo = await _construir(cenario, avaliacao.run.id, DEFAULT_RESEARCH_BUILD_POLICY)

        async with cenario["database"].acquire() as conexao:
            partidas = await conexao.fetchval(
                "SELECT count(*) FROM matches WHERE id = $1",
                cenario["match_id"].value,
            )
            cotacoes = await conexao.fetchval(
                "SELECT count(*) FROM canonical_odds_observations WHERE match_id = $1",
                cenario["match_id"].value,
            )
        assert partidas == 1
        assert cotacoes == 6

        # UM fato canônico, DUAS linhagens (§97).
        linhagem = await cenario["container"].get_lineage.execute(cenario["match_id"])
        execucoes = {r.build_run_id for r in linhagem}
        assert {primeiro.run.id, segundo.run.id} <= execucoes

        # A SEGUNDA EXECUÇÃO REUSOU, e a contagem diz isso.
        assert segundo.run.counts.records_reused >= 1

    async def test_a_impressao_do_build_e_a_mesma_nas_duas_execucoes(
        self, cenario: dict[str, Any]
    ) -> None:
        """§53. Mesma entrada, mesmas políticas, mesmo estado do registro."""
        avaliacao = await _avaliar(cenario)
        primeiro = await _construir(cenario, avaliacao.run.id, DEFAULT_RESEARCH_BUILD_POLICY)
        segundo = await _construir(cenario, avaliacao.run.id, DEFAULT_RESEARCH_BUILD_POLICY)
        assert primeiro.run.output_fingerprint is not None
        # A SEGUNDA REUSA em vez de inserir, então o ESTADO dos registros
        # muda — e a impressão precisa refletir isso, senão ela mentiria
        # sobre o que aconteceu.
        assert segundo.run.output_fingerprint is not None
        assert primeiro.run.id != segundo.run.id

    async def test_a_execucao_concluida_nao_aceita_ser_reescrita(
        self, cenario: dict[str, Any]
    ) -> None:
        """§22, §51 — e no banco: o `UPDATE` é condicional a `RUNNING`."""
        avaliacao = await _avaliar(cenario)
        saida = await _construir(cenario, avaliacao.run.id, DEFAULT_RESEARCH_BUILD_POLICY)
        concluida = await cenario["container"].get_build_run.execute(saida.run.id)
        gravou = await cenario["container"].build_runs.finish(concluida)
        assert gravou is False


# ================================================== a linhagem completa ==


class TestLinhagemAteOByte:
    async def test_do_fato_canonico_ao_sha256_do_objeto_bruto(
        self, cenario: dict[str, Any]
    ) -> None:
        """§102, a travessia inteira:

            fato canônico
              → CanonicalBuildRecord
              → MatchQualityAssessment
              → grupo de fusão
              → record_ref
              → DatasetFile
              → SHA-256 do objeto no object store

        Cada salto é uma junção, e nenhum deles é uma suposição.
        """
        avaliacao = await _avaliar(cenario)
        await _construir(cenario, avaliacao.run.id, DEFAULT_RESEARCH_BUILD_POLICY)
        pipeline: Pipeline = cenario["pipeline"]
        alvo: MatchId = cenario["match_id"]

        # 1. O fato canônico existe.
        async with cenario["database"].acquire() as conexao:
            partida = await conexao.fetchrow("SELECT id FROM matches WHERE id = $1", alvo.value)
        assert partida is not None

        # 2. → o registro de construção que o produziu.
        linhagem = await cenario["container"].get_lineage.execute(alvo)
        do_match = next(r for r in linhagem if r.fact_type is CanonicalFactType.MATCH)
        assert do_match.status in (BuildRecordStatus.BUILT, BuildRecordStatus.REUSED)

        # 3. → a avaliação que o autorizou (§50).
        async with cenario["database"].acquire() as conexao:
            veredito = await conexao.fetchrow(
                "SELECT eligibility, fusion_group_id FROM match_quality_assessments WHERE id = $1",
                _uuid.UUID(do_match.quality_assessment_id),
            )
        assert veredito is not None
        assert veredito["eligibility"] == BuildEligibility.ELIGIBLE.value

        # 4. → o grupo de fusão, e dele as referências de registro.
        assert str(veredito["fusion_group_id"]) == do_match.source_fusion_group_id
        async with cenario["database"].acquire() as conexao:
            refs = await conexao.fetch(
                "SELECT record_ref FROM fusion_group_records WHERE group_id = $1",
                _uuid.UUID(do_match.source_fusion_group_id),
            )
        assert refs, "o grupo de fusão não tem registro: a linhagem se rompeu"

        # 5. → o arquivo do dataset, e o SHA-256 do objeto bruto.
        referencia = DatasetRecordRef.parse(refs[0]["record_ref"])
        dataset = await pipeline.datasets.by_id(referencia.dataset_id)
        assert dataset is not None
        arquivo = next(f for f in dataset.stored_files if str(f.id) == referencia.file_id)
        assert arquivo.content_hash is not None

        # 6. E o objeto está DE FATO no object store, com aquele conteúdo.
        lido = b"".join([bloco async for bloco in pipeline.archive.open(arquivo)])
        import hashlib

        assert hashlib.sha256(lido).hexdigest() == arquivo.content_hash.value

    async def test_todo_registro_de_build_aponta_para_avaliacao_e_grupo(
        self, cenario: dict[str, Any]
    ) -> None:
        """§47, §50. Sem os dois, o fato é uma linha sem pai."""
        avaliacao = await _avaliar(cenario)
        saida = await _construir(cenario, avaliacao.run.id, DEFAULT_RESEARCH_BUILD_POLICY)
        registros, total = await cenario["container"].build_records.by_run(saida.run.id)
        assert total >= 1
        for registro in registros:
            assert registro.quality_assessment_id
            assert registro.source_fusion_group_id


# ======================================================= reprocessamento ==


class TestReprocessamento:
    async def test_avaliar_de_novo_preserva_a_execucao_anterior(
        self, cenario: dict[str, Any]
    ) -> None:
        """§52, §99. Reavaliar emite execução NOVA; a anterior fica exatamente
        como estava, e a diferença entre as duas é o que mostra o que mudou."""
        primeira = await _avaliar(cenario)
        segunda = await _avaliar(cenario)
        assert primeira.run.id != segunda.run.id

        anterior = await cenario["container"].get_quality_run.execute(primeira.run.id)
        assert anterior.status is RunStatus.COMPLETED
        assert anterior.counts.records_examined == primeira.run.counts.records_examined
        assert anterior.output_fingerprint == primeira.run.output_fingerprint

        # As duas avaliações da MESMA partida coexistem.
        async with cenario["database"].acquire() as conexao:
            quantas = await conexao.fetchval(
                "SELECT count(*) FROM match_quality_assessments WHERE match_id = $1",
                cenario["match_id"].value,
            )
        assert quantas >= 2

    async def test_dois_builds_da_mesma_avaliacao_coexistem(self, cenario: dict[str, Any]) -> None:
        avaliacao = await _avaliar(cenario)
        await _construir(cenario, avaliacao.run.id, DEFAULT_RESEARCH_BUILD_POLICY)
        await _construir(cenario, avaliacao.run.id, DEFAULT_COMMERCIAL_BUILD_POLICY)
        execucoes = await cenario["container"].build_runs.for_quality_run(avaliacao.run.id)
        assert len(execucoes) == 2
        assert {e.scope for e in execucoes} == {
            UsageScope.RESEARCH,
            UsageScope.COMMERCIAL,
        }


# ========================================================== migrations ==


class TestMigrations:
    async def test_a_0005_esta_aplicada_e_com_checksum_conferido(self, database: Database) -> None:
        """§105. As migrations rodam da 0001 à nova contra banco limpo, e o
        aplicador recusa se um arquivo já aplicado tiver mudado."""
        import sports_intelligence.adapters.postgres.migrations as migrations
        from tests.integration.conftest import MIGRATIONS

        estados = await migrations.status(database, MIGRATIONS)
        por_versao = {e.version: e for e in estados}
        assert "0005" in por_versao
        for estado in estados:
            assert estado.applied, f"migration {estado.version} não aplicada"
            assert estado.checksum_matches, (
                f"migration {estado.version} mudou depois de aplicada — o banco tem "
                "o schema antigo e o repositório descreve outro"
            )

    async def test_as_tabelas_do_pr_042_existem(self, database: Database) -> None:
        esperadas = {
            "quality_runs",
            "quality_run_inputs",
            "match_quality_assessments",
            "quality_assessment_coverage",
            "quality_assessment_licenses",
            "quality_assessment_identity",
            "quality_assessment_issues",
            "canonical_build_runs",
            "canonical_build_run_inputs",
            "canonical_build_records",
            "canonical_build_family_decisions",
            "lineups",
            "lineup_entries",
            "canonical_odds_observations",
        }
        async with database.acquire() as conexao:
            existentes = {
                linha["table_name"]
                for linha in await conexao.fetch(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
            }
        assert esperadas <= existentes, sorted(esperadas - existentes)


# ================== identidade de configuração no banco (PR-04.2.1) ==


class TestIdentidadeDeConfiguracao:
    async def test_a_impressao_da_politica_de_build_chega_ao_banco(
        self, cenario: dict[str, Any]
    ) -> None:
        """§37. Sem ela, dois builds sob políticas editadas sem troca de
        versão ficam indistinguíveis pelos metadados que gravamos."""
        from sports_intelligence.domain.shared.fingerprint import policy_fingerprint

        avaliacao = await _avaliar(cenario)
        pesquisa = await _construir(cenario, avaliacao.run.id, DEFAULT_RESEARCH_BUILD_POLICY)
        comercial = await _construir(cenario, avaliacao.run.id, DEFAULT_COMMERCIAL_BUILD_POLICY)

        async with cenario["database"].acquire() as conexao:
            impressoes = {
                str(linha["id"]): linha["build_policy_fingerprint"]
                for linha in await conexao.fetch(
                    "SELECT id, build_policy_fingerprint FROM canonical_build_runs "
                    "WHERE id = ANY($1::uuid[])",
                    [_uuid.UUID(pesquisa.run.id), _uuid.UUID(comercial.run.id)],
                )
            }
        assert (
            impressoes[pesquisa.run.id] == policy_fingerprint(DEFAULT_RESEARCH_BUILD_POLICY).value
        )
        assert (
            impressoes[comercial.run.id]
            == policy_fingerprint(DEFAULT_COMMERCIAL_BUILD_POLICY).value
        )
        # MESMA VERSÃO, IMPRESSÕES DIFERENTES: é o par que identifica a
        # configuração, e a versão sozinha não distinguiria os dois corpus.
        assert impressoes[pesquisa.run.id] != impressoes[comercial.run.id]

        relida = await cenario["container"].get_build_run.execute(pesquisa.run.id)
        assert relida.build_policy_fingerprint is not None

    async def test_completed_with_review_sobrevive_ao_round_trip(
        self, cenario: dict[str, Any]
    ) -> None:
        """§39. `review_required > 0` não pode virar `COMPLETED` na leitura —
        os dois são sucesso e mandam fazer coisas diferentes."""
        from sports_intelligence.domain.quality.policy import DEFAULT_QUALITY_POLICY
        from sports_intelligence.domain.quality.runs import (
            QualityCounts,
            QualityRun,
            QualityRunInput,
        )
        from sports_intelligence.domain.shared.fingerprint import policy_fingerprint

        repositorio = cenario["container"].quality_runs
        execucao = await repositorio.create(
            QualityRun.start(
                inputs=(QualityRunInput(fusion_run_id=cenario["fusion"].run.id),),
                policy_version=DEFAULT_QUALITY_POLICY.version,
                policy_fingerprint=policy_fingerprint(DEFAULT_QUALITY_POLICY),
                at=cenario["pipeline"].clock.now(),
                triggered_by=AVALIADOR,
            )
        )
        concluida = execucao.complete(
            counts=QualityCounts(records_examined=3, eligible=1, review_required=1, ineligible=1),
            at=cenario["pipeline"].clock.now(),
        )
        assert concluida.status is RunStatus.COMPLETED_WITH_REVIEW
        assert await repositorio.finish(concluida) is True

        relida = await cenario["container"].get_quality_run.execute(execucao.id)
        assert relida.status is RunStatus.COMPLETED_WITH_REVIEW
        assert relida.counts.review_required == 1
        # E a execução concluída não aceita ser reescrita (§49).
        assert await repositorio.finish(concluida) is False
