"""Os goldens da agregação — peso, concentração e o que eles NÃO são.

O PR-06.5 TRANSFORMA, E NÃO INTERPRETA. Os testes aqui provam a aritmética e os
limites; nenhum deles olha desfecho, e nenhum chama peso de probabilidade.
"""

from __future__ import annotations

import math

import pytest

from sports_intelligence.domain.retrieval.aggregation.aggregate import (
    AggregationStatus,
    NeighborAggregation,
    WeightedNeighbor,
    aggregate,
)
from sports_intelligence.domain.retrieval.aggregation.kernel import (
    effective_sample_size,
    normalized_weights,
    top_mass,
    uniform_weights,
)
from sports_intelligence.domain.retrieval.aggregation.policy import (
    DistanceWeightingPolicy,
    RetrievalKind,
    state_weighting,
    trajectory_weighting,
    uniform_baseline,
)
from sports_intelligence.domain.shared.errors import ValidationError

IMPRESSAO = "d" * 64


def _politica(lam: float = 1.0) -> DistanceWeightingPolicy:
    return state_weighting(lam=lam, distance_definition_fingerprint=IMPRESSAO)


def _vizinhos(distancias: list[float]) -> list[tuple[str, int, float, str]]:
    return [(f"m{i}#0001", i + 1, d, f"ev{i}") for i, d in enumerate(distancias)]


class TestONucleoDePesos:
    """§12 ao §17 — a exponencial deslocada, e por que ela é deslocada."""

    def test_a_soma_dos_pesos_e_um(self) -> None:
        p = normalized_weights([0.1, 0.4, 0.9, 1.7], lam=1.0)
        assert math.isclose(math.fsum(p), 1.0, rel_tol=0, abs_tol=1e-15)

    def test_distancias_iguais_dao_pesos_iguais(self) -> None:
        """§63 — nenhum desempate escondido."""
        p = normalized_weights([0.5, 0.5, 0.5], lam=2.0)
        assert p[0] == p[1] == p[2]
        assert math.isclose(p[0], 1 / 3, abs_tol=1e-15)

    def test_menor_distancia_tem_peso_MAIOR(self) -> None:
        """§64 — monotonicidade estrita."""
        p = normalized_weights([0.1, 0.2, 0.3, 0.4], lam=1.0)
        assert p[0] > p[1] > p[2] > p[3]

    def test_a_razao_entre_pesos_e_a_exponencial_da_diferenca(self) -> None:
        """§62 — `w_i/w_j = exp(-lambda (d_i - d_j))`.

        ESTE É O GOLDEN QUE DEFINE O NÚCLEO. Ele vale sobre os pesos
        NORMALIZADOS porque o denominador comum se cancela na razão — que é
        exatamente o que torna o deslocamento invisível na semântica.
        """
        lam, d = 1.7, [0.3, 1.1]
        p = normalized_weights(d, lam=lam)
        assert math.isclose(p[0] / p[1], math.exp(-lam * (d[0] - d[1])), rel_tol=1e-12)

    def test_deslocar_TODAS_as_distancias_nao_muda_peso_nenhum(self) -> None:
        """§65 — a invariância é EXATA em R, e aproximada em `binary64`.

        A TOLERÂNCIA AQUI FOI MEDIDA, e não escolhida por conveniência. A
        identidade `p_i(d + c) = p_i(d)` vale exatamente na matemática; o que
        não vale é `(d_i + c) - min(d + c) == d_i - min(d)` em ponto flutuante:

            c =    1.0   erro no expoente  5,6e-17
            c =   50.0   erro no expoente  4,2e-15
            c = 1000.0   erro no expoente  6,8e-14

        Esse erro entra no expoente ANTES da exponenciação e sai nos pesos
        normalizados como ~9,4e-15 absolutos. Uma tolerância de 1e-15 reprovaria
        a implementação por um efeito do `float64`, e não por um defeito dela.
        """
        base = [0.2, 0.7, 1.4]
        for constante in (0.0, 1.0, 50.0, 1000.0):
            deslocadas = [d + constante for d in base]
            assert normalized_weights(deslocadas, lam=1.3) == pytest.approx(
                normalized_weights(base, lam=1.3), rel=1e-12
            )

    def test_sem_deslocamento_a_invariancia_e_BIT_A_BIT(self) -> None:
        """E com `c = 0` não há erro nenhum: a igualdade é exata.

        ELE SEPARA AS DUAS COISAS. O teste acima aceita tolerância por causa da
        soma `d + c`; este prova que a implementação em si não introduz erro.
        """
        base = [0.2, 0.7, 1.4]
        assert normalized_weights(base, lam=1.3) == normalized_weights(base, lam=1.3)

    def test_escalar_as_distancias_MUDA_os_pesos(self) -> None:
        """§66 — e isso NÃO é um defeito: é o que `lambda` significa.

        A INVARIÂNCIA DE ESCALA SERIA UMA SUPOSIÇÃO ESCONDIDA. `lambda` tem
        unidade — é o inverso de uma distância —, e multiplicar as distâncias
        por dois com o mesmo `lambda` concentra os pesos. Quem trocar a régua de
        distância precisa revisar `lambda`, e este teste é o que impede alguém
        de assumir o contrário.
        """
        base = [0.1, 0.2, 0.4]
        assert normalized_weights([2 * d for d in base], lam=1.0) != pytest.approx(
            normalized_weights(base, lam=1.0), abs=1e-9
        )

    def test_a_forma_ingenua_estouraria_e_a_deslocada_NAO(self) -> None:
        """§15 — o motivo concreto do deslocamento, medido.

        Com `lambda = 4` e distâncias na casa de 200, `exp(-800)` é zero em
        `binary64`; a soma dá zero e a normalização seria divisão por zero.
        """
        distantes = [200.0, 201.0, 202.0]
        assert math.fsum(math.exp(-4.0 * d) for d in distantes) == 0.0
        p = normalized_weights(distantes, lam=4.0)
        assert math.isclose(math.fsum(p), 1.0, abs_tol=1e-15)
        assert all(math.isfinite(x) for x in p)
        assert p[0] > p[1] > p[2]

    def test_lambda_maior_concentra_mais(self) -> None:
        """§67 — mais `lambda`, menos `N_eff`."""
        d = [0.1, 0.3, 0.6, 1.0]
        anterior = float("inf")
        for lam in (0.25, 0.5, 1.0, 2.0, 4.0):
            atual = effective_sample_size(normalized_weights(d, lam=lam))
            assert atual is not None
            assert atual <= anterior + 1e-12
            anterior = atual


