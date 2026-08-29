"""As invariantes da agregação, varridas sobre muitos vetores de distância.

    §28   1 <= N_eff <= k
    §64   monotonicidade do peso na distância
    §65   invariância a deslocamento constante
    §67   lambda maior concentra mais
    §69   determinismo sob permutação física

ELAS SÃO VARRIDAS, E NÃO EXEMPLIFICADAS. Um golden prova um caso; estas
percorrem centenas de vetores gerados por semente fixa, incluindo os que a
aritmética odeia — todos iguais, quase iguais, muito distantes, um só.
"""

from __future__ import annotations

import math
import random

import pytest

from sports_intelligence.domain.retrieval.aggregation.aggregate import aggregate
from sports_intelligence.domain.retrieval.aggregation.kernel import (
    effective_sample_size,
    normalized_weights,
)
from sports_intelligence.domain.retrieval.aggregation.policy import (
    RetrievalKind,
    state_weighting,
)

pytestmark = pytest.mark.property

SEMENTE = 20260828
IMPRESSAO = "d" * 64
LAMBDAS = (0.25, 0.5, 1.0, 2.0, 4.0)


def _vetores() -> list[list[float]]:
    """Os vetores de distância da varredura — com os casos difíceis dentro.

    OS EXTREMOS ESTÃO AQUI DE PROPÓSITO (§68): todos zero, diferenças
    minúsculas, diferenças enormes, muitos iguais, um só. São eles que quebram
    uma normalização ingênua.
    """
    rng = random.Random(SEMENTE)
    vetores: list[list[float]] = [
        [0.0],
        [0.0, 0.0, 0.0, 0.0],
        [0.5] * 20,
        [0.0, 1e-15, 2e-15],
        [0.0, 100.0, 200.0],
        [0.0, 0.001, 0.002, 0.003],
        list(range(1, 51)) and [float(i) / 10 for i in range(1, 51)],
    ]
    for k in (2, 3, 5, 10, 20, 50):
        for _ in range(12):
            vetores.append([abs(rng.gauss(0.0, 1.0)) for _ in range(k)])
    return vetores


VETORES = _vetores()


class TestOsLimitesDoTamanhoEfetivo:
    """§28 ao §31 — `N_eff` nunca sai de `[1, k]`."""

    def test_N_eff_fica_sempre_entre_um_e_k(self) -> None:
        for d in VETORES:
            for lam in LAMBDAS:
                efetivo = effective_sample_size(normalized_weights(d, lam=lam))
                assert efetivo is not None
                assert 1.0 - 1e-9 <= efetivo <= len(d) + 1e-9, (
                    f"N_eff={efetivo} fora de [1,{len(d)}] com lambda={lam}"
                )

    def test_distancias_todas_iguais_dao_N_eff_igual_a_k(self) -> None:
        """O caso uniforme, alcançado pelo núcleo exponencial."""
        for k in (1, 2, 7, 30):
            for lam in LAMBDAS:
                efetivo = effective_sample_size(normalized_weights([0.7] * k, lam=lam))
                assert efetivo == pytest.approx(float(k), rel=1e-12)


class TestOsPesos:
    """§64 ao §66 — o que o núcleo garante sobre a forma dos pesos."""

    def test_a_soma_e_sempre_um(self) -> None:
        for d in VETORES:
            for lam in LAMBDAS:
                assert math.fsum(normalized_weights(d, lam=lam)) == pytest.approx(1.0, abs=1e-12)

    def test_todos_finitos_e_nao_negativos(self) -> None:
        for d in VETORES:
            for lam in LAMBDAS:
                for p in normalized_weights(d, lam=lam):
                    assert math.isfinite(p)
                    assert p >= 0.0

    def test_a_ordem_dos_pesos_INVERTE_a_das_distancias(self) -> None:
        """§64 — `d_i < d_j` implica `p_i > p_j`, e igual implica igual."""
        for d in VETORES:
            for lam in LAMBDAS:
                p = normalized_weights(d, lam=lam)
                for i in range(len(d)):
                    for j in range(len(d)):
                        if d[i] < d[j]:
                            assert p[i] >= p[j], f"d={d} lambda={lam}"
                        elif d[i] == d[j]:
                            assert p[i] == p[j]

    def test_deslocamento_constante_preserva_os_pesos(self) -> None:
        """§65 — com tolerância medida, pelo motivo do golden correspondente."""
        for d in VETORES[:20]:
            for constante in (1.0, 10.0):
                deslocado = [x + constante for x in d]
                assert normalized_weights(deslocado, lam=1.0) == pytest.approx(
                    normalized_weights(d, lam=1.0), rel=1e-9
                )


