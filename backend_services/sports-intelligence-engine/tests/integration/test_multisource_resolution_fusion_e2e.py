"""Três datasets heterogêneos, uma identidade canônica — contra tudo real.

O QUE SÓ ESTE TESTE PROVA. Os testes de unidade do PR-03 exercitam cada peça
com duplos que imitam o banco: o resolver com um contexto montado à mão, a
fusão com `ResolvedSourceRecord` construídos direto. Cada um está certo, e
juntos não provam que o CAMINHO existe — a ligação entre eles passa por
colunas, consultas e conversões de tipo que só o PostgreSQL tem.

Foi exatamente aí que este teste encontrou dois defeitos que o PR-03 fechou
verde: `record_ref` gravado como `NULL` em toda decisão (o que fazia a fusão
receber ZERO registros, sempre) e o id canônico relido do banco como
`EntityId` genérico em vez do tipo concreto (o que derrubava a resolução na
primeira asserção do caso de uso).

O CENÁRIO É O DO §15:

    fonte A   `Man City`            placar, chutes, cartões
    fonte B   `Manchester City FC`  xG, escalação, formação — kickoff com drift
    fonte C   `Manchester City`     odds de duas casas

As três precisam terminar no MESMO `MatchId`, e o candidato fundido precisa
carregar o que cada uma trouxe, com procedência até o byte.
"""

from __future__ import annotations

import hashlib
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import (
    Competition,
    CompetitionRegime,
    RegimeCode,
    Season,
    Stage,
    StageType,
)
from sports_intelligence.domain.fusion.models import FusionRule
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.players.models import Player, PlayerTeamTenure
from sports_intelligence.domain.resolution.decisions import (
    ResolutionStatus,
    SubjectType,
)
from sports_intelligence.domain.resolution.mappings import EntityAlias
from sports_intelligence.domain.resolution.policy import DEFAULT_RESOLUTION_POLICY
from sports_intelligence.domain.shared.identity import (
    MatchId,
    PlayerId,
    ProviderId,
    TeamId,
)
from sports_intelligence.domain.shared.provenance import LicenseClass
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.sources.mapping import SeasonConvention, SourceFieldMapping
from sports_intelligence.domain.sources.semantics import SemanticRole
from sports_intelligence.domain.teams.models import Team
from sports_intelligence.ingestion.normalization.names import NameNormalizer
from sports_intelligence.ingestion.resolution.context import ContextBuilder, NormalizedName
from sports_intelligence.ingestion.resolution.resolvers import ResolverBundle
from tests.support.corpus import Corpus, TimeSintetico
from tests.support.pipeline import Pipeline
from tests.support.registry_seed import limpar_execucoes, seed_corpus

pytestmark = pytest.mark.integration

A = ProviderId("fonte_a")
B = ProviderId("fonte_b")
C = ProviderId("fonte_c")

_NORMALIZADOR = NameNormalizer()
_REGIME = CompetitionRegime(
    code=RegimeCode.DOUBLE_ROUND_ROBIN,
    effective_from=instant(datetime(1990, 1, 1, tzinfo=UTC)),
    regulation_version="e2e-v1",
)
_REGIME_COPA = CompetitionRegime(
    code=RegimeCode.LEAGUE_PHASE_KNOCKOUT,
    effective_from=instant(datetime(1990, 1, 1, tzinfo=UTC)),
    regulation_version="e2e-v1",
)


def _time(nome: str, pais: str = "GB") -> Team:
    return Team(id=TeamId.derive("e2e", nome), canonical_name=nome, country=pais)


def _alias(entidade: TeamId, texto: str) -> EntityAlias:
    return EntityAlias(
        id=str(TeamId.derive("e2e-alias", str(entidade), texto)),
        entity_type=SubjectType.TEAM,
        entity_id=entidade,
        alias_original=texto,
        alias_normalized=_NORMALIZADOR.normalize(texto),
        normalizer_version=_NORMALIZADOR.version,
        created_at=instant(datetime(2026, 1, 1, tzinfo=UTC)),
        created_by="e2e",
    )