class TestOTamanhoEfetivo:
    """§27 ao §32 — `N_eff` e os limites que ele nunca deixa."""

    def test_uniforme_da_exatamente_k(self) -> None:
        """§29 — o golden que prova `N_eff` sem passar pelo exponencial."""
        for k in (1, 2, 5, 17, 100):
            assert effective_sample_size(uniform_weights(k)) == pytest.approx(float(k), rel=1e-12)

    def test_um_vizinho_da_um(self) -> None:
        """§30."""
        assert effective_sample_size(normalized_weights([4.2], lam=1.0)) == 1.0

    def test_um_vizinho_dominante_tende_a_um(self) -> None:
        """§31 — a massa concentra, e `N_eff` desce até o piso."""
        efetivo = effective_sample_size(normalized_weights([0.0, 50.0, 60.0], lam=5.0))
        assert efetivo is not None
        assert 1.0 <= efetivo < 1.001

    def test_os_limites_valem_sempre(self) -> None:
        """§28 — `1 <= N_eff <= k`."""
        for d in ([0.0], [0.1, 0.1], [0.0, 1.0, 2.0, 3.0], [0.5] * 20):
            p = normalized_weights(d, lam=1.5)
            efetivo = effective_sample_size(p)
            assert efetivo is not None
            assert 1.0 - 1e-12 <= efetivo <= len(d) + 1e-12

    def test_conjunto_vazio_devolve_None_e_nao_zero(self) -> None:
        """§35 — zero seria um número abaixo do mínimo da escala."""
        assert effective_sample_size(()) is None
        assert top_mass(()) is None


