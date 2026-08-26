"""Os dois caminhos que existiam no código e não existiam na execução.

O QUE O BENCHMARK DO PR-03.1 PROVOU, e é a razão deste arquivo:

    players_normalizado_idx            0 usos
    players_dob_idx                    0 usos
    provider_entity_mappings (todos)   0 usos

Um índice com zero usos sobre uma consulta que deveria acontecer é o sintoma
de que ela não acontece. `PlayerResolver` tinha código e teste de unidade e
NENHUM chamador na cadeia de `RunIdentityResolution`; `ProviderEntityMapping`
era declarado como «a memória explícita das decisões» e a execução em lote
nunca passava `provider_ref` ao resolver.

Cada teste aqui atravessa o CASO DE USO REAL contra PostgreSQL real. Nenhum
chama o resolver na mão — chamar o resolver na mão é exatamente o que os
testes de unidade já faziam quando o caminho operacional estava morto.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, date, datetime
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
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.players.models import Player, PlayerTeamTenure
from sports_intelligence.domain.resolution.decisions import (
    ResolutionMethod,
    ResolutionStatus,
    SubjectType,
)
from sports_intelligence.domain.shared.identity import (
    MatchId,
    PlayerId,
    ProviderId,
    TeamId,
)
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.sources.mapping import SeasonConvention, SourceFieldMapping
from sports_intelligence.domain.sources.semantics import SemanticRole
from sports_intelligence.domain.teams.models import Team
from sports_intelligence.ingestion.normalization.names import NameNormalizer
from tests.support.corpus import Corpus, TimeSintetico
from tests.support.pipeline import SERVICO, Pipeline
from tests.support.registry_seed import limpar_execucoes, seed_corpus

pytestmark = pytest.mark.integration

FONTE = ProviderId("fonte_com_ids")
_NORMALIZADOR = NameNormalizer()
_REGIME = CompetitionRegime(
    code=RegimeCode.DOUBLE_ROUND_ROBIN,
    effective_from=instant(datetime(1990, 1, 1, tzinfo=UTC)),
    regulation_version="e2e-v1",
)

#: OS NOMES DE CLUBE E DE JOGADOR SÃO EXCLUSIVOS DESTE ARQUIVO. O registro
#: canônico é preservado entre testes (§49) — é o que torna a semeadura barata
#: —, então dois arquivos que registrem `Manchester City` com ids derivados de
#: sementes diferentes criam DOIS clubes com o mesmo nome normalizado. A
#: resolução, corretamente, recusa escolher entre eles, e o teste falha por
#: colisão de cenário em vez de por defeito.

#: Os ids que a fonte usa. Curtos e legíveis de propósito: quando um teste
#: falha, `time-123` no diff diz mais que um `uuid`.
REF_CITY = "time-123"
REF_ARSENAL = "time-456"
REF_JOGADOR = "jogador-777"

#: O NOME É PROPOSITALMENTE RUIM (§25). Se o teste passasse com um nome bom,
#: ele estaria provando alias ou chave canônica — não mapeamento de provedor.
#: Com este texto, resolver por nome é impossível, e resolver mesmo assim só
#: pode ter vindo do id.
NOME_RUIM_CITY = "xxq zzt clube 998877"
NOME_RUIM_ARSENAL = "vvk ppl clube 112233"
NOME_RUIM_JOGADOR = "zzq wwy jogador 445566"


def _time(nome: str) -> Team:
    return Team(id=TeamId.derive("e2e-ids", nome), canonical_name=nome, country="GB")


def _cenario() -> tuple[Corpus, dict[str, Any]]:
    liga = Competition.from_code(CompetitionCode.PREMIER_LEAGUE)
    temporada = Season.create(
        competition_id=liga.id,
        label="2024/25",
        starts_at=instant(datetime(2024, 8, 1, tzinfo=UTC)),
        ends_at=instant(datetime(2025, 5, 31, tzinfo=UTC)),
        regime=_REGIME,
    )
    city = _time("Northtown City")
    arsenal = _time("Eastport Rovers")
    chelsea = _time("Southgate Athletic")

    partida = Match(
        id=MatchId.derive("e2e-ids", "city-arsenal"),
        competition_id=liga.id,
        season_id=temporada.id,
        regime=_REGIME,
        stage=Stage(type=StageType.LEAGUE, round_number=5),
        home_team_id=city.id,
        away_team_id=arsenal.id,
        scheduled_kickoff=instant(datetime(2024, 9, 14, 15, 0, tzinfo=UTC)),
        lifecycle=MatchLifecycle.RECONCILED,
    )

    # OS DOIS HOMÔNIMOS DO §17/§18. Mesmo nome normalizado, nascimentos e
    # clubes diferentes — e é a diferença que o motor precisa enxergar sem
    # nunca fundi-los por nome.
    silva_96 = Player(
        id=PlayerId.derive("e2e-ids", "silva-96"),
        canonical_name="Adriano Moretti",
        date_of_birth=date(1998, 2, 10),
    )
    silva_01 = Player(
        id=PlayerId.derive("e2e-ids", "silva-01"),
        canonical_name="Adriano Moretti",
        date_of_birth=date(2001, 7, 17),
    )
    mapeado = Player(
        id=PlayerId.derive("e2e-ids", "mapeado"),
        canonical_name="Jogador Com Id Conhecido",
        date_of_birth=date(1995, 5, 5),
    )

    corpus = Corpus(
        competitions=(liga,),
        seasons=(temporada,),
        teams=tuple(
            TimeSintetico(team=t, competition=CompetitionCode.PREMIER_LEAGUE, alias="")
            for t in (city, arsenal, chelsea)
        ),
        aliases=(),
        players=(silva_96, silva_01, mapeado),
        tenures=(
            # `silva_96` no Northtown NA JANELA da partida; `silva_01` no Southgate.
            # É o vínculo NA DATA que separa os dois (§19).
            PlayerTeamTenure(
                player_id=silva_96.id,
                team_id=city.id,
                valid_from=instant(datetime(2023, 7, 1, tzinfo=UTC)),
                valid_to=None,
            ),
            PlayerTeamTenure(
                player_id=silva_01.id,
                team_id=chelsea.id,
                valid_from=instant(datetime(2023, 7, 1, tzinfo=UTC)),
                valid_to=None,
            ),
        ),
        matches=(partida,),
    )
    return corpus, {
        "city": city,
        "arsenal": arsenal,
        "chelsea": chelsea,
        "silva_96": silva_96,
        "silva_01": silva_01,
        "mapeado": mapeado,
        "partida": partida,
    }


CAMPOS: tuple[SourceFieldMapping, ...] = (
    SourceFieldMapping(column="Competition", role=SemanticRole.COMPETITION_NAME),
    SourceFieldMapping(column="Season", role=SemanticRole.SEASON_LABEL),
    SourceFieldMapping(column="Kickoff", role=SemanticRole.KICKOFF),
    SourceFieldMapping(column="Home", role=SemanticRole.HOME_TEAM_NAME),
    SourceFieldMapping(column="Away", role=SemanticRole.AWAY_TEAM_NAME),
    SourceFieldMapping(column="HomeId", role=SemanticRole.HOME_TEAM_PROVIDER_ID),
    SourceFieldMapping(column="AwayId", role=SemanticRole.AWAY_TEAM_PROVIDER_ID),
    SourceFieldMapping(column="Player", role=SemanticRole.PLAYER_NAME),
    SourceFieldMapping(column="PlayerDOB", role=SemanticRole.PLAYER_DOB, date_format="%Y-%m-%d"),
    SourceFieldMapping(column="PlayerId", role=SemanticRole.PLAYER_PROVIDER_ID),
    SourceFieldMapping(column="Club", role=SemanticRole.TEAM_NAME),
)

_CABECALHO = b"Competition,Season,Kickoff,Home,Away,HomeId,AwayId,Player,PlayerDOB,PlayerId,Club\n"
_PREFIXO = b"Premier League,2024/25,2024-09-14T15:00:00+00:00,"

#: Linha 2 — TIME POR ID. Os dois nomes de clube são impronunciáveis; se o
#: `TeamId` sair certo, ele só pode ter vindo do mapeamento.
#: O jogador tem nome, nascimento e clube: resolve com evidência sobrando.
LINHA_MAPEADA = (
    NOME_RUIM_CITY.encode()
    + b","
    + NOME_RUIM_ARSENAL.encode()
    + f",{REF_CITY},{REF_ARSENAL},".encode()
    + b"Adriano Moretti,1998-02-10,,Northtown City\n"
)

#: Linha 3 — JOGADOR SEM EVIDÊNCIA. Nome só, sem nascimento e sem clube, com
#: dois homônimos reais no registro. Não pode resolver (§18).
LINHA_AMBIGUA = b"Northtown City,Eastport Rovers,,," + b"Adriano Moretti,,,\n"

#: Linha 4 — JOGADOR POR ID, com nome ruim pelo mesmo motivo da linha 2.
LINHA_JOGADOR_MAPEADO = (
    b"Northtown City,Eastport Rovers,,,"
    + NOME_RUIM_JOGADOR.encode()
    + f",,{REF_JOGADOR},\n".encode()
)

ARQUIVO = (
    _CABECALHO
    + _PREFIXO
    + LINHA_MAPEADA
    + _PREFIXO
    + LINHA_AMBIGUA
    + _PREFIXO
    + (LINHA_JOGADOR_MAPEADO)
)


async def _gravar_mapeamentos(database: Database, entidades: dict[str, Any]) -> None:
    """Os mapeamentos que uma decisão anterior teria deixado.

    GRAVADOS POR `SQL` E NÃO PELO FLUXO DE REVISÃO porque o que este teste
    prova é o CONSUMO do mapeamento, não a produção dele — a produção já tem
    teste próprio no ciclo de revisão. Misturar os dois faria a falha de um
    parecer falha do outro.
    """
    async with database.acquire() as conexao:
        await conexao.executemany(
            """
            INSERT INTO provider_entity_mappings (
                id, provider_id, entity_type, provider_entity_id,
                canonical_entity_id, resolution_decision_id,
                valid_from, valid_to, created_at, created_by
            )
            VALUES ($1, $2, $3, $4, $5, $6, NULL, NULL, now(), 'e2e')
            ON CONFLICT (provider_id, entity_type, provider_entity_id)
                WHERE valid_to IS NULL
            DO NOTHING
            """,
            [
                (
                    _uuid.uuid4(),
                    str(FONTE),
                    SubjectType.TEAM.value,
                    REF_CITY,
                    entidades["city"].id.value,
                    _uuid.uuid4(),
                ),
                (
                    _uuid.uuid4(),
                    str(FONTE),
                    SubjectType.TEAM.value,
                    REF_ARSENAL,
                    entidades["arsenal"].id.value,
                    _uuid.uuid4(),
                ),
                (
                    _uuid.uuid4(),
                    str(FONTE),
                    SubjectType.PLAYER.value,
                    REF_JOGADOR,
                    entidades["mapeado"].id.value,
                    _uuid.uuid4(),
                ),
            ],
        )


@pytest.fixture
async def executado(database: Database, object_store: Any) -> tuple[Pipeline, dict[str, Any], str]:
    corpus, entidades = _cenario()
    await limpar_execucoes(database)
    await seed_corpus(database, corpus)
    await _gravar_mapeamentos(database, entidades)
    if hasattr(object_store, "ensure_bucket"):
        await object_store.ensure_bucket()

    pipeline = Pipeline(database, object_store, batch_size=500)
    dataset = await pipeline.stage(name="e2e-ids", content=ARQUIVO, provider=FONTE)
    await pipeline.map_source(
        dataset,
        provider=FONTE,
        fields=CAMPOS,
        conventions={"season_convention": SeasonConvention.SPLIT_YEAR.value},
    )
    saida = await pipeline.resolve(dataset.id)
    return pipeline, entidades, saida.run.id


async def _decisoes(database: Database, run_id: str, subject: SubjectType) -> list[dict[str, Any]]:
    async with database.acquire() as conexao:
        linhas = await conexao.fetch(
            """
            SELECT record_ref, source_raw, status, method, canonical_entity_id
            FROM resolution_decisions
            WHERE run_id = $1 AND subject_type = $2
            ORDER BY record_ref, source_raw
            """,
            _uuid.UUID(run_id),
            subject.value,
        )
    return [dict(linha) for linha in linhas]


class TestMapeamentoDeProvedor:
    async def test_time_resolve_pelo_id_e_nao_pelo_nome(
        self, executado: tuple[Pipeline, dict[str, Any], str], database: Database
    ) -> None:
        """§22, §25: o id do provedor é o caminho prioritário.

        O NOME DA LINHA É IMPRONUNCIÁVEL. Nenhum alias, nenhuma chave
        canônica e nenhuma similaridade chegam perto dele — então um
        `TeamId` correto na saída só pode ter vindo do mapeamento.
        """
        _, entidades, run_id = executado
        decisoes = await _decisoes(database, run_id, SubjectType.TEAM)
        por_mapeamento = [
            d for d in decisoes if d["method"] == ResolutionMethod.EXACT_PROVIDER_MAPPING.value
        ]
        assert por_mapeamento, (
            "nenhuma decisão de time veio de mapeamento de provedor — o caminho "
            "continua inalcançável pela execução em lote"
        )
        alvos = {d["canonical_entity_id"] for d in por_mapeamento}
        assert entidades["city"].id.value in alvos
        assert entidades["arsenal"].id.value in alvos
        assert all(d["status"] == ResolutionStatus.RESOLVED.value for d in por_mapeamento)
        # §82 — TODA DECISÃO CARREGA A LINHA DE ONDE SAIU.
        assert all(d["record_ref"] for d in por_mapeamento)

    async def test_jogador_tambem_resolve_por_id(
        self, executado: tuple[Pipeline, dict[str, Any], str], database: Database
    ) -> None:
        """§26: o mecanismo é por TIPO DE ENTIDADE, não hardcoded para time.

        Sem este teste, um `if subject is TEAM` escondido em algum lugar
        passaria despercebido — e a primeira fonte de jogadores com ids
        próprios descobriria isso em produção.
        """
        _, entidades, run_id = executado
        decisoes = await _decisoes(database, run_id, SubjectType.PLAYER)
        por_mapeamento = [
            d for d in decisoes if d["method"] == ResolutionMethod.EXACT_PROVIDER_MAPPING.value
        ]
        assert len(por_mapeamento) == 1, decisoes
        assert por_mapeamento[0]["canonical_entity_id"] == entidades["mapeado"].id.value
        assert por_mapeamento[0]["status"] == ResolutionStatus.RESOLVED.value

    async def test_o_tipo_do_id_canonico_e_concreto(
        self, executado: tuple[Pipeline, dict[str, Any], str]
    ) -> None:
        """§81: o defeito do `EntityId` genérico não pode voltar pelos caminhos novos.

        O adapter relê o id do banco e precisa devolver `PlayerId` para uma
        decisão de jogador — não a superclasse. `mypy` não pega, porque
        `EntityId` é supertipo; só a execução pega.
        """
        pipeline, _, run_id = executado
        decisoes, _ = await pipeline.resolution.list_decisions.execute(
            run_id, subject=SubjectType.PLAYER, limit=100
        )
        resolvidas = [d for d in decisoes if d.canonical_entity_id is not None]
        assert resolvidas
        assert all(isinstance(d.canonical_entity_id, PlayerId) for d in resolvidas), [
            type(d.canonical_entity_id).__name__ for d in resolvidas
        ]


class TestResolucaoDeJogador:
    async def test_o_resolver_de_jogador_e_alcancavel_pela_execucao(
        self, executado: tuple[Pipeline, dict[str, Any], str], database: Database
    ) -> None:
        """§13, §14: a prova de que a etapa existe na cadeia real.

        Até o PR-03.2, `RunIdentityResolution` ia de competição a partida e
        nunca passava por jogador. Zero decisões de `PLAYER` era o resultado —
        e nenhum teste falhava, porque nenhum teste olhava.
        """
        _, _, run_id = executado
        decisoes = await _decisoes(database, run_id, SubjectType.PLAYER)
        assert decisoes, "a execução não produziu decisão de jogador nenhuma"
        assert all(d["record_ref"] for d in decisoes)

    async def test_nome_nascimento_e_clube_na_data_resolvem(
        self, executado: tuple[Pipeline, dict[str, Any], str], database: Database
    ) -> None:
        """§17, §19: três evidências, e o clube é o DA DATA.

        `silva_96` está no Northtown desde 2023 e `silva_01` no Southgate. A
        linha diz `Northtown City` — e é o vínculo NA DATA DO JOGO, não o
        clube atual de ninguém, que aponta para um dos dois.

        OS NOMES DE CLUBE SÃO EXCLUSIVOS DESTE ARQUIVO de propósito. O
        registro canônico é preservado entre testes (§49), então reusar
        `Manchester City` faria este cenário e o do arquivo multi-fonte
        registrarem dois clubes com o mesmo nome normalizado e ids
        diferentes — e a resolução, corretamente, recusaria escolher entre
        eles. O teste falharia por colisão de cenário, não por defeito.
        """
        _, entidades, run_id = executado
        decisoes = await _decisoes(database, run_id, SubjectType.PLAYER)
        resolvidas = [
            d
            for d in decisoes
            if d["status"] == ResolutionStatus.RESOLVED.value
            and d["source_raw"] == "Adriano Moretti"
        ]
        assert len(resolvidas) == 1, decisoes
        assert resolvidas[0]["canonical_entity_id"] == entidades["silva_96"].id.value
        assert resolvidas[0]["method"] != ResolutionMethod.EXACT_PROVIDER_MAPPING.value

    async def test_homonimo_sem_evidencia_nao_resolve(
        self, executado: tuple[Pipeline, dict[str, Any], str], database: Database
    ) -> None:
        """§18: nome sozinho NUNCA resolve, mesmo na cadeia real.

        É a assimetria que governa o motor inteiro: um `PlayerId` errado
        contamina influência, força de elenco e grafo tático de forma que não
        se detecta depois, porque tudo continua somando.
        """
        _, _, run_id = executado
        decisoes = await _decisoes(database, run_id, SubjectType.PLAYER)
        sem_evidencia = [
            d
            for d in decisoes
            if d["source_raw"] == "Adriano Moretti"
            and d["status"] != ResolutionStatus.RESOLVED.value
        ]
        assert sem_evidencia, decisoes
        assert all(
            d["status"]
            in {
                ResolutionStatus.AMBIGUOUS.value,
                ResolutionStatus.REVIEW_REQUIRED.value,
                ResolutionStatus.UNRESOLVED.value,
            }
            for d in sem_evidencia
        )
        assert all(d["canonical_entity_id"] is None for d in sem_evidencia)


class TestFalhaNoMeioDoStreaming:
    async def test_falha_no_terceiro_lote_nao_produz_execucao_concluida(
        self, database: Database, object_store: Any
    ) -> None:
        """§45, §80: streaming não pode fazer o status mentir.

        O RISCO QUE O CONSUMO PREGUIÇOSO INTRODUZ. Com a lista inteira
        materializada antes de começar, uma falha de leitura acontecia ANTES
        da execução existir. Lendo lote a lote, ela passa a acontecer no MEIO
        — com decisões já gravadas e uma execução aberta.

        O QUE NÃO PODE ACONTECER é a execução terminar `COMPLETED`. As
        decisões já gravadas ficam (a tabela é append-only e elas são
        verdadeiras: aquelas linhas foram mesmo resolvidas), mas a EXECUÇÃO
        precisa dizer que falhou — senão a fusão a aceitaria como entrada
        utilizável e produziria um candidato que parece completo e não é.
        """
        from collections.abc import Iterator

        from sports_intelligence.domain.sources.records import SourceBatch

        corpus, _ = _cenario()
        await limpar_execucoes(database)
        await seed_corpus(database, corpus)
        if hasattr(object_store, "ensure_bucket"):
            await object_store.ensure_bucket()

        pipeline = Pipeline(database, object_store, batch_size=1)
        dataset = await pipeline.stage(
            name="e2e-falha", content=ARQUIVO, provider=ProviderId("fonte_falha")
        )
        await pipeline.map_source(
            dataset,
            provider=ProviderId("fonte_falha"),
            fields=CAMPOS,
            conventions={"season_convention": SeasonConvention.SPLIT_YEAR.value},
        )
        mapeamento = await pipeline.resolution.source_mappings.active_for(dataset.id)
        assert mapeamento is not None
        completo = [
            lote
            async for lote in __import__(
                "apps.resolution_composition", fromlist=["read_batches"]
            ).read_batches(
                dataset,
                archive=pipeline.archive,
                reader=pipeline.resolution.reader,
                mapping=mapeamento,
                manifest_fingerprint=await pipeline._impressao(dataset),
            )
        ]
        assert len(completo) >= 3, "o cenário precisa de pelo menos três lotes"

        def com_defeito() -> Iterator[SourceBatch]:
            """Entrega dois lotes e quebra no terceiro, como um arquivo truncado."""
            yield completo[0]
            yield completo[1]
            raise OSError("o arquivo bruto ficou ilegível no meio da leitura")

        with pytest.raises(OSError, match="ilegível"):
            await pipeline.resolution.run_resolution.execute(
                actor=SERVICO, dataset_id=dataset.id, batches=com_defeito()
            )

        async with database.acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT status, failure_reason FROM resolution_runs "
                "WHERE dataset_id = $1 ORDER BY started_at DESC LIMIT 1",
                dataset.id.value,
            )
        assert linha is not None
        assert linha["status"] == "FAILED", linha["status"]
        assert linha["failure_reason"], "a execução falhou sem dizer por quê"