def _cenario() -> tuple[Corpus, tuple[Team, Team, Team, Team]]:
    """O registro canônico do cenário: duas competições, quatro clubes.

    A SEGUNDA COMPETIÇÃO NÃO É ENFEITE. Ela existe para o caso negativo do
    §25: o mesmo confronto, no mesmo dia, no mesmo horário, em Premier League
    e em Champions. São dois jogos, e um motor que os fundisse produziria um
    histórico com metade dos jogos e o dobro dos gols em cada.
    """
    liga = Competition.from_code(CompetitionCode.PREMIER_LEAGUE)
    copa = Competition.from_code(CompetitionCode.UEFA_CHAMPIONS_LEAGUE)
    temporada_liga = Season.create(
        competition_id=liga.id,
        label="2024/25",
        starts_at=instant(datetime(2024, 8, 1, tzinfo=UTC)),
        ends_at=instant(datetime(2025, 5, 31, tzinfo=UTC)),
        regime=_REGIME,
    )
    temporada_copa = Season.create(
        competition_id=copa.id,
        label="2024/25",
        starts_at=instant(datetime(2024, 9, 1, tzinfo=UTC)),
        ends_at=instant(datetime(2025, 6, 1, tzinfo=UTC)),
        regime=_REGIME_COPA,
    )

    city = _time("Manchester City")
    arsenal = _time("Arsenal")
    chelsea = _time("Chelsea")
    liverpool = _time("Liverpool")

    def partida(
        chave: str,
        competicao: Competition,
        temporada: Season,
        casa: Team,
        fora: Team,
        quando: datetime,
        regime: CompetitionRegime = _REGIME,
        fase: StageType = StageType.LEAGUE,
    ) -> Match:
        return Match(
            id=MatchId.derive("e2e", chave),
            competition_id=competicao.id,
            season_id=temporada.id,
            regime=regime,
            stage=Stage(type=fase, round_number=5 if fase is StageType.LEAGUE else None),
            home_team_id=casa.id,
            away_team_id=fora.id,
            scheduled_kickoff=instant(quando),
            lifecycle=MatchLifecycle.RECONCILED,
        )

    jogos = (
        partida(
            "city-arsenal",
            liga,
            temporada_liga,
            city,
            arsenal,
            datetime(2024, 9, 14, 15, 0, tzinfo=UTC),
        ),
        partida(
            "chelsea-liverpool",
            liga,
            temporada_liga,
            chelsea,
            liverpool,
            datetime(2024, 9, 14, 17, 30, tzinfo=UTC),
        ),
        # OS DOIS DO §25: mesmos times, mesmo dia, mesma hora, competições
        # diferentes.
        partida(
            "arsenal-chelsea-liga",
            liga,
            temporada_liga,
            arsenal,
            chelsea,
            datetime(2024, 10, 1, 20, 0, tzinfo=UTC),
        ),
        partida(
            "arsenal-chelsea-copa",
            copa,
            temporada_copa,
            arsenal,
            chelsea,
            datetime(2024, 10, 1, 20, 0, tzinfo=UTC),
            regime=_REGIME_COPA,
            fase=StageType.LEAGUE_PHASE,
        ),
    )

    # OS HOMÔNIMOS DO §26: mesmo nome normalizado, nascimento e clube
    # diferentes. Registrá-los é o que permite provar que o motor NÃO os
    # funde — com um só, não haveria o que confundir.
    homonimo_a = Player(
        id=PlayerId.derive("e2e", "rodrigo-silva-1996"),
        canonical_name="Rodrigo Silva",
        date_of_birth=datetime(1996, 3, 12, tzinfo=UTC).date(),
    )
    homonimo_b = Player(
        id=PlayerId.derive("e2e", "rodrigo-silva-2001"),
        canonical_name="Rodrigo Silva",
        date_of_birth=datetime(2001, 7, 30, tzinfo=UTC).date(),
    )

    corpus = Corpus(
        competitions=(liga, copa),
        seasons=(temporada_liga, temporada_copa),
        # OS CLUBES ENTRAM PELO CORPUS, e não por um `INSERT` do teste: a
        # ordem importa porque `player_team_tenures` e `matches` referenciam
        # `teams`, e semear fora de ordem viola a chave estrangeira — que é o
        # banco fazendo exatamente o trabalho dele.
        teams=tuple(
            TimeSintetico(team=t, competition=CompetitionCode.PREMIER_LEAGUE, alias="")
            for t in (city, arsenal, chelsea, liverpool)
        ),
        aliases=(
            _alias(city.id, "Man City"),
            _alias(city.id, "Man. City"),
        ),
        players=(homonimo_a, homonimo_b),
        tenures=(
            PlayerTeamTenure(
                player_id=homonimo_a.id,
                team_id=city.id,
                valid_from=instant(datetime(2020, 7, 1, tzinfo=UTC)),
                valid_to=None,
            ),
            PlayerTeamTenure(
                player_id=homonimo_b.id,
                team_id=chelsea.id,
                valid_from=instant(datetime(2022, 7, 1, tzinfo=UTC)),
                valid_to=None,
            ),
        ),
        matches=jogos,
    )
    return corpus, (city, arsenal, chelsea, liverpool)