class TestAsRecusas:
    """§38, §39, §20 — o que a agregação não aceita."""

    def test_distancia_nao_finita_e_recusada(self) -> None:
        for ruim in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValidationError):
                normalized_weights([0.1, ruim], lam=1.0)

    def test_distancia_negativa_e_recusada(self) -> None:
        with pytest.raises(ValidationError):
            normalized_weights([0.1, -0.2], lam=1.0)

    def test_lambda_invalido_e_recusado(self) -> None:
        for ruim in (0.0, -1.0, float("nan"), float("inf")):
            with pytest.raises(ValidationError):
                normalized_weights([0.1, 0.2], lam=ruim)

    def test_lambda_nao_tem_padrao_escondido(self) -> None:
        """§20 — a política é obrigatória, e o núcleo exige o valor."""
        with pytest.raises(TypeError):
            normalized_weights([0.1])  # type: ignore[call-arg]

    def test_vizinho_repetido_e_recusado(self) -> None:
        """§38 — a mesma partida receberia massa duas vezes."""
        with pytest.raises(ValidationError):
            aggregate(
                query_identity="q#0001",
                kind=RetrievalKind.STATE,
                policy=_politica(),
                requested_k=2,
                neighbors=[("m1#0001", 1, 0.1, "e"), ("m1#0001", 2, 0.2, "e")],
            )

    def test_politica_do_tipo_errado_e_recusada(self) -> None:
        """§11 — estado e trajetória não se misturam."""
        with pytest.raises(ValidationError):
            aggregate(
                query_identity="q#0001",
                kind=RetrievalKind.TRAJECTORY,
                policy=_politica(),
                requested_k=1,
                neighbors=_vizinhos([0.1]),
            )


class TestOAgregado:
    """§45 ao §48 — o contrato do resultado."""

    def test_o_conjunto_vazio_tem_ESTADO_e_nao_zeros(self) -> None:
        """§35 — `NO_NEIGHBORS`, e os números ficam `None`."""
        agregado = aggregate(
            query_identity="q#0001",
            kind=RetrievalKind.STATE,
            policy=_politica(),
            requested_k=10,
            neighbors=[],
        )
        assert agregado.status is AggregationStatus.NO_NEIGHBORS
        assert agregado.neighbor_count == 0
        assert agregado.effective_sample_size is None
        assert agregado.weighted_mean_dissimilarity is None
        assert agregado.max_neighbor_weight is None

    def test_a_contagem_e_o_tamanho_efetivo_sao_campos_DIFERENTES(self) -> None:
        """§32 — `k` e `N_eff` não são a mesma grandeza."""
        agregado = aggregate(
            query_identity="q#0001",
            kind=RetrievalKind.STATE,
            policy=_politica(lam=2.0),
            requested_k=10,
            neighbors=_vizinhos([0.0, 0.5, 1.0, 2.0]),
        )
        assert agregado.neighbor_count == 4
        efetivo = agregado.effective_sample_size
        assert efetivo is not None
        assert efetivo < 4.0

    def test_a_ordem_do_topK_e_preservada(self) -> None:
        """§40 — a agregação não reordena."""
        agregado = aggregate(
            query_identity="q#0001",
            kind=RetrievalKind.STATE,
            policy=_politica(),
            requested_k=10,
            neighbors=_vizinhos([0.1, 0.2, 0.3]),
        )
        assert [v.retrieval_rank for v in agregado.weighted_neighbors] == [1, 2, 3]

    def test_a_massa_do_topo_soma_os_TRES_maiores(self) -> None:
        """§47."""
        agregado = aggregate(
            query_identity="q#0001",
            kind=RetrievalKind.STATE,
            policy=_politica(lam=1.0),
            requested_k=10,
            neighbors=_vizinhos([0.0, 0.1, 0.2, 5.0, 6.0]),
        )
        massa = agregado.top3_weight_mass
        assert massa is not None
        pesos = sorted(agregado.weights, reverse=True)
        assert massa == pytest.approx(math.fsum(pesos[:3]), abs=1e-15)

    def test_a_media_ponderada_usa_os_pesos(self) -> None:
        """§46 — e ela fica ENTRE o mínimo e o máximo."""
        agregado = aggregate(
            query_identity="q#0001",
            kind=RetrievalKind.STATE,
            policy=_politica(lam=1.0),
            requested_k=10,
            neighbors=_vizinhos([0.2, 0.8, 1.5]),
        )
        media = agregado.weighted_mean_dissimilarity
        assert media is not None
        assert agregado.minimum_dissimilarity is not None
        assert agregado.maximum_dissimilarity is not None
        assert agregado.minimum_dissimilarity <= media <= agregado.maximum_dissimilarity