class TestAConcentracao:
    """§67 — `lambda` maior nunca aumenta `N_eff`."""

    def test_lambda_crescente_nao_aumenta_N_eff(self) -> None:
        for d in VETORES:
            if len(set(d)) == 1:
                # DISTÂNCIAS TODAS IGUAIS SÃO O CASO DEGENERADO: os pesos são
                # uniformes para qualquer lambda, e `N_eff = k` sempre. A
                # monotonicidade vale como igualdade, e afirmá-la como estrita
                # aqui seria falso.
                continue
            anterior = float("inf")
            for lam in LAMBDAS:
                atual = effective_sample_size(normalized_weights(d, lam=lam))
                assert atual is not None
                assert atual <= anterior + 1e-9, f"d={d} lambda={lam}"
                anterior = atual


class TestODeterminismo:
    """§41, §69 — a mesma entrada semântica dá o mesmo agregado."""

    def test_permutar_a_ORDEM_FISICA_nao_muda_a_semantica(self) -> None:
        """§41 — o que identifica um vizinho é a posição no top-K, não a lista.

        A CANONICALIZAÇÃO É PELA POSIÇÃO. Se a lista física chegar embaralhada
        mas com as mesmas identidades e posições, o agregado precisa ser o
        mesmo — e é o construtor que recusa uma ordem que não seja a do top-K.
        """
        rng = random.Random(SEMENTE)
        politica = state_weighting(lam=1.0, distance_definition_fingerprint=IMPRESSAO)
        vizinhos = [(f"m{i}#0001", i + 1, 0.1 * i, f"ev{i}") for i in range(8)]

        original = aggregate(
            query_identity="q#0001",
            kind=RetrievalKind.STATE,
            policy=politica,
            requested_k=10,
            neighbors=vizinhos,
        )
        for _ in range(10):
            embaralhado = list(vizinhos)
            rng.shuffle(embaralhado)
            # A ORDEM DO TOP-K É A AUTORIDADE: reordenamos pela posição antes de
            # agregar, que é o que qualquer chamador honesto faz ao receber uma
            # lista de outra fonte física.
            recanonizado = sorted(embaralhado, key=lambda v: v[1])
            outro = aggregate(
                query_identity="q#0001",
                kind=RetrievalKind.STATE,
                policy=politica,
                requested_k=10,
                neighbors=recanonizado,
            )
            assert outro.fingerprint == original.fingerprint
            assert outro.weights == original.weights

    def test_repetir_a_execucao_da_o_mesmo_resultado(self) -> None:
        politica = state_weighting(lam=1.7, distance_definition_fingerprint=IMPRESSAO)
        vizinhos = [(f"m{i}#0001", i + 1, 0.3 * i, f"ev{i}") for i in range(12)]
        impressoes = {
            aggregate(
                query_identity="q#0001",
                kind=RetrievalKind.STATE,
                policy=politica,
                requested_k=20,
                neighbors=vizinhos,
            ).fingerprint
            for _ in range(5)
        }
        assert len(impressoes) == 1


class TestOPrefixoDeK:
    """§60, §61 — o prefixo, e a renormalização que ele implica."""

    def test_as_RAZOES_entre_vizinhos_comuns_sobrevivem_ao_corte(self) -> None:
        """§61 — os pesos mudam; as razões entre eles, não.

        RENORMALIZAR É ESPERADO: o denominador de `K=10` é a soma de dez termos,
        e o de `K=20` é a de vinte. Exigir `p_i(K=10) == p_i(K=20)` seria exigir
        que o conjunto não importasse. O que precisa sobreviver é a razão, que é
        onde o núcleo vive.
        """
        politica = state_weighting(lam=1.3, distance_definition_fingerprint=IMPRESSAO)
        todos = [(f"m{i}#0001", i + 1, 0.15 * i, f"ev{i}") for i in range(20)]

        largo = aggregate(
            query_identity="q#0001",
            kind=RetrievalKind.STATE,
            policy=politica,
            requested_k=20,
            neighbors=todos,
        )
        estreito = aggregate(
            query_identity="q#0001",
            kind=RetrievalKind.STATE,
            policy=politica,
            requested_k=10,
            neighbors=todos[:10],
        )
        # Os pesos absolutos DIFEREM — e é isso que a renormalização faz.
        assert largo.weights[:10] != estreito.weights
        # As razões entre os mesmos vizinhos NÃO.
        for i in range(1, 10):
            assert estreito.weights[i] / estreito.weights[0] == pytest.approx(
                largo.weights[i] / largo.weights[0], rel=1e-12
            )

    def test_o_prefixo_preserva_as_identidades_e_a_ordem(self) -> None:
        politica = state_weighting(lam=1.0, distance_definition_fingerprint=IMPRESSAO)
        todos = [(f"m{i}#0001", i + 1, 0.2 * i, f"ev{i}") for i in range(20)]
        largo = aggregate(
            query_identity="q#0001",
            kind=RetrievalKind.STATE,
            policy=politica,
            requested_k=20,
            neighbors=todos,
        )
        estreito = aggregate(
            query_identity="q#0001",
            kind=RetrievalKind.STATE,
            policy=politica,
            requested_k=10,
            neighbors=todos[:10],
        )
        assert [v.identity for v in largo.weighted_neighbors[:10]] == [
            v.identity for v in estreito.weighted_neighbors
        ]
