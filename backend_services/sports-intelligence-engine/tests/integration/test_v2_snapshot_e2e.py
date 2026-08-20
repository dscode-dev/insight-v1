"""Do corpus PUBLICADO ao `MATCH_STATE_RAW_V2` — PostgreSQL e MinIO reais.

O QUE SÓ ESTE TESTE PROVA (§186 ao §192):

    o CONTEXTO vem do banco       partidas anteriores lidas por SQL, com
                                  pertinência à versão e prova de conclusão
    a ISOLAÇÃO POR VERSÃO         a MESMA partida anterior existe fisicamente
                                  no PostgreSQL e não pertence à outra versão —
                                  e o contexto muda por causa disso
    o MERCADO vem do estado       cotações de várias casas, filtradas pelo
                                  corte, agregadas sem uma segunda leitura
    a V1 CONTINUA FUNCIONANDO     o mesmo corpus produz snapshot V1 intacto

O CENÁRIO DE CONTEXTO É CONSTRUÍDO AQUI, e não reusado: os E2E anteriores têm
UMA partida, e contexto exige uma SEQUÊNCIA. Quatro jogos da mesma competição,
mais um de outra para provar que o escopo é local.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import timedelta
from typing import Any

import pytest

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.adapters.postgres.feature_context import (
    PostgresHistoricalContextSource,
)
from sports_intelligence.adapters.postgres.feature_state import (
    PostgresHistoricalMatchStateSource,
)
from sports_intelligence.application.use_cases.feature_snapshot import (
    BuildHistoricalFeatureSnapshot,
)
from sports_intelligence.application.use_cases.feature_snapshot_v2 import (
    BuildExtendedFeatureSnapshot,
    BuildExtendedFeatureSnapshots,
)
from sports_intelligence.domain.features.availability import (
    FeatureAvailability,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.extraction.catalog import (
    match_state_raw_space_v1,
)
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    MATCH_STATE_RAW_V2_NAME,
    V1_SIZE,
    match_state_raw_space_v2,
)
from sports_intelligence.domain.features.prematch.policy import (
    DEFAULT_CONTEXT_POLICY,
)
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.quality.coverage import CoverageFamily, CoverageState
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import Period
from tests.integration.test_match_state_e2e import (
    PUBLICADOR,
    montar_corpus_publicado,
)
from tests.support.instrumentation import contando_consultas

pytestmark = pytest.mark.integration

#: Os intervalos entre a partida atual e as anteriores, em dias.
#:
#: A DE 45 DIAS EXISTE PARA A COBERTURA, e não para as contagens. Sem ela, a
#: partida publicada mais antiga da competição seria a de 28 dias — e a janela
#: de 30 pediria prova de que o corpus alcança `T-30d`, que ele não teria. O
#: resultado seria `INSUFFICIENT_COVERAGE`, corretíssimo e inútil para provar a
#: contagem. Ela fica FORA das duas janelas e dentro da cobertura.
#:
#:     [T-14d, T)  →  só a de 7 dias         →  1
#:     [T-30d, T)  →  as de 28, 21 e 7 dias  →  3
DIAS_ANTES = (45, 28, 21, 7)


@pytest.fixture
async def publicado(database: Database, object_store: Any) -> dict[str, Any]:
    """O corpus READY dos E2E anteriores, mais uma sequência de anteriores."""
    base = await montar_corpus_publicado(database, object_store)
    anteriores = await _semear_anteriores(database, base)
    return {**base, **anteriores}


async def _semear_anteriores(
    database: Database, publicado: dict[str, Any]
) -> dict[str, Any]:
    """Insere partidas ANTERIORES da mesma competição, e uma de outra.

    ELAS SÃO INSERIDAS DIRETO, e é o certo aqui: o que este teste prova é a
    LEITURA de contexto, e fazer as três passarem pelo pipeline inteiro
    mediria o pipeline de novo por três minutos. As linhas são as mesmas que o
    build canônico grava — partida, resultado e pertinência à versão.
    """
    async with database.acquire() as conexao:
        atual = await conexao.fetchrow(
            """
            SELECT id, competition_id, season_id, home_team_id, away_team_id,
                   scheduled_kickoff, stage_type, regime_code, regime_from,
                   regulation_version
            FROM matches WHERE id = $1
            """,
            publicado["match_id"].value,
        )
        assert atual is not None
        kickoff = atual["scheduled_kickoff"]
        criadas: list[MatchId] = []
        for dias in DIAS_ANTES:
            identificador = MatchId.derive("pr054-e2e", f"anterior-{dias}")
            criadas.append(identificador)
            await conexao.execute(
                """
                INSERT INTO matches (
                    id, competition_id, season_id, home_team_id, away_team_id,
                    scheduled_kickoff, stage_type, lifecycle, neutral_venue,
                    regime_code, regime_from, regulation_version
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'RECONCILED', false, $8, $9, $10)
                ON CONFLICT (id) DO NOTHING
                """,
                identificador.value,
                atual["competition_id"],
                atual["season_id"],
                atual["home_team_id"],
                atual["away_team_id"],
                kickoff - timedelta(days=dias),
                atual["stage_type"],
                atual["regime_code"],
                atual["regime_from"],
                atual["regulation_version"],
            )
            # A PROVA DE CONCLUSÃO (§19, §20): o corpus publica o resultado.
            await conexao.execute(
                """
                INSERT INTO match_results (match_id, regular_home, regular_away)
                VALUES ($1, 1, 0) ON CONFLICT (match_id) DO NOTHING
                """,
                identificador.value,
            )
        # A PARTIDA DE OUTRA COMPETIÇÃO (§15, §168): mesma data, outro torneio.
        de_outra = MatchId.derive("pr054-e2e", "outra-competicao")
        outra_competicao = await conexao.fetchval(
            "SELECT id FROM competitions WHERE id <> $1 LIMIT 1",
            atual["competition_id"],
        )
        if outra_competicao is not None:
            await conexao.execute(
                """
                INSERT INTO matches (
                    id, competition_id, season_id, home_team_id, away_team_id,
                    scheduled_kickoff, stage_type, lifecycle, neutral_venue,
                    regime_code, regime_from, regulation_version
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'RECONCILED', false, $8, $9, $10)
                ON CONFLICT (id) DO NOTHING
                """,
                de_outra.value,
                outra_competicao,
                atual["season_id"],
                atual["home_team_id"],
                atual["away_team_id"],
                kickoff - timedelta(days=3),
                atual["stage_type"],
                atual["regime_code"],
                atual["regime_from"],
                atual["regulation_version"],
            )
        # PERTINÊNCIA: as três da mesma competição entram na versão publicada.
        for identificador in criadas:
            await conexao.execute(
                """
                INSERT INTO historical_canonical_members (
                    version_id, match_id, competition_id, season_id,
                    competition_code, season_label, included_families,
                    content_fingerprint
                )
                SELECT $1, $2, competition_id, season_id, competition_code,
                       season_label, included_families, content_fingerprint
                FROM historical_canonical_members
                WHERE version_id = $1 AND match_id = $3
                ON CONFLICT DO NOTHING
                """,
                _uuid.UUID(publicado["version"].id),
                identificador.value,
                publicado["match_id"].value,
            )
    return {"anteriores": criadas, "de_outra_competicao": de_outra}


def _origem(publicado: dict[str, Any]) -> CorpusSource:
    manifesto = publicado["manifest"]
    return CorpusSource.of(
        publicado["version"],
        published_families=frozenset(
            CoverageFamily(f.family)
            for f in manifesto.coverage
            if f.state != CoverageState.NOT_DECLARED.value
        ),
    )


def _caso(publicado: dict[str, Any]) -> BuildExtendedFeatureSnapshot:
    return BuildExtendedFeatureSnapshot(
        state_source=PostgresHistoricalMatchStateSource(publicado["database"]),
        context_source=PostgresHistoricalContextSource(publicado["database"]),
        policy=TemporalAvailabilityPolicy.default(),
    )


def _corte(publicado: dict[str, Any], minuto: int = 60) -> FeatureAsOf:
    return FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, minuto)


async def _snapshot(publicado: dict[str, Any], minuto: int = 60) -> Any:
    return await _caso(publicado).execute(
        source_corpus=_origem(publicado), as_of=_corte(publicado, minuto)
    )


# ================================================== o espaço estendido ==


class TestOSnapshotV2:
    async def test_o_espaco_e_o_de_producao_estendido(
        self, publicado: dict[str, Any]
    ) -> None:
        snapshot = await _snapshot(publicado)
        assert snapshot.space.name == MATCH_STATE_RAW_V2_NAME
        assert len(snapshot.features) == 105
        assert snapshot.space.fingerprint == match_state_raw_space_v2().fingerprint

    async def test_as_setenta_e_cinco_primeiras_sao_as_da_v1(
        self, publicado: dict[str, Any]
    ) -> None:
        """§157, §192 — a V1 continua exatamente funcional no mesmo corpus."""
        v1 = await BuildHistoricalFeatureSnapshot(
            source=PostgresHistoricalMatchStateSource(publicado["database"]),
            policy=TemporalAvailabilityPolicy.default(),
        ).execute(source_corpus=_origem(publicado), as_of=_corte(publicado))
        v2 = await _snapshot(publicado)

        assert v1.snapshot.space.fingerprint == match_state_raw_space_v1().fingerprint
        for herdada in v2.features[:V1_SIZE]:
            correspondente = v1.snapshot.value_of(herdada.definition_key)
            assert herdada.numeric == correspondente.numeric, herdada.definition_key
            assert herdada.availability == correspondente.availability

    async def test_as_impressoes_diferem_porque_o_espaco_difere(
        self, publicado: dict[str, Any]
    ) -> None:
        """§158."""
        v1 = await BuildHistoricalFeatureSnapshot(
            source=PostgresHistoricalMatchStateSource(publicado["database"]),
            policy=TemporalAvailabilityPolicy.default(),
        ).execute(source_corpus=_origem(publicado), as_of=_corte(publicado))
        v2 = await _snapshot(publicado)
        assert v1.snapshot.fingerprint != v2.fingerprint


class TestOContextoVemDoBanco:
    """§187 — a sequência A, B, C e a partida atual."""

    async def test_o_intervalo_ate_a_anterior_e_o_esperado(
        self, publicado: dict[str, Any]
    ) -> None:
        """A mais recente está a 7 dias — 168 horas."""
        snapshot = await _snapshot(publicado)
        computada = snapshot.value_of("ctx_same_comp_prev_gap_hours_home")
        assert computada.is_available
        assert computada.numeric == 168.0

    async def test_as_contagens_sao_as_esperadas(
        self, publicado: dict[str, Any]
    ) -> None:
        """[T-14d, T) contém só a de 7 dias; [T-30d, T) contém as três."""
        snapshot = await _snapshot(publicado)
        assert snapshot.value_of("ctx_same_comp_matches_14d_home").numeric == 1
        assert snapshot.value_of("ctx_same_comp_matches_30d_home").numeric == 3

    async def test_o_visitante_tem_o_mesmo_calendario(
        self, publicado: dict[str, Any]
    ) -> None:
        """As anteriores foram semeadas com os dois times da partida atual."""
        snapshot = await _snapshot(publicado)
        assert snapshot.value_of("ctx_same_comp_matches_30d_away").numeric == 3
        assert snapshot.value_of("ctx_same_comp_matches_30d_diff").numeric == 0

    async def test_a_partida_de_outra_competicao_nao_conta(
        self, publicado: dict[str, Any]
    ) -> None:
        """§15, §168 — ela está a 3 dias e não aparece em janela nenhuma."""
        snapshot = await _snapshot(publicado)
        assert snapshot.value_of("ctx_same_comp_matches_14d_home").numeric == 1
        assert snapshot.value_of("ctx_same_comp_prev_gap_hours_home").numeric == 168.0

    async def test_a_procedencia_aponta_as_partidas_anteriores(
        self, publicado: dict[str, Any]
    ) -> None:
        """§35."""
        snapshot = await _snapshot(publicado)
        procedencia = snapshot.value_of("ctx_same_comp_matches_30d_home").provenance
        assert procedencia.count == 3
        assert {c.kind for c in procedencia.sample} == {"MATCH"}

    async def test_o_contexto_nao_muda_com_o_corte(
        self, publicado: dict[str, Any]
    ) -> None:
        """§159."""
        cedo = await _snapshot(publicado, 10)
        tarde = await _snapshot(publicado, 80)
        for chave in match_state_raw_space_v2().keys:
            if chave.startswith("ctx_"):
                assert cedo.value_of(chave).numeric == tarde.value_of(chave).numeric


class TestAIsolacaoPorVersao:
    """§40, §41, §167, §188 — a partida existe no banco e não na versão."""

    @pytest.fixture
    async def sem_anteriores(self, publicado: dict[str, Any]) -> dict[str, Any]:
        """Uma segunda versão publicada que NÃO inclui as partidas anteriores."""
        from sports_intelligence.domain.corpus.versions import VersionInputs
        from sports_intelligence.domain.shared.versioning import DatasetVersion

        contêiner = publicado["corpus"]
        dataset = await contêiner.create_dataset.execute(
            actor=PUBLICADOR, name=f"v2-sem-anteriores-{_uuid.uuid4().hex[:6]}"
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

    async def test_as_anteriores_existem_fisicamente_no_banco(
        self, sem_anteriores: dict[str, Any]
    ) -> None:
        """A premissa do teste: elas ESTÃO no PostgreSQL."""
        async with sem_anteriores["database"].acquire() as conexao:
            total = await conexao.fetchval(
                "SELECT count(*) FROM matches WHERE id = ANY($1::uuid[])",
                [m.value for m in sem_anteriores["anteriores"]],
            )
        assert total == len(DIAS_ANTES)

    async def test_a_versao_que_nao_as_publica_nao_ve_contexto(
        self, sem_anteriores: dict[str, Any]
    ) -> None:
        """§41 — a pertinência decide, e não a existência física."""
        snapshot = await _snapshot(sem_anteriores)
        gap = snapshot.value_of("ctx_same_comp_prev_gap_hours_home")
        assert not gap.is_available
        assert gap.numeric is None
        contagem = snapshot.value_of("ctx_same_comp_matches_30d_home")
        assert contagem.numeric != 3

    async def test_as_duas_versoes_dao_contextos_diferentes(
        self, publicado: dict[str, Any], sem_anteriores: dict[str, Any]
    ) -> None:
        com = await _snapshot(publicado)
        sem = await _snapshot(sem_anteriores)
        assert com.value_of("ctx_same_comp_matches_30d_home").numeric == 3
        assert sem.value_of("ctx_same_comp_matches_30d_home").numeric != 3
        assert com.fingerprint != sem.fingerprint


class TestOMercadoNoE2E:
    """§189, §190 — o cenário do PR-05.2 não publica `ODDS`."""

    async def test_sem_a_familia_odds_as_vinte_e_uma_sao_nao_declaradas(
        self, publicado: dict[str, Any]
    ) -> None:
        snapshot = await _snapshot(publicado)
        mercado = [k for k in snapshot.space.keys if k.startswith("market_")]
        assert len(mercado) == 21
        for chave in mercado:
            computada = snapshot.value_of(chave)
            assert computada.availability is FeatureAvailability.NOT_DECLARED, chave
            assert computada.numeric is None

    async def test_a_ausencia_de_mercado_nao_inviabiliza_o_snapshot(
        self, publicado: dict[str, Any]
    ) -> None:
        """§80 — `ODDS` é opcional no espaço, e a ausência é da máscara."""
        snapshot = await _snapshot(publicado)
        assert snapshot.value_of("score_home").is_available
        assert snapshot.value_of("ctx_same_comp_matches_14d_home").is_available
        assert not snapshot.is_complete


class TestAsConsultas:
    """§178, §179 — o contexto acrescenta duas por lote; o mercado, zero."""

    async def test_o_contexto_acrescenta_duas_consultas_por_lote(
        self, publicado: dict[str, Any]
    ) -> None:
        origem = _origem(publicado)
        alvo = _corte(publicado)
        estado = PostgresHistoricalMatchStateSource(publicado["database"])

        async with contando_consultas(publicado["database"]) as so_v1:
            await BuildHistoricalFeatureSnapshot(
                source=estado, policy=TemporalAvailabilityPolicy.default()
            ).execute(source_corpus=origem, as_of=alvo)

        async with contando_consultas(publicado["database"]) as com_v2:
            await _caso(publicado).execute(source_corpus=origem, as_of=alvo)

        # A V1 faz 5 (estado). A V2 faz 5 + cobertura + janela + última = 8 na
        # PRIMEIRA execução; a cobertura é memorizada por versão, então os
        # lotes seguintes custam 5 + 2 = 7 (§178).
        assert so_v1.total == 5
        assert com_v2.total == 8, com_v2.por_alvo

    async def test_varios_cortes_reusam_o_contexto(
        self, publicado: dict[str, Any]
    ) -> None:
        """§159 — o contexto é por PARTIDA, e não por corte."""
        cortes = tuple(
            FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, m)
            for m in (50, 55, 60, 65, 70)
        )
        async with contando_consultas(publicado["database"]) as consultas:
            saida = await BuildExtendedFeatureSnapshots(
                state_source=PostgresHistoricalMatchStateSource(publicado["database"]),
                context_source=PostgresHistoricalContextSource(publicado["database"]),
                policy=TemporalAvailabilityPolicy.default(),
            ).execute(
                source_corpus=_origem(publicado),
                match_ids=[publicado["match_id"]],
                as_of_of=lambda _: cortes,
            )
        assert saida.built == 5
        # UM lote: 5 do estado + cobertura + janela + última. Os cinco cortes
        # reaproveitam o MESMO contexto — recarregá-lo por corte daria cinco vezes isso.
        assert consultas.total == 8


class TestOLoteV2:
    async def test_o_lote_produz_o_mesmo_snapshot_que_o_individual(
        self, publicado: dict[str, Any]
    ) -> None:
        alvo = _corte(publicado)
        individual = await _snapshot(publicado)
        saida = await BuildExtendedFeatureSnapshots(
            state_source=PostgresHistoricalMatchStateSource(publicado["database"]),
            context_source=PostgresHistoricalContextSource(publicado["database"]),
            policy=TemporalAvailabilityPolicy.default(),
        ).execute(
            source_corpus=_origem(publicado),
            match_ids=[publicado["match_id"]],
            as_of_of=lambda _: (alvo,),
        )
        assert saida.built == 1
        assert saida.feature_values == 105
        assert saida.snapshots[0].fingerprint == individual.fingerprint

    async def test_a_politica_de_contexto_entra_na_identidade(
        self, publicado: dict[str, Any]
    ) -> None:
        from sports_intelligence.domain.features.extraction.catalog_v2 import (
            extended_feature_catalog,
        )
        from sports_intelligence.domain.features.prematch.policy import (
            HistoricalContextPolicy,
        )

        outra = HistoricalContextPolicy(lookback_days=(7, 30))
        alternativo = await BuildExtendedFeatureSnapshot(
            state_source=PostgresHistoricalMatchStateSource(publicado["database"]),
            context_source=PostgresHistoricalContextSource(publicado["database"]),
            policy=TemporalAvailabilityPolicy.default(),
            context_policy=outra,
            space=match_state_raw_space_v2(context_policy=outra),
            catalog=extended_feature_catalog(context_policy=outra),
        ).execute(source_corpus=_origem(publicado), as_of=_corte(publicado))
        padrao = await _snapshot(publicado)
        assert alternativo.fingerprint != padrao.fingerprint
        assert "ctx_same_comp_matches_7d_home" in alternativo.space.keys


class TestAReprodutibilidade:
    async def test_duas_execucoes_dao_a_mesma_impressao(
        self, publicado: dict[str, Any]
    ) -> None:
        """§176."""
        assert (await _snapshot(publicado)).fingerprint == (
            await _snapshot(publicado)
        ).fingerprint

    async def test_a_politica_padrao_e_a_declarada(
        self, publicado: dict[str, Any]
    ) -> None:
        snapshot = await _snapshot(publicado)
        definicao = snapshot.space.definition_of("ctx_same_comp_matches_14d_home")
        assert (
            definicao.parameters["context_policy_fingerprint"]
            == DEFAULT_CONTEXT_POLICY.fingerprint
        )