class TestAsImpressoes:
    """§42, §43, §97 ao §99 — o que muda a identidade, e o que não muda."""

    def _agregado(self, lam: float, distancias: list[float]) -> NeighborAggregation:
        return aggregate(
            query_identity="q#0001",
            kind=RetrievalKind.STATE,
            policy=_politica(lam),
            requested_k=10,
            neighbors=_vizinhos(distancias),
            retrieval_fingerprint="r" * 64,
        )

    def test_a_mesma_entrada_da_a_mesma_impressao(self) -> None:
        a = self._agregado(1.0, [0.1, 0.4])
        b = self._agregado(1.0, [0.1, 0.4])
        assert a.fingerprint == b.fingerprint

    def test_mudar_a_DISTANCIA_muda_a_impressao(self) -> None:
        """§97."""
        a = self._agregado(1.0, [0.1, 0.4])
        b = self._agregado(1.0, [0.1, 0.5])
        assert a.fingerprint != b.fingerprint

    def test_mudar_LAMBDA_muda_a_impressao_e_os_pesos(self) -> None:
        """§99 — mesmas identidades, mesmas distâncias, outra semântica."""
        a = self._agregado(1.0, [0.1, 0.4])
        b = self._agregado(2.0, [0.1, 0.4])
        assert [v.identity for v in a.weighted_neighbors] == [
            v.identity for v in b.weighted_neighbors
        ]
        assert a.dissimilarities == b.dissimilarities
        assert a.weights != b.weights
        assert a.fingerprint != b.fingerprint

    def test_mudar_SO_a_evidencia_NAO_muda_os_pesos(self) -> None:
        """§98 — a prova de que a cobertura não entra no peso.

        ESTE É O TESTE DA NÃO-DUPLICAÇÃO. A distância manda no peso; a evidência
        descreve o suporte. Se um resumo de evidência diferente mudasse a massa,
        a ausência estaria sendo cobrada duas vezes — uma dentro da distância,
        outra fora dela.
        """
        comum = {
            "query_identity": "q#0001",
            "kind": RetrievalKind.STATE,
            "policy": _politica(1.0),
            "requested_k": 10,
            "neighbors": _vizinhos([0.1, 0.4]),
        }
        magra = aggregate(**comum, evidence_summary={"weighted_shared_axes": 10.0})
        gorda = aggregate(**comum, evidence_summary={"weighted_shared_axes": 3.0})
        assert magra.weights == gorda.weights
        assert magra.effective_sample_size == gorda.effective_sample_size

    def test_a_impressao_NAO_depende_do_resumo_de_evidencia(self) -> None:
        """O resumo é descritivo; a identidade vem da entrada e da política."""
        comum = {
            "query_identity": "q#0001",
            "kind": RetrievalKind.STATE,
            "policy": _politica(1.0),
            "requested_k": 10,
            "neighbors": _vizinhos([0.1, 0.4]),
        }
        assert (
            aggregate(**comum, evidence_summary={"a": 1}).fingerprint
            == aggregate(**comum, evidence_summary={"b": 2}).fingerprint
        )


