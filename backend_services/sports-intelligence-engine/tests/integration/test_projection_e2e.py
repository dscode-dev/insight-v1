"""A projeção contra o oráculo — igualdade, e não semelhança.

O QUE ESTE MÓDULO PROVA, e é o PR-06.4 inteiro:

    universo projetado   ==  universo do Parquet
    elegibilidade        ==
    D_state              ==
    evidência            ==
    top-K ordenado       ==

CEM POR CENTO, e não «quase». A implementação compartilha os mesmos
calculadores do domínio — o que reduz o risco de divergência a quase zero —,
mas implementação compartilhada NÃO É PROVA EMPÍRICA. O PR exige a medição.

E A COMPARAÇÃO É DO UNIVERSO INTEIRO, e não só do top-K. Dois recuperadores
podem produzir o mesmo top-K por acaso com candidatos divergentes fora do
corte; comparar só o topo aceitaria essa coincidência como equivalência.

AS ASSERÇÕES ESTÃO AGRUPADAS EM POUCOS TESTES DE PROPÓSITO. A fixture do corpus
é de FUNÇÃO — é a convenção do repositório, e ela existe para que um teste não
veja o resíduo de outro. O preço é que cada teste reconstrói o pipeline inteiro;
espalhar doze asserções em doze testes custaria doze construções para provar o
que uma prova.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from sports_intelligence.application.use_cases.projected_retrieval import (
    universe_filter_for,
)
from sports_intelligence.domain.retrieval.projection.contract import (
    ProjectionKindMismatchError,
    ProjectionNotReadyError,
    ProjectionSourceMismatchError,
    RetrievalProjectionKind,
    RetrievalProjectionStatus,
)

pytestmark = pytest.mark.integration

K = 10
QUERIES = 40


@pytest.fixture
async def projetado(database: Any, object_store: Any) -> dict[str, Any]:
    """Corpus real -> normalizado READY -> as duas projeções READY."""
    from tests.support.projection_e2e import montar_projecoes
    from tests.support.trajectory_e2e import dataset_com_movimento

    dados = await dataset_com_movimento(database, object_store)
    return {**dados, **await montar_projecoes(dados, database)}


async def _queries(projetado: dict[str, Any], limite: int = QUERIES) -> list[Any]:
    from tests.support.retrieval_e2e import queries_disponiveis

    return await queries_disponiveis(
        projetado["conteiner"].source,
        dataset_name="match-state-normalized",
        version=str(projetado["versao_n"].version),
        limite=limite,
    )


class TestAProjecaoConcordaComOOraculo:
    """O gate do PR: o caminho projetado devolve EXATAMENTE o mesmo."""

    async def test_o_ciclo_de_vida_fecha_e_a_contabilidade_bate(
        self, projetado: dict[str, Any]
    ) -> None:
        """§12 ao §16 — READY, e nenhuma linha sumida sem motivo."""
        assert projetado["state_version"].status is RetrievalProjectionStatus.READY
        assert projetado["trajectory_version"].status is RetrievalProjectionStatus.READY

        estado = projetado["state_build"]
        estado.accounting.assert_reconciles()
        assert estado.rows_written > 0
        assert estado.accounting.rows_read == (
            estado.accounting.rows_indexed + estado.accounting.rejected_total
        )

        trajetoria = projetado["trajectory_build"]
        trajetoria.accounting.assert_reconciles()
        assert trajetoria.rows_written > 0

        assert len(projetado["state_version"].content_fingerprint) == 64
        assert len(projetado["trajectory_version"].content_fingerprint) == 64

    async def test_universo_distancia_evidencia_e_topK_sao_IDENTICOS(
        self, projetado: dict[str, Any]
    ) -> None:
        """§30 ao §39 — e a comparação é do universo INTEIRO, não só do topo."""
        conteiner = projetado["conteiner"]
        versao = projetado["versao_n"]
        leitor = projetado["reader"]
        versao_p = projetado["state_version"]
        projetor = projetado["projected_state"]

        comparadas = 0
        candidatos_comparados = 0
        for chave, _ in await _queries(projetado):
            contexto = await conteiner.retrieve_aware.resolve(version_id=versao.id, key=chave)
            resolucao = contexto.resolution

            # ---- 1. o UNIVERSO inteiro -------------------------------------
            do_parquet = await conteiner.retrieve.candidates(resolucao, None)
            chaves_parquet = {c.key.text for c in do_parquet}
            da_projecao = await leitor.load_state_universe(
                projection_version=versao_p,
                universe=universe_filter_for(
                    competition=resolucao.competition,
                    position=resolucao.snapshot.position,
                    exclude_match_id=resolucao.snapshot.key.match_key,
                ),
                axis_keys=versao_p.axis_keys,
            )
            chaves_projecao = {c.semantic_key for c in da_projecao}
            assert chaves_projecao == chaves_parquet, (
                f"universo divergente em {chave.text}: "
                f"{len(chaves_projecao)} projetadas contra {len(chaves_parquet)}"
            )
            candidatos_comparados += len(chaves_parquet)

            # ---- 2. o RESULTADO --------------------------------------------
            do_oraculo = await conteiner.retrieve_aware.execute(
                version_id=versao.id, key=chave, k=K
            )
            resultado = (
                await projetor.execute(
                    projection_version=versao_p,
                    version_id=versao.id,
                    key=chave,
                    k=K,
                )
            ).result

            assert resultado.universe_count == do_oraculo.universe_count
            assert resultado.coverage_eligible_count == do_oraculo.coverage_eligible_count

            oraculo = [v.key.text for v in do_oraculo.neighbors]
            assert [v.key.text for v in resultado.neighbors] == oraculo, (
                f"top-K divergente em {chave.text}"
            )

            # ---- 3. DISTÂNCIA e EVIDÊNCIA, sem tolerância ------------------
            for a, b in zip(resultado.neighbors, do_oraculo.neighbors, strict=True):
                assert a.dissimilarity == b.dissimilarity, (
                    f"distância divergente em {chave.text}/{a.key.text}: "
                    f"{a.dissimilarity!r} != {b.dissimilarity!r}"
                )
                assert a.evidence.fingerprint == b.evidence.fingerprint, (
                    f"evidência divergente em {chave.text}/{a.key.text}"
                )
            comparadas += 1

        assert comparadas >= 20, f"só {comparadas} queries comparadas"
        assert candidatos_comparados > 0

    async def test_o_prefixo_do_topK_continua_valendo(self, projetado: dict[str, Any]) -> None:
        """§41 — `Top10(K=20) == K=10` também no caminho projetado."""
        versao = projetado["versao_n"]
        projetor = projetado["projected_state"]
        versao_p = projetado["state_version"]

        chave, _ = (await _queries(projetado, limite=5))[0]
        vinte = await projetor.execute(
            projection_version=versao_p, version_id=versao.id, key=chave, k=20
        )
        dez = await projetor.execute(
            projection_version=versao_p, version_id=versao.id, key=chave, k=10
        )
        assert [v.key.text for v in vinte.result.neighbors[:10]] == [
            v.key.text for v in dez.result.neighbors
        ]

    async def test_a_consulta_usa_indice_e_nao_varre_a_tabela(
        self, projetado: dict[str, Any]
    ) -> None:
        """§48, §52 — o plano REAL, sem forçar nada."""
        conteiner = projetado["conteiner"]
        versao = projetado["versao_n"]

        chave, _ = (await _queries(projetado, limite=5))[0]
        contexto = await conteiner.retrieve_aware.resolve(version_id=versao.id, key=chave)
        resolucao = contexto.resolution
        plano = await projetado["reader"].explain_state_universe(
            projection_version=projetado["state_version"],
            universe=universe_filter_for(
                competition=resolucao.competition,
                position=resolucao.snapshot.position,
                exclude_match_id=resolucao.snapshot.key.match_key,
            ),
        )
        # A ASSERÇÃO É FRACA DE PROPÓSITO: o que importa é que o planejador não
        # varre a tabela inteira. Exigir um nome de índice específico tornaria o
        # teste refém de uma decisão que é do planejador, e não nossa.
        assert "Seq Scan" not in plano, plano


class TestOsSentinelasDeMetadado:
    """§54 ao §57 — toda divergência de amarra é fail-closed.

    ELES NÃO PRECISAM DO CORPUS. A recusa acontece ANTES de qualquer leitura de
    candidato (§121), e é justamente isso que se prova aqui: um objeto de versão
    construído à mão basta, porque a decisão é de metadado.
    """

    def _versao(self) -> Any:
        from sports_intelligence.domain.retrieval.projection.contract import (
            HistoricalRetrievalProjectionVersion,
            RetrievalProjectionBinding,
        )

        return HistoricalRetrievalProjectionVersion(
            version_id="11111111-1111-1111-1111-111111111111",
            projection_id="22222222-2222-2222-2222-222222222222",
            kind=RetrievalProjectionKind.STATE,
            name="sentinela",
            version=1,
            status=RetrievalProjectionStatus.READY,
            axis_count=29,
            content_fingerprint="f" * 64,
            binding=RetrievalProjectionBinding(
                source_dataset_version_id="33333333-3333-3333-3333-333333333333",
                source_dataset_version="1.0",
                source_reference_fingerprint="ref",
                normalization_plan_fingerprint="plano",
                artifact_set_fingerprint="artefatos",
                candidate_policy_fingerprint="politica",
                exact_payload_encoding="EXACT_FLOAT64_LE_PAYLOAD_V1",
            ),
        )

    def test_projecao_nao_READY_e_recusada(self) -> None:
        for estado in (
            RetrievalProjectionStatus.DRAFT,
            RetrievalProjectionStatus.BUILDING,
            RetrievalProjectionStatus.VALIDATING,
            RetrievalProjectionStatus.FAILED,
        ):
            with pytest.raises(ProjectionNotReadyError):
                replace(self._versao(), status=estado).assert_queryable()

    def test_tipo_errado_e_recusado(self) -> None:
        with pytest.raises(ProjectionKindMismatchError):
            self._versao().assert_serves(
                dataset_version_id="33333333-3333-3333-3333-333333333333",
                plan_fingerprint="plano",
                artifact_set_fingerprint="artefatos",
                kind=RetrievalProjectionKind.TRAJECTORY,
            )

    def test_dataset_errado_e_recusado(self) -> None:
        with pytest.raises(ProjectionSourceMismatchError):
            self._versao().assert_serves(
                dataset_version_id="99999999-9999-9999-9999-999999999999",
                plan_fingerprint="plano",
                artifact_set_fingerprint="artefatos",
                kind=RetrievalProjectionKind.STATE,
            )

    def test_plano_de_normalizacao_errado_e_recusado(self) -> None:
        with pytest.raises(ProjectionSourceMismatchError):
            self._versao().assert_serves(
                dataset_version_id="33333333-3333-3333-3333-333333333333",
                plan_fingerprint="OUTRO",
                artifact_set_fingerprint="artefatos",
                kind=RetrievalProjectionKind.STATE,
            )

    def test_conjunto_de_artefatos_errado_e_recusado(self) -> None:
        with pytest.raises(ProjectionSourceMismatchError):
            self._versao().assert_serves(
                dataset_version_id="33333333-3333-3333-3333-333333333333",
                plan_fingerprint="plano",
                artifact_set_fingerprint="OUTRO",
                kind=RetrievalProjectionKind.STATE,
            )


class TestATrajetoriaProjetadaConcordaComOOraculo:
    """§17 ao §23 — a trajetória, com a mesma exigência de igualdade.

    A DIFERENÇA EM RELAÇÃO AO ESTADO É A LINHAGEM. Uma trajetória tem
    identidade própria — âncora, política e o digesto de cada slot —, e a
    impressão da evidência a cobre. Igualar deslocamentos não basta: se a
    linhagem reconstruída divergir, a evidência diverge sem que um número mude.
    """

    async def test_universo_distancia_evidencia_e_topK_da_TRAJETORIA(
        self, projetado: dict[str, Any]
    ) -> None:
        from sports_intelligence.domain.retrieval.trajectory_coverage import (
            QueryInsufficientTrajectoryEvidenceError,
        )
        from sports_intelligence.domain.retrieval.trajectory_window import (
            TrajectoryNotApplicableError,
        )

        conteiner = projetado["conteiner"]
        versao = projetado["versao_n"]
        versao_t = projetado["trajectory_version"]
        projetor = projetado["projected_trajectory"]

        comparadas = 0
        nao_aplicaveis = 0
        recusadas = 0
        for chave, _ in await _queries(projetado):
            try:
                do_oraculo = await conteiner.retrieve_trajectory.execute(
                    version_id=versao.id, key=chave, k=K
                )
            except TrajectoryNotApplicableError:
                nao_aplicaveis += 1
                continue
            except QueryInsufficientTrajectoryEvidenceError:
                recusadas += 1
                continue

            saida = await projetor.execute(
                projection_version=versao_t, version_id=versao.id, key=chave, k=K
            )
            resultado = saida.result

            # ---- o universo e a atrição -----------------------------------
            assert resultado.universe_count == do_oraculo.universe_count, (
                f"universo divergente em {chave.text}"
            )
            assert resultado.trajectory_eligible_count == (do_oraculo.trajectory_eligible_count)
            assert resultado.ineligible == do_oraculo.ineligible

            # ---- o top-K ORDENADO ------------------------------------------
            oraculo = [v.anchor_key.text for v in do_oraculo.neighbors]
            assert [v.anchor_key.text for v in resultado.neighbors] == oraculo, (
                f"top-K de trajetória divergente em {chave.text}"
            )

            # ---- DISTÂNCIA e EVIDÊNCIA, sem tolerância --------------------
            for a, b in zip(resultado.neighbors, do_oraculo.neighbors, strict=True):
                assert a.trajectory_dissimilarity == b.trajectory_dissimilarity, (
                    f"D_T divergente em {chave.text}/{a.anchor_key.text}: "
                    f"{a.trajectory_dissimilarity!r} != {b.trajectory_dissimilarity!r}"
                )
                assert a.evidence.fingerprint == b.evidence.fingerprint, (
                    f"evidência de trajetória divergente em {chave.text}"
                )
                assert a.shared_cells == b.shared_cells
                assert a.shared_horizons == b.shared_horizons
            comparadas += 1

        assert comparadas > 0, (
            f"nenhuma query de trajetória comparada "
            f"({nao_aplicaveis} não aplicáveis, {recusadas} recusadas)"
        )
