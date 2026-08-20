"""Do corpus PUBLICADO ao `FeatureSnapshot` — PostgreSQL e MinIO reais.

    versão READY  →  insumos  →  projeção efetiva  →  estado  →  snapshot

O QUE SÓ ESTE TESTE PROVA (§169 ao §174). Os testes de unidade extraem features
de um contexto montado à mão; cada um está certo, e juntos não provam que o
caminho existe. Ele passa por:

    o CORPUS de verdade         a mesma versão publicada do PR-05.2, construída
                                pelo pipeline inteiro do PR-04
    uma PROJEÇÃO só             estado e features sobre os MESMOS fatos efetivos
    zero consulta extra         a extração não acrescenta ida ao banco nenhuma
    a CORREÇÃO real             o evento corrigido que o PR-04.4.1 gravou
    duas MÁSCARAS               o mesmo espaço sobre dois corpus produz
                                disponibilidades diferentes, e é isso que a
                                máscara existe para dizer

O CENÁRIO É O DO PR-05.2, de propósito: reusar a fixture prova o encaixe entre
as fases em vez de um encaixe que só existe neste arquivo. Ele NÃO publica
escalação — e por isso as features de elenco saem indisponíveis contra um banco
de verdade, que é a parcialidade honesta do §127 acontecendo fora do duplo.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

import pytest

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.adapters.postgres.feature_state import (
    PostgresHistoricalMatchStateSource,
)
from sports_intelligence.application.use_cases.feature_snapshot import (
    BuildHistoricalFeatureSnapshot,
    BuildHistoricalFeatureSnapshots,
)
from sports_intelligence.domain.corpus.versions import VersionInputs
from sports_intelligence.domain.features.availability import (
    FeatureAvailability,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.extraction.catalog import (
    MATCH_STATE_RAW_V1_NAME,
    match_state_raw_space_v1,
    production_feature_catalog,
)
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.quality.coverage import CoverageFamily, CoverageState
from sports_intelligence.domain.shared.errors import NotFoundError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import Period
from sports_intelligence.domain.shared.versioning import DatasetVersion
from tests.integration.test_match_state_e2e import (
    PUBLICADOR,
    montar_corpus_publicado,
)
from tests.support.instrumentation import contando_consultas

pytestmark = pytest.mark.integration


@pytest.fixture
async def publicado(database: Database, object_store: Any) -> dict[str, Any]:
    """O MESMO corpus READY do E2E de estado, montado por função comum.

    Reusá-lo é o ponto: se o snapshot se extrai do corpus que o PR-05.2
    reconstrói, o encaixe entre as fases é o real — e não um que só existe
    neste arquivo.
    """
    return await montar_corpus_publicado(database, object_store)


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


def _caso(publicado: dict[str, Any]) -> BuildHistoricalFeatureSnapshot:
    return BuildHistoricalFeatureSnapshot(
        source=PostgresHistoricalMatchStateSource(publicado["database"]),
        policy=TemporalAvailabilityPolicy.default(),
    )


def _corte(publicado: dict[str, Any], minuto: int = 60) -> FeatureAsOf:
    return FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, minuto)


async def _snapshot(publicado: dict[str, Any], minuto: int = 60) -> Any:
    resultado = await _caso(publicado).execute(
        source_corpus=_origem(publicado), as_of=_corte(publicado, minuto)
    )
    return resultado.snapshot


# ================================================== o caminho completo ==


class TestOSnapshotSaiDoCorpus:
    async def test_o_snapshot_tem_o_espaco_de_producao_inteiro(
        self, publicado: dict[str, Any]
    ) -> None:
        snapshot = await _snapshot(publicado)
        assert snapshot.space.name == MATCH_STATE_RAW_V1_NAME
        assert len(snapshot.features) == 75
        assert snapshot.space.fingerprint == match_state_raw_space_v1().fingerprint

    async def test_as_features_de_relogio_descrevem_o_corte(
        self, publicado: dict[str, Any]
    ) -> None:
        snapshot = await _snapshot(publicado)
        assert snapshot.value_of("clock_minute").numeric == 60
        assert snapshot.value_of("clock_stoppage").numeric == 0
        assert (
            snapshot.value_of("clock_period_order").numeric
            == Period.SECOND_HALF.order
        )

    async def test_o_placar_vem_do_estado_reconstruido(
        self, publicado: dict[str, Any]
    ) -> None:
        """§36 — o estado já reduziu os gols; a feature não os reconta."""
        snapshot = await _snapshot(publicado)
        assert snapshot.value_of("score_home").numeric == 1
        assert snapshot.value_of("score_away").numeric == 1
        assert snapshot.value_of("score_difference").numeric == 0

    async def test_a_disciplina_vem_do_estado(self, publicado: dict[str, Any]) -> None:
        snapshot = await _snapshot(publicado)
        assert snapshot.value_of("yellow_cards_home").numeric == 1
        assert snapshot.value_of("dismissals_away").numeric == 1

    async def test_as_janelas_contam_os_eventos_do_corpus(
        self, publicado: dict[str, Any]
    ) -> None:
        """O cenário do PR-05.2 só tem gols e cartões — e é isso que aparece.

        O corpus daquele PR não publica finalização nem escanteio: as famílias
        correspondentes valem ZERO, e o zero é AVAILABLE porque `EVENT` está
        publicado e a ausência é observável (§51, §62).
        """
        snapshot = await _snapshot(publicado)
        assert snapshot.value_of("shots_home_10m").numeric == 0
        assert snapshot.value_of("corners_home_10m").numeric == 0
        assert snapshot.value_of("goals_home_10m").numeric == 0

    async def test_o_gol_dos_58_aparece_na_janela_que_o_contem(
        self, publicado: dict[str, Any]
    ) -> None:
        """O vermelho é dos 58; num corte de 60 com janela de 5m ele entra.

        A prova de que a janela lê o corpus real: `(55, 60]` contém o minuto
        58, e o cartão vermelho de fora está lá.
        """
        resultado = await _caso(publicado).execute(
            source_corpus=_origem(publicado), as_of=_corte(publicado, 60)
        )
        assert resultado.snapshot.value_of("dismissals_away").numeric == 1

    async def test_o_gol_dos_71_nao_entra_no_snapshot_dos_60(
        self, publicado: dict[str, Any]
    ) -> None:
        """§148 contra um banco de verdade."""
        snapshot = await _snapshot(publicado, 60)
        assert snapshot.value_of("score_home").numeric == 1
        assert snapshot.value_of("goals_home_10m").numeric == 0

    async def test_o_corte_pos_jogo_ve_a_partida_inteira(
        self, publicado: dict[str, Any]
    ) -> None:
        resultado = await _caso(publicado).execute(
            source_corpus=_origem(publicado),
            as_of=FeatureAsOf.at(publicado["match_id"], Period.FULL_TIME, 90),
        )
        assert resultado.snapshot.value_of("score_home").numeric == 2

    async def test_uma_partida_fora_da_versao_e_recusada(
        self, publicado: dict[str, Any]
    ) -> None:
        outra = MatchId.derive("pr053e2e", "partida-de-outro-corpus")
        with pytest.raises(NotFoundError):
            await _caso(publicado).execute(
                source_corpus=_origem(publicado),
                as_of=FeatureAsOf.at(outra, Period.SECOND_HALF, 60),
            )


class TestACorrecaoAtravessaTresPRs:
    """§174 — gravada no PR-04.4.1, projetada no PR-05.1, contada aqui."""

    async def test_o_gol_corrigido_conta_uma_vez_no_placar(
        self, publicado: dict[str, Any]
    ) -> None:
        snapshot = await _snapshot(publicado, 60)
        assert snapshot.value_of("score_home").numeric == 1

    async def test_a_procedencia_do_placar_aponta_os_gols_efetivos(
        self, publicado: dict[str, Any]
    ) -> None:
        snapshot = await _snapshot(publicado, 60)
        assert snapshot.value_of("score_home").provenance.count == 2


class TestAParcialidadeContraOBanco:
    """§127 — o cenário não publica escalação, e o snapshot o declara."""

    async def test_as_features_de_elenco_sao_indisponiveis(
        self, publicado: dict[str, Any]
    ) -> None:
        snapshot = await _snapshot(publicado)
        for chave in (
            "players_on_field_home",
            "players_on_field_away",
            "manpower_difference",
        ):
            computada = snapshot.value_of(chave)
            assert not computada.is_available, chave
            assert computada.numeric is None, chave

    async def test_o_resto_do_snapshot_sobrevive(
        self, publicado: dict[str, Any]
    ) -> None:
        """§158 — a degradação é da família, e não do snapshot."""
        snapshot = await _snapshot(publicado)
        assert snapshot.value_of("score_home").is_available
        assert snapshot.value_of("shots_home_5m").is_available
        assert not snapshot.is_complete

    async def test_a_mascara_diz_quantas_dimensoes_existem(
        self, publicado: dict[str, Any]
    ) -> None:
        snapshot = await _snapshot(publicado)
        assert snapshot.mask.keys == match_state_raw_space_v1().keys
        assert snapshot.mask.available_count == 72
        assert (
            snapshot.mask.state_of("players_on_field_home")
            is FeatureAvailability.NOT_DECLARED
        )


class TestDuasMascarasSobreOMesmoEspaco:
    """§172, §173 — o mesmo espaço, dois corpus, disponibilidades diferentes."""

    @pytest.fixture
    async def sem_eventos(self, publicado: dict[str, Any]) -> dict[str, Any]:
        """Uma segunda versão da MESMA partida, sem publicar `EVENT`.

        Ela é o análogo do corpus comercial que não pode publicar evento
        restrito: o que muda não é a feature, é o que o corpus declara.
        """
        contêiner = publicado["corpus"]
        dataset = await contêiner.create_dataset.execute(
            actor=PUBLICADOR, name=f"snapshot-sem-eventos-{_uuid.uuid4().hex[:6]}"
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

    async def test_sem_event_as_janelas_ficam_indisponiveis(
        self, sem_eventos: dict[str, Any]
    ) -> None:
        """§59, §156 — e NUNCA zero."""
        snapshot = await _snapshot(sem_eventos)
        for chave in ("shots_home_5m", "xg_away_10m", "corners_diff_1m"):
            computada = snapshot.value_of(chave)
            assert not computada.is_available, chave
            assert computada.numeric is None, chave

    async def test_sem_event_o_placar_tambem_nao_e_afirmavel(
        self, sem_eventos: dict[str, Any]
    ) -> None:
        snapshot = await _snapshot(sem_eventos)
        assert not snapshot.value_of("score_home").is_available

    async def test_o_relogio_continua_disponivel(
        self, sem_eventos: dict[str, Any]
    ) -> None:
        """O corte é dado de entrada: ele não depende de cobertura nenhuma."""
        snapshot = await _snapshot(sem_eventos)
        assert snapshot.value_of("clock_minute").is_available

    async def test_o_mesmo_espaco_produz_mascaras_diferentes(
        self, publicado: dict[str, Any], sem_eventos: dict[str, Any]
    ) -> None:
        """§172 — é para isso que a máscara é de primeira classe."""
        com = await _snapshot(publicado)
        sem = await _snapshot(sem_eventos)
        assert com.space.fingerprint == sem.space.fingerprint
        assert com.mask.keys == sem.mask.keys
        assert com.mask.available_count > sem.mask.available_count
        assert com.fingerprint != sem.fingerprint

    async def test_o_corpus_sem_evento_nao_toma_emprestado_do_outro(
        self, sem_eventos: dict[str, Any]
    ) -> None:
        """§173 — os eventos existem no banco, e a versão não os publica.

        Este é o teste que reprovaria a otimização mais tentadora: ler
        `canonical_match_events` direto em vez de cruzar com a pertinência da
        versão. Os eventos ESTÃO lá — a outra versão os publica —, e mesmo
        assim este snapshot precisa dizer que não sabe.
        """
        snapshot = await _snapshot(sem_eventos)
        assert snapshot.value_of("goals_home_10m").numeric is None


class TestZeroConsultaExtra:
    """§94, §95, §179 — a extração não vai ao banco."""

    async def test_a_extracao_nao_acrescenta_consulta_ao_estado(
        self, publicado: dict[str, Any]
    ) -> None:
        """Cinco consultas com estado; cinco consultas com estado E features."""
        from sports_intelligence.application.use_cases.feature_state import (
            BuildHistoricalMatchState,
        )

        origem = _origem(publicado)
        alvo = _corte(publicado)
        fonte = PostgresHistoricalMatchStateSource(publicado["database"])

        async with contando_consultas(publicado["database"]) as so_estado:
            await BuildHistoricalMatchState(
                source=fonte, policy=TemporalAvailabilityPolicy.default()
            ).execute(source_corpus=origem, as_of=alvo)

        async with contando_consultas(publicado["database"]) as com_features:
            await _caso(publicado).execute(source_corpus=origem, as_of=alvo)

        assert com_features.total == so_estado.total == 5, (
            f"estado {so_estado.total}, estado+features {com_features.total} — a "
            "extração acrescentou consulta ao caminho (§179)"
        )

    async def test_cinco_cortes_da_mesma_partida_leem_o_corpus_uma_vez(
        self, publicado: dict[str, Any]
    ) -> None:
        """§113 — o insumo é por PARTIDA, e é reaproveitado dentro do lote."""
        cortes = tuple(
            FeatureAsOf.at(publicado["match_id"], Period.SECOND_HALF, m)
            for m in (50, 55, 60, 65, 70)
        )
        async with contando_consultas(publicado["database"]) as consultas:
            saida = await BuildHistoricalFeatureSnapshots(
                source=PostgresHistoricalMatchStateSource(publicado["database"]),
                policy=TemporalAvailabilityPolicy.default(),
            ).execute(
                source_corpus=_origem(publicado),
                match_ids=[publicado["match_id"]],
                as_of_of=lambda _: cortes,
            )
        assert saida.built == 5
        assert consultas.total == 5


class TestOLote:
    async def test_o_lote_produz_o_mesmo_snapshot_que_o_individual(
        self, publicado: dict[str, Any]
    ) -> None:
        alvo = _corte(publicado)
        individual = await _snapshot(publicado)
        saida = await BuildHistoricalFeatureSnapshots(
            source=PostgresHistoricalMatchStateSource(publicado["database"]),
            policy=TemporalAvailabilityPolicy.default(),
        ).execute(
            source_corpus=_origem(publicado),
            match_ids=[publicado["match_id"]],
            as_of_of=lambda _: (alvo,),
        )
        assert saida.built == 1
        assert saida.snapshots[0].fingerprint == individual.fingerprint

    async def test_o_lote_conta_valores_e_indisponibilidades(
        self, publicado: dict[str, Any]
    ) -> None:
        saida = await BuildHistoricalFeatureSnapshots(
            source=PostgresHistoricalMatchStateSource(publicado["database"]),
            policy=TemporalAvailabilityPolicy.default(),
        ).execute(
            source_corpus=_origem(publicado),
            match_ids=[publicado["match_id"]],
            as_of_of=lambda m: (FeatureAsOf.at(m, Period.SECOND_HALF, 60),),
        )
        assert saida.feature_values == 75
        assert saida.available_values == 72
        assert saida.unavailable_by_reason == {
            FeatureAvailability.NOT_DECLARED.value: 3
        }


class TestReprodutibilidadeContraOBanco:
    """§162, §203 — mesmo corpus, mesmo corte, mesma impressão."""

    async def test_duas_execucoes_produzem_a_mesma_impressao(
        self, publicado: dict[str, Any]
    ) -> None:
        assert (await _snapshot(publicado)).fingerprint == (
            await _snapshot(publicado)
        ).fingerprint

    async def test_cortes_diferentes_produzem_impressoes_diferentes(
        self, publicado: dict[str, Any]
    ) -> None:
        assert (await _snapshot(publicado, 40)).fingerprint != (
            await _snapshot(publicado, 60)
        ).fingerprint

    async def test_a_politica_entra_na_impressao(
        self, publicado: dict[str, Any]
    ) -> None:
        estrita = await BuildHistoricalFeatureSnapshot(
            source=PostgresHistoricalMatchStateSource(publicado["database"]),
            policy=TemporalAvailabilityPolicy.strict_observed(),
        ).execute(source_corpus=_origem(publicado), as_of=_corte(publicado))
        assert estrita.snapshot.fingerprint != (await _snapshot(publicado)).fingerprint

    async def test_o_catalogo_de_producao_e_o_usado(
        self, publicado: dict[str, Any]
    ) -> None:
        """O caso de uso não monta um espaço próprio: usa o de produção."""
        snapshot = await _snapshot(publicado)
        assert tuple(f.definition_key for f in snapshot.features) == tuple(
            s.definition.key for s in production_feature_catalog().specs
        )