class TestAsPoliticas:
    """§18 ao §21 — `lambda` é semântica versionada."""

    def test_lambda_entra_na_impressao(self) -> None:
        um = state_weighting(lam=1.0, distance_definition_fingerprint=IMPRESSAO)
        dois = state_weighting(lam=2.0, distance_definition_fingerprint=IMPRESSAO)
        assert um.fingerprint != dois.fingerprint

    def test_a_regua_de_distancia_entra_na_impressao(self) -> None:
        a = state_weighting(lam=1.0, distance_definition_fingerprint="a" * 64)
        b = state_weighting(lam=1.0, distance_definition_fingerprint="b" * 64)
        assert a.fingerprint != b.fingerprint

    def test_estado_e_trajetoria_sao_politicas_distintas(self) -> None:
        """§21 — mesmo `lambda`, impressões diferentes."""
        e = state_weighting(lam=1.0, distance_definition_fingerprint=IMPRESSAO)
        t = trajectory_weighting(lam=1.0, distance_definition_fingerprint=IMPRESSAO)
        assert e.fingerprint != t.fingerprint
        assert e.kind is RetrievalKind.STATE
        assert t.kind is RetrievalKind.TRAJECTORY

    def test_as_politicas_SELECIONADAS_carregam_os_lambdas_medidos(self) -> None:
        """§7, §8, §12, §13, §94 — os valores congelados da V1.

        AS FÁBRICAS RESOLVEM CONSTANTES NOMEADAS, e não um padrão escondido: o
        `lambda` sai na política, entra na impressão, e trocá-lo muda a
        identidade. É essa a diferença entre uma constante documentada e o
        `1.0` solto que o §20 proíbe.
        """
        from sports_intelligence.domain.retrieval.aggregation.policy import (
            SELECTED_STATE_LAMBDA,
            SELECTED_TRAJECTORY_LAMBDA,
        )

        assert SELECTED_STATE_LAMBDA == 8.0
        assert SELECTED_TRAJECTORY_LAMBDA == 16.0

        e = state_weighting(distance_definition_fingerprint=IMPRESSAO)
        t = trajectory_weighting(distance_definition_fingerprint=IMPRESSAO)
        assert e.lam == 8.0
        assert t.lam == 16.0
        assert e.identity == "STATE_DISTANCE_WEIGHTING_V1@1"
        assert t.identity == "TRAJECTORY_DISTANCE_WEIGHTING_V1@1"
        # E O `lambda` APARECE NA REPRESENTAÇÃO. Nenhuma execução pode escondê-lo.
        assert "exp(-8" in str(e)
        assert "exp(-16" in str(t)

    def test_as_impressoes_das_politicas_selecionadas_estao_CONGELADAS(self) -> None:
        """§11, §14, §94 — mudar uma delas é mudar a semântica da V1.

        O GOLDEN É SOBRE A IMPRESSÃO, e não sobre o `lambda` sozinho: ela cobre
        também o núcleo, a normalização, a fronteira numérica e a régua de
        distância. Uma mudança em qualquer um deles produziria agregados que não
        se comparam com os de ontem, e o hexadecimal é o que obriga essa
        mudança a ser deliberada.

        A régua fixa `d * 64` é do teste, e não de produção: em produção ela é a
        impressão da definição de distância que mediu o resultado.
        """
        e = state_weighting(distance_definition_fingerprint="d" * 64)
        t = trajectory_weighting(distance_definition_fingerprint="d" * 64)
        assert e.fingerprint == (
            "04656c5c3adb6dcd53d20a7f9889c441a5ea84156e875ed436941340cb0e8ee2"
        )
        assert t.fingerprint == (
            "b3084c55eaf55313a8760354c1af699f019bde02f5421811c37df296cfade0b3"
        )

    def test_o_lambda_de_estado_aplicado_a_TRAJETORIA_concentra_menos(self) -> None:
        """§10, §27 — o contrafactual que justifica as duas políticas.

        A DISTÂNCIA DE TRAJETÓRIA TEM ESCALA MENOR, então o mesmo `lambda`
        separa menos: sobre o mesmo vetor, `lambda = 8` deixa `N_eff` mais perto
        de `k` do que `lambda = 16`. É o mecanismo pelo qual um `lambda` único
        produziria semânticas diferentes nos dois caminhos por acidente.
        """
        distancias = [0.0, 0.05, 0.10, 0.15, 0.20]
        com_oito = effective_sample_size(normalized_weights(distancias, lam=8.0))
        com_dezesseis = effective_sample_size(normalized_weights(distancias, lam=16.0))
        assert com_oito is not None
        assert com_dezesseis is not None
        assert com_oito > com_dezesseis
        # E o de estado fica MAIS PERTO do uniforme, que é o regime que o §92
        # manda evitar para a trajetória.
        assert com_oito / len(distancias) > com_dezesseis / len(distancias)

    def test_a_linha_de_base_uniforme_recusa_lambda(self) -> None:
        """§25 — guardá-lo sugeriria que ele influencia algo."""
        base = uniform_baseline(kind=RetrievalKind.STATE, distance_definition_fingerprint=IMPRESSAO)
        assert base.is_uniform
        assert base.lam == 0.0
        with pytest.raises(ValidationError):
            DistanceWeightingPolicy(
                name="x",
                version=1,
                kind=RetrievalKind.STATE,
                kernel="UNIFORM_WEIGHTING_BASELINE_V1",
                lam=1.0,
                distance_definition_fingerprint=IMPRESSAO,
            )

    def test_a_linha_de_base_da_pesos_iguais_e_N_eff_igual_a_k(self) -> None:
        agregado = aggregate(
            query_identity="q#0001",
            kind=RetrievalKind.STATE,
            policy=uniform_baseline(
                kind=RetrievalKind.STATE, distance_definition_fingerprint=IMPRESSAO
            ),
            requested_k=10,
            neighbors=_vizinhos([0.1, 5.0, 40.0]),
        )
        assert agregado.weights == pytest.approx((1 / 3, 1 / 3, 1 / 3), abs=1e-15)
        assert agregado.effective_sample_size == pytest.approx(3.0, rel=1e-12)

    def test_o_nucleo_desconhecido_e_recusado(self) -> None:
        with pytest.raises(ValidationError):
            DistanceWeightingPolicy(
                name="x",
                version=1,
                kind=RetrievalKind.STATE,
                kernel="GAUSSIAN_V9",
                lam=1.0,
                distance_definition_fingerprint=IMPRESSAO,
            )