# ------------------------------------------------------------------ fontes --

_CAMPOS_BASE: tuple[SourceFieldMapping, ...] = (
    SourceFieldMapping(column="Competition", role=SemanticRole.COMPETITION_NAME),
    SourceFieldMapping(column="Season", role=SemanticRole.SEASON_LABEL),
    SourceFieldMapping(column="Kickoff", role=SemanticRole.KICKOFF),
    SourceFieldMapping(column="Home", role=SemanticRole.HOME_TEAM_NAME),
    SourceFieldMapping(column="Away", role=SemanticRole.AWAY_TEAM_NAME),
)

CAMPOS_A: tuple[SourceFieldMapping, ...] = (
    *_CAMPOS_BASE,
    SourceFieldMapping(column="HG", role=SemanticRole.HOME_SCORE),
    SourceFieldMapping(column="AG", role=SemanticRole.AWAY_SCORE),
    SourceFieldMapping(column="HShots", role=SemanticRole.HOME_SHOTS),
    SourceFieldMapping(column="HCorners", role=SemanticRole.HOME_CORNERS),
)
CAMPOS_B: tuple[SourceFieldMapping, ...] = (
    *_CAMPOS_BASE,
    SourceFieldMapping(column="HG", role=SemanticRole.HOME_SCORE),
    SourceFieldMapping(column="HShots", role=SemanticRole.HOME_SHOTS),
    SourceFieldMapping(column="HomeXG", role=SemanticRole.HOME_XG),
    SourceFieldMapping(column="HomeShape", role=SemanticRole.HOME_FORMATION),
)
CAMPOS_C: tuple[SourceFieldMapping, ...] = (
    *_CAMPOS_BASE,
    SourceFieldMapping(column="Book", role=SemanticRole.BOOKMAKER_NAME),
    SourceFieldMapping(column="OddsH", role=SemanticRole.ODDS_HOME),
    SourceFieldMapping(column="OddsD", role=SemanticRole.ODDS_DRAW),
    SourceFieldMapping(column="OddsA", role=SemanticRole.ODDS_AWAY),
)

#: `Man City` (alias) na A, nome canônico na B e na C — e o `FC` da B é
#: dobrado pelo normalizador, então ela também entra por chave exata. As três
#: grafias, três caminhos, um `TeamId` (§16).
FONTE_A = (
    b"Competition,Season,Kickoff,Home,Away,HG,AG,HShots,HCorners\n"
    b"Premier League,2024/25,2024-09-14T15:00:00+00:00,Man City,Arsenal,2,1,14,7\n"
    b"Premier League,2024/25,2024-09-14T17:30:00+00:00,Chelsea,Liverpool,0,0,9,3\n"
    b"Premier League,2024/25,2024-10-01T20:00:00+00:00,Arsenal,Chelsea,1,1,11,5\n"
)

