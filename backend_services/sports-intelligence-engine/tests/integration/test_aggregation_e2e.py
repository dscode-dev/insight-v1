"""A agregação sobre o pipeline REAL — e a prova de que ela não lê nada.

O QUE ESTE ARQUIVO PROVA, e que nenhum teste de unidade consegue provar:

    §60, §61   o top-K EXATO que o PR-06.4 produz atravessa a agregação
    §62 a §65  e a agregação não paga UMA leitura por isso
    §66        e ela termina sem tocar em desfecho nenhum
    §69        e o agregado aponta para o resultado que o originou

A DIFERENÇA ENTRE ESTE E OS TESTES DE UNIDADE É A AUTORIDADE DA ENTRADA. Um
vetor sintético `[0.0, 0.1, 0.2]` prova aritmética; ele não prova que as
distâncias que o retrieval REAL produz atravessam o núcleo sem estourar, sem
empatar tudo, e sem produzir massa concentrada num vizinho só. Essa pergunta só
tem resposta sobre as distâncias de verdade.

## Por que o zero de I/O é medido, e não afirmado

A guarda de arquitetura prova que o pacote de agregação não PODE importar um
adapter. Ela não prova que a EXECUÇÃO não leu: o caminho de aplicação passa por
objetos que têm acesso a armazenamento, e uma leitura preguiçosa disparada ao
tocar um atributo do resultado não apareceria em guarda de import nenhuma.

Por isso o bloco medido começa DEPOIS que o resultado exato já existe.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from sports_intelligence.application.use_cases.neighbor_aggregation import (
    AggregateProjectedStateNeighbors,
    AggregateProjectedTrajectoryNeighbors,
    state_policy_for,
    trajectory_policy_for,
)
from sports_intelligence.domain.retrieval.aggregation.aggregate import AggregationStatus
from sports_intelligence.domain.retrieval.aggregation.policy import (
    SELECTED_STATE_LAMBDA,
    SELECTED_TRAJECTORY_LAMBDA,
    STATE_DISTANCE_WEIGHTING_V1,
    TRAJECTORY_DISTANCE_WEIGHTING_V1,
    RetrievalKind,
)
from sports_intelligence.domain.retrieval.aggregation.summaries import (
    aggregate_state,
    aggregate_trajectory,
)

pytestmark = pytest.mark.integration

K = 20
QUERIES = 24


@pytest.fixture
async def agregavel(database: Any, object_store: Any) -> dict[str, Any]:
    """Corpus real -> normalizado READY -> projeções READY -> agregadores.

    A LOJA CONTADA ENTRA ANTES DE TUDO. Ela precisa ser a loja que o contêiner
    INTEIRO usa; embrulhá-la depois da montagem contaria só as chamadas feitas
    por quem recebesse o proxy, e o resto passaria invisível.
    """
    from tests.support.aggregation_e2e import LojaContada
    from tests.support.projection_e2e import montar_projecoes
    from tests.support.trajectory_e2e import dataset_com_movimento

    loja = LojaContada(object_store)
    dados = await dataset_com_movimento(database, loja)
    projetado = await montar_projecoes(dados, database)
    return {
        **dados,
        **projetado,
        "loja": loja,
        "agregar_estado": AggregateProjectedStateNeighbors(projetado["projected_state"]),
        "agregar_trajetoria": AggregateProjectedTrajectoryNeighbors(
            projetado["projected_trajectory"]
        ),
    }


async def _queries(agregavel: dict[str, Any], limite: int = QUERIES) -> list[Any]:
    from tests.support.retrieval_e2e import queries_disponiveis

    return await queries_disponiveis(
        agregavel["conteiner"].source,
        dataset_name="match-state-normalized",
        version=str(agregavel["versao_n"].version),
        limite=limite,
    )


class TestOEstadoAtravessaOPipelineReal:
    """§25, §60 — o top-K exato de estado vira vizinhança ponderada."""

    async def test_a_agregacao_de_ESTADO_sobre_vizinhos_REAIS(
        self, agregavel: dict[str, Any]
    ) -> None:
        versao = agregavel["versao_n"]
        versao_p = agregavel["state_version"]
        agregador = agregavel["agregar_estado"]

        agregados = 0
        vazios = 0
        for chave, _ in await _queries(agregavel):
            saida = await agregador.execute(
                projection_version=versao_p, version_id=versao.id, key=chave, k=K
            )
            agregado = saida.aggregation

            # ---- a política resolvida está VISÍVEL (§13, §82) --------------
            assert saida.policy.name == STATE_DISTANCE_WEIGHTING_V1
            assert saida.policy.lam == SELECTED_STATE_LAMBDA
            assert len(saida.policy.fingerprint) == 64
            # A régua que MEDIU é a régua que a política declara (§11).
            assert (
                saida.policy.distance_definition_fingerprint
                == saida.result.distance_definition_fingerprint
            )

            if agregado.status is AggregationStatus.NO_NEIGHBORS:
                # §39 — a ausência tem estado próprio, e não vira zero.
                vazios += 1
                assert agregado.weighted_neighbors == ()
                assert agregado.effective_sample_size is None
                assert agregado.max_neighbor_weight is None
                continue

            agregados += 1
            k = agregado.neighbor_count
            pesos = agregado.weights

            # ---- §30 — o que os pesos reais precisam satisfazer ------------
            assert all(p > 0.0 for p in pesos), f"{chave.text}: peso nulo em {k} vizinhos"
            assert all(math.isfinite(p) for p in pesos)
            assert math.fsum(pesos) == pytest.approx(1.0, abs=1e-12)

            # ---- §34 — mais perto nunca pesa menos ------------------------
            distancias = agregado.dissimilarities
            for i in range(k):
                for j in range(k):
                    if distancias[i] < distancias[j]:
                        assert pesos[i] >= pesos[j], f"{chave.text}: {distancias} / {pesos}"

            # ---- §16, §38 — N_eff dentro de [1, k] ------------------------
            efetivo = agregado.effective_sample_size
            assert efetivo is not None
            assert 1.0 - 1e-9 <= efetivo <= k + 1e-9, f"N_eff={efetivo} com k={k}"

            # ---- §69 — a linhagem aponta para o resultado exato -----------
            assert agregado.retrieval_fingerprint == saida.result.fingerprint
            assert [v.identity for v in agregado.weighted_neighbors] == [
                v.key.text for v in saida.result.neighbors
            ]
            assert [v.retrieval_rank for v in agregado.weighted_neighbors] == [
                v.rank for v in saida.result.neighbors
            ]
            assert [v.dissimilarity for v in agregado.weighted_neighbors] == [
                float(v.dissimilarity) for v in saida.result.neighbors
            ]
            assert all(len(v.evidence_fingerprint) == 64 for v in agregado.weighted_neighbors)

            # ---- §53 — o resumo descreve, e não decide --------------------
            resumo = agregado.evidence_summary
            assert int(str(resumo["profile_axis_count"])) > 0
            assert int(str(resumo["minimum_shared_axes"])) <= int(
                str(resumo["maximum_shared_axes"])
            )

        assert agregados >= 5, f"o cenário precisa de agregações reais: {agregados}"

    async def test_a_TRAJETORIA_atravessa_o_mesmo_caminho(self, agregavel: dict[str, Any]) -> None:
        """§26, §61 — e com a política dela, que é outra (§9, §11)."""
        versao = agregavel["versao_n"]
        versao_p = agregavel["trajectory_version"]
        agregador = agregavel["agregar_trajetoria"]

        agregados = 0
        recusadas = 0
        for chave, _ in await _queries(agregavel):
            try:
                saida = await agregador.execute(
                    projection_version=versao_p, version_id=versao.id, key=chave, k=K
                )
            except Exception:  # noqa: BLE001 — query inelegível é caminho normal
                recusadas += 1
                continue

            agregado = saida.aggregation
            assert saida.policy.name == TRAJECTORY_DISTANCE_WEIGHTING_V1
            assert saida.policy.lam == SELECTED_TRAJECTORY_LAMBDA
            assert agregado.kind is RetrievalKind.TRAJECTORY

            if agregado.status is AggregationStatus.NO_NEIGHBORS:
                continue

            agregados += 1
            pesos = agregado.weights
            assert math.fsum(pesos) == pytest.approx(1.0, abs=1e-12)
            efetivo = agregado.effective_sample_size
            assert efetivo is not None
            assert 1.0 - 1e-9 <= efetivo <= agregado.neighbor_count + 1e-9

            assert agregado.retrieval_fingerprint == saida.result.fingerprint
            assert [v.identity for v in agregado.weighted_neighbors] == [
                v.anchor_key.text for v in saida.result.neighbors
            ]
            assert [v.dissimilarity for v in agregado.weighted_neighbors] == [
                float(v.trajectory_dissimilarity) for v in saida.result.neighbors
            ]

            # §54 — o resumo por horizonte é o que a trajetória tem de próprio.
            resumo = agregado.evidence_summary
            assert int(str(resumo["cell_count"])) > 0
            for minutos in (1, 3, 5):
                assert f"{minutos}m_weighted_shared_axes" in resumo

        assert agregados >= 3, (
            f"o cenário precisa de trajetórias: {agregados} ({recusadas} recusadas)"
        )


class TestAAgregacaoNaoLeNada:
    """§28, §62 ao §65 — o gate absoluto, medido e não afirmado."""

    async def test_zero_leituras_depois_que_o_resultado_exato_existe(
        self, agregavel: dict[str, Any], database: Any
    ) -> None:
        from tests.support.aggregation_e2e import sem_leituras

        versao = agregavel["versao_n"]
        loja = agregavel["loja"]
        projetor = agregavel["projected_state"]
        projetor_t = agregavel["projected_trajectory"]

        medidos_estado = 0
        medidos_traj = 0
        for chave, _ in await _queries(agregavel, limite=8):
            # ---- FASE 1: a recuperação. Ela paga, e é para pagar mesmo -----
            saida = await projetor.execute(
                projection_version=agregavel["state_version"],
                version_id=versao.id,
                key=chave,
                k=K,
            )
            politica = state_policy_for(saida.result)

            # ---- FASE 2: a agregação. Aqui o contador precisa dar zero -----
            with sem_leituras(database, loja) as leituras:
                agregado = aggregate_state(
                    saida.result, policy=politica, query_identity=chave.text, requested_k=K
                )
                # AS LEITURAS DERIVADAS ENTRAM NO BLOCO de propósito: se alguma
                # delas disparasse acesso preguiçoso, o zero seria falso.
                _ = agregado.effective_sample_size
                _ = agregado.weighted_mean_dissimilarity
                _ = agregado.top3_weight_mass
                _ = agregado.max_neighbor_weight
                _ = agregado.fingerprint
                _ = dict(agregado.diagnostics())
            assert leituras.postgres == 0, f"§62: {leituras}"
            assert leituras.objetos == 0, f"§64: {leituras}"
            assert leituras.parquet == 0, f"§63: {leituras}"
            medidos_estado += 1

            try:
                saida_t = await projetor_t.execute(
                    projection_version=agregavel["trajectory_version"],
                    version_id=versao.id,
                    key=chave,
                    k=K,
                )
            except Exception:  # noqa: BLE001
                continue
            politica_t = trajectory_policy_for(saida_t.result)
            with sem_leituras(database, loja) as leituras_t:
                agregado_t = aggregate_trajectory(
                    saida_t.result,
                    policy=politica_t,
                    query_identity=chave.text,
                    requested_k=K,
                )
                _ = agregado_t.effective_sample_size
                _ = agregado_t.fingerprint
                _ = dict(agregado_t.diagnostics())
            assert leituras_t.total == 0, f"§62 ao §65 (trajetória): {leituras_t}"
            medidos_traj += 1

        assert medidos_estado >= 5
        assert medidos_traj >= 1

    async def test_o_CONTADOR_enxerga_leituras_quando_elas_existem(
        self, agregavel: dict[str, Any], database: Any
    ) -> None:
        """Uma guarda contra a guarda que dá zero por não estar olhando.

        SE O CONTADOR ESTIVER QUEBRADO, o teste acima passa por engano — e o
        §28 estaria «provado» por um instrumento cego. Aqui a recuperação roda
        DENTRO do bloco, e o contador tem de acusar.
        """
        from tests.support.aggregation_e2e import sem_leituras

        chave, _ = (await _queries(agregavel, limite=1))[0]
        loja = agregavel["loja"]
        with sem_leituras(database, loja) as leituras:
            await agregavel["projected_state"].execute(
                projection_version=agregavel["state_version"],
                version_id=agregavel["versao_n"].id,
                key=chave,
                k=K,
            )
        assert leituras.postgres > 0, f"o contador de PostgreSQL está cego: {leituras}"


class TestAAgregacaoNaoOlhaODesfecho:
    """§57, §58 — ela completa sem carregar nada de pós-jogo."""

    async def test_o_agregado_nao_carrega_NENHUM_campo_de_desfecho(
        self, agregavel: dict[str, Any]
    ) -> None:
        """A prova é sobre o CONTEÚDO, e não sobre imports.

        A guarda de arquitetura prova que o pacote não importa `MatchResult`.
        Esta prova é outra: o objeto que sai da execução real não tem, em
        lugar nenhum da forma canônica nem do diagnóstico, um campo que possa
        carregar placar, vencedor ou evento futuro.
        """
        proibidos = {
            "result",
            "outcome",
            "winner",
            "score",
            "goals",
            "home_goals",
            "away_goals",
            "final_score",
            "label",
        }
        saida = await agregavel["agregar_estado"].execute(
            projection_version=agregavel["state_version"],
            version_id=agregavel["versao_n"].id,
            key=(await _queries(agregavel, limite=1))[0][0],
            k=K,
        )
        agregado = saida.aggregation
        campos: set[str] = set()

        def _colher(mapa: Any) -> None:
            if isinstance(mapa, dict):
                for nome, valor in mapa.items():
                    campos.add(str(nome).lower())
                    _colher(valor)
            elif isinstance(mapa, list):
                for item in mapa:
                    _colher(item)

        _colher(dict(agregado.as_canonical()))
        _colher(dict(agregado.diagnostics()))
        intersecao = campos & proibidos
        assert not intersecao, f"o agregado carrega {sorted(intersecao)}"

    async def test_o_agregado_e_DETERMINISTICO_sobre_a_mesma_query(
        self, agregavel: dict[str, Any]
    ) -> None:
        """§68, §84 — repetir a execução real dá a mesma impressão."""
        chave, _ = (await _queries(agregavel, limite=1))[0]
        impressoes = set()
        for _ in range(3):
            saida = await agregavel["agregar_estado"].execute(
                projection_version=agregavel["state_version"],
                version_id=agregavel["versao_n"].id,
                key=chave,
                k=K,
            )
            impressoes.add(saida.aggregation.fingerprint)
        assert len(impressoes) == 1, impressoes