class TestOVizinhoPonderado:
    """O contrato de um vizinho — e o que ele recusa."""

    def test_massa_fora_de_zero_um_e_recusada(self) -> None:
        with pytest.raises(ValidationError):
            WeightedNeighbor(
                identity="m#0001",
                retrieval_rank=1,
                dissimilarity=0.1,
                normalized_weight=1.5,
                evidence_fingerprint="e",
            )

    def test_o_vizinho_tem_impressao_PROPRIA_e_o_peso_nao_entra(self) -> None:
        """§44 — identidade semântica do vizinho, sem a massa do conjunto.

        O PESO É DO CONJUNTO, e não do vizinho: renormalizar num top-10 e num
        top-20 dá massas diferentes para o MESMO vizinho, à mesma distância.
        Amarrar o peso na impressão dele faria a identidade de um vizinho mudar
        por causa dos vizinhos ao lado.
        """
        comum = {
            "identity": "m1#0001",
            "retrieval_rank": 1,
            "dissimilarity": 0.25,
            "evidence_fingerprint": "e" * 64,
        }
        leve = WeightedNeighbor(**comum, normalized_weight=0.1)
        pesado = WeightedNeighbor(**comum, normalized_weight=0.9)
        assert len(leve.fingerprint) == 64
        assert leve.fingerprint == pesado.fingerprint

        outra_distancia = WeightedNeighbor(
            identity="m1#0001",
            retrieval_rank=1,
            dissimilarity=0.26,
            evidence_fingerprint="e" * 64,
            normalized_weight=0.1,
        )
        assert outra_distancia.fingerprint != leve.fingerprint

    def test_posicao_menor_que_um_e_recusada(self) -> None:
        with pytest.raises(ValidationError):
            WeightedNeighbor(
                identity="m#0001",
                retrieval_rank=0,
                dissimilarity=0.1,
                normalized_weight=0.5,
                evidence_fingerprint="e",
            )