#: Kickoff com DRIFT de dez minutos — dentro da tolerância exata de quinze
#: (§15), e rótulo de temporada noutro formato (`2024-2025`).
#:
#: SÓ O MANCHESTER CITY LEVA `FC`, e a razão é o normalizador: ele só dobra o
#: sufixo societário quando SOBRAM DUAS PALAVRAS. `Manchester City FC` vira
#: `manchester city`; `Arsenal FC` continua `arsenal fc`, porque dobrá-lo
#: deixaria uma palavra só — e é essa guarda que preserva `Sporting CP`. Pôr
#: `Arsenal FC` aqui não testaria a fusão: testaria a recusa do normalizador,
#: que já tem teste de unidade e que está CERTA.
FONTE_B = (
    b"Competition,Season,Kickoff,Home,Away,HG,HShots,HomeXG,HomeShape\n"
    b"Premier League,2024-2025,2024-09-14T15:10:00+00:00,"
    b"Manchester City FC,Arsenal,2,16,2.31,4-3-3\n"
    b"Premier League,2024-2025,2024-09-14T17:35:00+00:00,"
    b"Chelsea,Liverpool,0,10,0.84,4-2-3-1\n"
)

#: Odds de DUAS casas para a mesma partida, MAIS uma linha repetida.
#:
#: AS TRÊS LINHAS SÃO O CONTRATO DO PR-03.2 EM MINIATURA:
#:
#:     BET365   @ 2.00     observação
#:     PINNACLE @ 2.05     OUTRA observação — não é a mesma fonte falando duas
#:                         vezes, e as duas são verdade ao mesmo tempo (§7)
#:     BET365   @ 2.00     MESMA casa, MESMO payload — duplicata de verdade,
#:                         e é ela que continua sendo deduplicada (§11)
FONTE_C = (
    b"Competition,Season,Kickoff,Home,Away,Book,OddsH,OddsD,OddsA\n"
    b"Premier League,2024/25,2024-09-14T15:00:00+00:00,Manchester City,Arsenal,"
    b"BET365,2.00,3.40,3.60\n"
    b"Premier League,2024/25,2024-09-14T15:00:00+00:00,Manchester City,Arsenal,"
    b"PINNACLE,2.05,3.35,3.55\n"
    b"Premier League,2024/25,2024-09-14T15:00:00+00:00,Manchester City,Arsenal,"
    b"BET365,2.00,3.40,3.60\n"
)

#: O CASO NEGATIVO DO §25. Mesmos times, mesmo instante, competição outra.
FONTE_COPA = (
    b"Competition,Season,Kickoff,Home,Away,HG,AG,HShots,HCorners\n"
    b"UEFA Champions League,2024/25,2024-10-01T20:00:00+00:00,Arsenal,Chelsea,3,2,15,8\n"
)


@pytest.fixture
async def cenario(database: Database, object_store: Any) -> tuple[Pipeline, Any]:
    corpus, times = _cenario()
    await limpar_execucoes(database)
    await seed_corpus(database, corpus)
    if hasattr(object_store, "ensure_bucket"):
        await object_store.ensure_bucket()
    pipeline = Pipeline(database, object_store, batch_size=500)
    return pipeline, (corpus, times)


async def _resolver_tres_fontes(pipeline: Pipeline) -> tuple[list[str], list[Any]]:
    execucoes: list[str] = []
    datasets: list[Any] = []
    for provedor, conteudo, campos, licenca in (
        (A, FONTE_A, CAMPOS_A, LicenseClass.PUBLIC_DOMAIN),
        (B, FONTE_B, CAMPOS_B, LicenseClass.ATTRIBUTION_REQUIRED),
        # A FONTE C É A MAIS RESTRITIVA. O candidato fundido precisa herdar a
        # licença DELA — não a da fonte que venceu mais campos (§76).
        (C, FONTE_C, CAMPOS_C, LicenseClass.RESEARCH_ONLY),
    ):
        dataset = await pipeline.stage(
            name=f"e2e-{provedor}",
            content=conteudo,
            provider=provedor,
            license_class=licenca,
        )
        await pipeline.map_source(
            dataset,
            provider=provedor,
            fields=campos,
            conventions={"season_convention": SeasonConvention.SPLIT_YEAR.value},
        )
        execucoes.append((await pipeline.resolve(dataset.id)).run.id)
        datasets.append(dataset)
    return execucoes, datasets


class TestConvergenciaDeIdentidade:
    async def test_tres_grafias_terminam_no_mesmo_match_id(
        self, cenario: tuple[Pipeline, Any], database: Database
    ) -> None:
        """§16 e §18: `Man City`, `Manchester City FC` e `Manchester City`.

        PROVADO PELO `MatchId`, e não inferido do fato de a fusão ter formado
        um grupo. Um grupo pode se formar por acidente de agrupamento; o id
        canônico gravado em três decisões de três provedores diferentes não.
        """
        pipeline, _ = cenario
        execucoes, _ = await _resolver_tres_fontes(pipeline)

        async with database.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT provider_id, source_raw, canonical_entity_id
                FROM resolution_decisions
                WHERE run_id = ANY($1::uuid[]) AND subject_type = 'TEAM'
                  AND status = 'RESOLVED' AND canonical_entity_id = $2
                ORDER BY provider_id
                """,
                [_uuid.UUID(r) for r in execucoes],
                TeamId.derive("e2e", "Manchester City").value,
            )
        grafias = {linha["source_raw"] for linha in linhas}
        ids = {linha["canonical_entity_id"] for linha in linhas}
        # A CONSULTA VAI PELO ID, e não pelo texto: `Man City` normaliza para
        # `man city`, que não contém `manchester`. Filtrar por texto acharia
        # duas das três grafias e o teste passaria provando menos.
        assert len(grafias) >= 3, f"o cenário não trouxe três grafias: {grafias}"
        assert len(ids) == 1, f"as grafias resolveram para {len(ids)} clubes: {ids}"

        async with database.acquire() as conexao:
            partidas = await conexao.fetch(
                """
                SELECT provider_id, canonical_entity_id
                FROM resolution_decisions
                WHERE run_id = ANY($1::uuid[]) AND subject_type = 'MATCH'
                  AND status = 'RESOLVED' AND record_ref LIKE '%:2'
                """,
                [_uuid.UUID(r) for r in execucoes],
            )
        # A PRIMEIRA LINHA DE CADA ARQUIVO É A MESMA PARTIDA (City x Arsenal).
        # As três fontes precisam apontar para o mesmo id.
        provedores = {linha["provider_id"] for linha in partidas}
        alvos = {linha["canonical_entity_id"] for linha in partidas}
        assert provedores == {str(A), str(B), str(C)}, provedores
        assert len(alvos) == 1, f"as três fontes acharam {len(alvos)} partidas"

    async def test_competicao_diferente_nao_funde(
        self, cenario: tuple[Pipeline, Any], database: Database
    ) -> None:
        """§25: Arsenal x Chelsea na liga e na copa são DOIS jogos.

        MESMOS TIMES, MESMA DATA, MESMO HORÁRIO. A única coisa que os separa é
        a competição — e é por isso que ela é evidência DURA na política. Sem
        essa trava, o histórico teria metade dos jogos e o dobro dos gols em
        cada um deles.
        """
        pipeline, _ = cenario
        execucoes, _ = await _resolver_tres_fontes(pipeline)

        copa = await pipeline.stage(
            name="e2e-copa", content=FONTE_COPA, provider=ProviderId("fonte_copa")
        )
        await pipeline.map_source(
            copa,
            provider=ProviderId("fonte_copa"),
            fields=CAMPOS_A,
            conventions={"season_convention": SeasonConvention.SPLIT_YEAR.value},
        )
        da_copa = await pipeline.resolve(copa.id)

        async with database.acquire() as conexao:
            liga = await conexao.fetchval(
                """
                SELECT canonical_entity_id FROM resolution_decisions
                WHERE run_id = ANY($1::uuid[]) AND subject_type = 'MATCH'
                  AND status = 'RESOLVED' AND record_ref LIKE '%:4'
                """,
                [_uuid.UUID(r) for r in execucoes],
            )
            na_copa = await conexao.fetchval(
                """
                SELECT canonical_entity_id FROM resolution_decisions
                WHERE run_id = $1 AND subject_type = 'MATCH' AND status = 'RESOLVED'
                """,
                _uuid.UUID(da_copa.run.id),
            )
        assert liga is not None, "a partida da liga não resolveu"
        assert na_copa is not None, "a partida da copa não resolveu"
        assert liga != na_copa, (
            "a partida da liga e a da copa resolveram para o mesmo id — dois jogos viraram um"
        )

    async def test_homonimos_nao_se_fundem_contra_o_registro_real(
        self, cenario: tuple[Pipeline, Any], database: Database
    ) -> None:
        """§26: dois `Rodrigo Silva`, e o motor recusa escolher.

        CONTRA O REGISTRO REAL, e não contra um contexto montado à mão: os
        dois jogadores e os dois vínculos vêm do PostgreSQL, pelas MESMAS
        consultas em massa que a resolução usa.

        A CHAMADA É DIRETA AO RESOLVER porque `RunIdentityResolution` não tem
        etapa de jogador — a cadeia dele é competição → temporada → time →
        partida. Isso está reportado como dívida do PR-03; o que este teste
        prova é a propriedade que importa e que é comprovável hoje: com o
        registro de verdade carregado, o resolver NÃO funde os dois.
        """
        from sports_intelligence.adapters.postgres.resolution import (
            PostgresCanonicalRegistry,
        )

        registro = PostgresCanonicalRegistry(database)
        normalizado = _NORMALIZADOR.normalize("Rodrigo Silva")
        jogadores = await registro.players_by_normalized_names([normalizado])
        vinculos = await registro.tenures_of([str(j.id) for j in jogadores])
        assert len(jogadores) == 2, f"o cenário precisa de dois homônimos: {jogadores}"

        contexto = (
            ContextBuilder(_NORMALIZADOR, instant(datetime(2024, 9, 14, tzinfo=UTC)))
            .with_players(tuple(jogadores), tuple(vinculos))
            .build()
        )
        bundle = ResolverBundle.build(_NORMALIZADOR)
        resultado = bundle.player.resolve(
            NormalizedName.of("Rodrigo Silva", _NORMALIZADOR),
            context=contexto,
            policy=DEFAULT_RESOLUTION_POLICY,
        )
        assert resultado.status is not ResolutionStatus.RESOLVED, (
            "dois jogadores com o mesmo nome e nascimentos diferentes foram fundidos"
        )
        assert resultado.status in {
            ResolutionStatus.AMBIGUOUS,
            ResolutionStatus.REVIEW_REQUIRED,
            ResolutionStatus.UNRESOLVED,
        }


class TestFusaoMultiFonte:
    async def test_campos_das_tres_fontes_no_mesmo_candidato(
        self, cenario: tuple[Pipeline, Any], database: Database
    ) -> None:
        """§19, §21, §22: cada fonte contribui, e o conflito sobrevive."""
        pipeline, _ = cenario
        execucoes, _ = await _resolver_tres_fontes(pipeline)
        saida = await pipeline.fuse(execucoes)

        assert saida.run.counts.groups > 0, "a fusão não recebeu registro nenhum"
        multi = [c for c in saida.candidates if len(c.fields) > 0]
        assert multi

        # A PARTIDA QUE AS TRÊS FONTES TÊM.
        alvo = max(
            saida.candidates,
            key=lambda c: len({s.provider_id for f in c.fields for s in f.contributions}),
        )
        provedores = {str(s.provider_id) for f in alvo.fields for s in f.contributions}
        por_campo = {f.field_name.value: f for f in alvo.fields}

        # §21 — CONCORDÂNCIA: A e B dizem 2, e as DUAS ficam registradas.
        placar = por_campo.get(SemanticRole.HOME_SCORE.value)
        assert placar is not None
        assert placar.rule is FusionRule.EXACT_AGREEMENT, placar.rule
        assert placar.selected_value == "2"
        assert len({str(s.provider_id) for s in placar.contributions}) >= 2

        # §22 — CONFLITO: A diz 14 chutes, B diz 16. A política de
        # `HOME_SHOTS` é `GLOBAL_PRECEDENCE`, então há valor escolhido E a
        # alternativa continua lá. Se fosse `KEEP_UNRESOLVED`, o campo ficaria
        # sem valor — e as duas saídas são corretas; o que não pode é o outro
        # valor sumir.
        chutes = por_campo.get(SemanticRole.HOME_SHOTS.value)
        assert chutes is not None
        assert len(chutes.contributions) >= 2, "a contribuição divergente sumiu"
        valores = {s.value for s in chutes.contributions}
        assert {"14", "16"} <= valores, valores
        if chutes.rule is FusionRule.CONFLICT_UNRESOLVED:
            assert chutes.selected_value is None
        else:
            assert chutes.selected_value in valores

        # §19 — COBERTURA: o que só uma fonte trouxe entra sem conflito.
        assert SemanticRole.HOME_XG.value in por_campo
        assert SemanticRole.HOME_FORMATION.value in por_campo
        assert SemanticRole.HOME_CORNERS.value in por_campo
        assert provedores >= {str(A), str(B)}

    async def test_duas_casas_da_mesma_fonte_sobrevivem(
        self, cenario: tuple[Pipeline, Any]
    ) -> None:
        """§10: `mesma fonte` NÃO implica `mesma observação`.

        O DEFEITO QUE ISTO FECHA. Até o PR-03.1, duas linhas da mesma fonte
        para a mesma partida eram tratadas como duplicata interna e a segunda
        era descartada — então uma fonte que publica uma linha por casa de
        apostas perdia todas menos a primeira. Nada era promediado, e mesmo
        assim a dispersão entre casas — que é O sinal — sumia.

        A regra de duplicata interna continua certa para FUSÃO ESCALAR: duas
        linhas dizendo o placar são a mesma fonte falando duas vezes. O que
        mudou é que ela deixou de valer para CONJUNTO DE OBSERVAÇÕES, onde a
        identidade inclui a casa de apostas.
        """
        pipeline, _ = cenario
        execucoes, _ = await _resolver_tres_fontes(pipeline)
        saida = await pipeline.fuse(execucoes)

        cotacoes = [
            observacao
            for candidato in saida.candidates
            for conjunto in candidato.observation_sets
            for observacao in conjunto.observations
        ]
        assert len(cotacoes) == 2, [o.discriminator for o in cotacoes]

        casas = {o.discriminator.split("|")[1] for o in cotacoes}
        assert casas == {"BET365", "PINNACLE"}, casas

        precos = {o.values[SemanticRole.ODDS_HOME.value] for o in cotacoes}
        assert precos == {"2.00", "2.05"}, precos
        # A MÉDIA NUNCA EXISTIU E CONTINUA NÃO EXISTINDO: `2.025` é um preço
        # que casa nenhuma ofereceu.
        assert "2.025" not in precos

        # §83 — CADA OBSERVAÇÃO APONTA PARA A PRÓPRIA LINHA. Colapsar as duas
        # procedências numa só seria inventar uma linha que não existe.
        referencias = {str(o.record_ref) for o in cotacoes}
        assert len(referencias) == 2, referencias

    async def test_linha_repetida_da_mesma_casa_continua_sendo_duplicata(
        self, cenario: tuple[Pipeline, Any]
    ) -> None:
        """§11: identidade repetida ainda é deduplicada.

        É A METADE QUE IMPEDE A CORREÇÃO DE VIRAR O DEFEITO OPOSTO. Se
        `mesma fonte ≠ mesma observação` virasse `toda linha é uma
        observação`, um arquivo com a mesma cotação repetida contaria duas
        vezes — e a contagem de casas, que é o insumo do Odds Intelligence,
        passaria a mentir para cima.

        A terceira linha da fonte C é a primeira repetida: mesma casa, mesmo
        mercado, mesmo payload. Ela é descartada, e o descarte é REPORTADO.
        """
        pipeline, _ = cenario
        execucoes, _ = await _resolver_tres_fontes(pipeline)
        saida = await pipeline.fuse(execucoes)

        assert saida.discarded == 1, (
            f"{saida.discarded} descartes: a linha repetida da BET365 precisa ser "
            "exatamente uma, e precisa aparecer na contagem"
        )
        cotacoes = [
            o
            for c in saida.candidates
            for conjunto in c.observation_sets
            for o in conjunto.observations
        ]
        assert len(cotacoes) == 2


class TestLinhagem:
    async def test_do_campo_fundido_ate_o_sha256_do_objeto_bruto(
        self, cenario: tuple[Pipeline, Any], database: Database
    ) -> None:
        """§23: campo → linha → arquivo → dataset → manifesto → bytes.

        A TRAVESSIA INTEIRA, e o último passo confere o SHA-256 do objeto que
        está no object store contra o hash gravado no intake. Sem esse último
        passo, «a linhagem existe» seria uma afirmação sobre ponteiros que
        ninguém seguiu até o fim.
        """
        pipeline, _ = cenario
        execucoes, datasets = await _resolver_tres_fontes(pipeline)
        saida = await pipeline.fuse(execucoes)

        contribuicoes = [
            (campo, fonte)
            for candidato in saida.candidates
            for campo in candidato.fields
            for fonte in campo.contributions
        ]
        assert len(contribuicoes) >= 3, "linhagem insuficiente para provar travessia"

        conferidos = 0
        for _campo, fonte in contribuicoes[:3]:
            referencia = fonte.record_ref
            dataset = next(d for d in datasets if d.id == referencia.dataset_id)
            arquivo = next(f for f in dataset.stored_files if str(f.id) == referencia.file_id)

            # O ARQUIVO BRUTO, LIDO DO OBJECT STORE, E O HASH RECALCULADO.
            digestor = hashlib.sha256()
            async for bloco in pipeline.archive.open(arquivo):
                digestor.update(bloco)
            assert digestor.hexdigest() == arquivo.content_hash.value, (
                f"os bytes de {arquivo.filename} não batem com o hash do intake"
            )

            # E A IMPRESSÃO DO MANIFESTO, que fecha a linhagem do lado da
            # decisão: ela é o que liga a execução a ESTES bytes.
            manifesto = await pipeline.manifests.latest_for(dataset.id)
            assert manifesto is not None
            assert any(a.sha256 == arquivo.content_hash for a in manifesto.files), (
                "o manifesto não contém o arquivo de onde o campo veio"
            )
            assert referencia.record_number >= 1
            conferidos += 1

        assert conferidos == 3


class TestReprocessamento:
    async def test_execucao_anterior_permanece_intacta(
        self, cenario: tuple[Pipeline, Any], database: Database
    ) -> None:
        """§28: a segunda execução não toca na primeira.

        É A PROPRIEDADE QUE TORNA A COMPARAÇÃO POSSÍVEL. Se a execução nova
        reescrevesse a antiga, «o que o resolver novo passou a enxergar» seria
        uma pergunta sem resposta — a única referência teria sido apagada
        pela própria mudança.
        """
        pipeline, _ = cenario
        execucoes, _ = await _resolver_tres_fontes(pipeline)
        primeira = execucoes[0]

        async with database.acquire() as conexao:
            antes = await conexao.fetch(
                "SELECT id, status, confidence, canonical_entity_id, decided_at "
                "FROM resolution_decisions WHERE run_id = $1 ORDER BY id",
                _uuid.UUID(primeira),
            )
        assert antes

        anterior = await pipeline.resolution.get_resolution_run.execute(primeira)
        de_novo = await pipeline.resolve(anterior.dataset_id)
        assert de_novo.run.id != primeira

        async with database.acquire() as conexao:
            depois = await conexao.fetch(
                "SELECT id, status, confidence, canonical_entity_id, decided_at "
                "FROM resolution_decisions WHERE run_id = $1 ORDER BY id",
                _uuid.UUID(primeira),
            )
        assert [tuple(linha) for linha in antes] == [tuple(linha) for linha in depois]

        # E a fusão idem: fundir de novo produz execução nova.
        uma = await pipeline.fuse(execucoes)
        outra = await pipeline.fuse(execucoes)
        assert uma.run.id != outra.run.id
        # MESMA ENTRADA, MESMA IMPRESSÃO. É o que prova que a saída é
        # reproduzível e que a execução nova não mudou nada por acidente.
        assert uma.run.output_fingerprint == outra.run.output_fingerprint
        preservada = await pipeline.resolution.get_fusion_run.execute(uma.run.id)
        assert preservada.counts.groups == uma.run.counts.groups
