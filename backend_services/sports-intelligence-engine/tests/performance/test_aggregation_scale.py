"""A sensibilidade de `lambda` e o custo da agregação.

DUAS COISAS DIFERENTES NUM ARQUIVO SÓ, e vale dizer qual é qual:

    a SENSIBILIDADE escolhe `lambda` pela GEOMETRIA do retrieval
    a ESCALA mede que a agregação é barata perto do retrieval

E NENHUMA DAS DUAS OLHA DESFECHO. A tabela de sensibilidade mede concentração —
`N_eff`, massa do topo, peso máximo — sobre distâncias reais. Ela não sabe o
placar, e escolher `lambda` por acerto de previsão seria vazar a camada de
inferência para dentro da agregação.

O QUE A TABELA NÃO É: uma medida de qualidade de previsão de futebol. Ela
descreve a forma da distribuição de pesos, e nada além disso.
"""

from __future__ import annotations

import statistics
import time
import tracemalloc
from typing import Any

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

pytestmark = pytest.mark.performance

#: A grade de `lambda`.
#:
#: ELA FOI ESTENDIDA POR MEDIÇÃO, e não por tentativa. A primeira grade parava
#: em `4.0` e produziu `N_eff ~ K` em toda ela — o que parecia «nenhum lambda
#: diferencia». A geometria do top-K disse outra coisa:
#:
#:     ESTADO       espalhamento p50 0,2710   lambda p/ razão 10:1  p50  8,50
#:     TRAJETÓRIA   espalhamento p50 0,1434   lambda p/ razão 10:1  p50 16,06
#:
#: A grade não alcançava a resposta. Escolher `4.0` por ser o maior valor
#: presente teria sido escolher pelo formato da grade, e não pelos dados.
LAMBDAS = (0.25, 1.0, 4.0, 8.0, 16.0, 32.0)
KS = (5, 10, 20)
ESCALAS = (5, 10, 20, 50, 100, 1000)


def _p(valores: list[float]) -> dict[str, float]:
    o = sorted(valores)
    n = len(o)
    return {
        "p10": o[min(n - 1, int(0.10 * n))],
        "p50": statistics.median(o),
        "p90": o[min(n - 1, int(0.90 * n))],
    }


class TestOCustoDaAgregacao:
    """§82 ao §85 — a agregação é `O(K)` e barata."""

    def test_a_escala_e_linear_e_o_custo_e_baixo(self) -> None:
        from tests.performance.test_resolution_100k import _relatar

        rng_base = [0.05 * i for i in range(max(ESCALAS))]
        politica = state_weighting(lam=1.0, distance_definition_fingerprint="d" * 64)

        linhas = []
        medidos: dict[int, float] = {}
        p95_por_k: dict[int, float] = {}
        for k in ESCALAS:
            vizinhos = [(f"m{i}#0001", i + 1, rng_base[i], f"ev{i}") for i in range(k)]
            amostras = []
            # ---- a MEMÓRIA (§67): pico de alocação de UMA agregação ---------
            #
            # ELA É MEDIDA NUMA EXECUÇÃO SÓ, e não no laço inteiro. O pico do
            # laço incluiria as duzentas listas de amostras e diria mais sobre o
            # arnês que sobre a agregação. `tracemalloc` mede alocação Python,
            # que é a métrica certa para «o agregado é O(K)?».
            tracemalloc.start()
            unico = aggregate(
                query_identity="q#0001",
                kind=RetrievalKind.STATE,
                policy=politica,
                requested_k=k,
                neighbors=vizinhos,
            )
            _ = unico.effective_sample_size
            _, pico = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            for _ in range(200):
                inicio = time.perf_counter()
                agregado = aggregate(
                    query_identity="q#0001",
                    kind=RetrievalKind.STATE,
                    policy=politica,
                    requested_k=k,
                    neighbors=vizinhos,
                )
                # As leituras derivadas entram na conta: são o que o consumidor
                # de fato pede ao agregado.
                _ = agregado.effective_sample_size
                _ = agregado.top3_weight_mass
                _ = agregado.weighted_mean_dissimilarity
                amostras.append((time.perf_counter() - inicio) * 1000)
            estat = _p(amostras)
            ordenadas = sorted(amostras)
            p95 = ordenadas[int(0.95 * len(ordenadas))]
            p99 = ordenadas[int(0.99 * len(ordenadas))]
            medidos[k] = estat["p50"]
            p95_por_k[k] = p95
            linhas.append(
                f"K={k:>5}  p50 {estat['p50']:.4f}  p95 {p95:.4f}  p99 {p99:.4f} ms  "
                f"por vizinho {estat['p50'] / k * 1000:.2f} us  "
                f"pico {pico / 1024:.1f} KiB ({pico / k:.0f} B/vizinho)"
            )

        # ---- linearidade: o custo POR VIZINHO fica aproximadamente constante
        por_vizinho = {k: medidos[k] / k for k in ESCALAS}
        razao = max(por_vizinho.values()) / min(por_vizinho.values())

        _relatar(
            "PR-06.5 - custo da agregacao (nucleo puro)",
            [
                "-- escala --",
                *linhas,
                "",
                f"custo por vizinho: max/min = {razao:.2f}x",
                "  proximo de 1 indica O(K); crescimento com K indicaria O(K^2)",
                "",
                "-- os gates (§63), medidos em p95 --",
                f"K<=20  p95 {max(p95_por_k[k] for k in (5, 10, 20)):.4f} ms  (<= 2 ms)",
                f"K<=100 p95 {max(p95_por_k[k] for k in (50, 100)):.4f} ms  (<= 5 ms)",
            ],
        )

        # §63 — os gates de latência, em p95 e não em p50: o contrato fala de
        # p95, e afirmá-lo com a mediana seria afirmar coisa mais fraca.
        for k in (5, 10, 20):
            assert p95_por_k[k] <= 2.0, f"K={k}: p95 {p95_por_k[k]:.4f} ms > 2 ms"
        for k in (50, 100):
            assert p95_por_k[k] <= 5.0, f"K={k}: p95 {p95_por_k[k]:.4f} ms > 5 ms"
        # §83 — `O(K)`: o custo por vizinho não pode explodir com K.
        assert razao < 10.0, f"custo por vizinho varia {razao:.2f}x — suspeita de O(K^2)"


class TestASensibilidadeDeLambda:
    """§23, §24, §88 ao §92 — a escolha de `lambda`, só pela geometria."""

    async def test_a_tabela_de_sensibilidade_sobre_dados_REAIS(
        self, database: Any, object_store: Any
    ) -> None:
        from tests.performance.test_resolution_100k import _relatar
        from tests.support.retrieval_e2e import queries_disponiveis
        from tests.support.trajectory_e2e import dataset_com_movimento

        dados = await dataset_com_movimento(database, object_store, partidas=96)
        conteiner = dados["conteiner"]
        versao = dados["versao_n"]
        queries = await queries_disponiveis(
            conteiner.source,
            dataset_name="match-state-normalized",
            version=str(versao.version),
            limite=40,
        )

        # ---- as distâncias REAIS, colhidas uma vez por K ------------------
        por_k_estado: dict[int, list[list[float]]] = {k: [] for k in KS}
        por_k_traj: dict[int, list[list[float]]] = {k: [] for k in KS}
        for chave, _ in queries:
            for k in KS:
                estado = await conteiner.retrieve_aware.execute(
                    version_id=versao.id, key=chave, k=k
                )
                if estado.neighbors:
                    por_k_estado[k].append([float(v.dissimilarity) for v in estado.neighbors])
                try:
                    traj = await conteiner.retrieve_trajectory.execute(
                        version_id=versao.id, key=chave, k=k
                    )
                except Exception:  # noqa: BLE001 — não aplicável/recusada
                    continue
                if traj.neighbors:
                    por_k_traj[k].append(
                        [float(v.trajectory_dissimilarity) for v in traj.neighbors]
                    )

        def _tabela(rotulo: str, dados_por_k: dict[int, list[list[float]]]) -> list[str]:
            linhas = [f"-- {rotulo} --", "  K   lambda  N_eff p10/p50/p90   maxw p50  top3 p50"]
            for k in KS:
                vetores = dados_por_k[k]
                if not vetores:
                    linhas.append(f"{k:>3}   (sem consultas)")
                    continue
                for lam in LAMBDAS:
                    efetivos, maximos, topos = [], [], []
                    for d in vetores:
                        p = normalized_weights(d, lam=lam)
                        efetivo = effective_sample_size(p)
                        if efetivo is None:
                            continue
                        efetivos.append(efetivo)
                        maximos.append(max(p))
                        topos.append(sum(sorted(p, reverse=True)[:3]))
                    if not efetivos:
                        continue
                    e, m, t = _p(efetivos), _p(maximos), _p(topos)
                    linhas.append(
                        f"{k:>3}  {lam:>6.2f}  "
                        f"{e['p10']:>5.2f}/{e['p50']:>5.2f}/{e['p90']:>5.2f}   "
                        f"{m['p50']:>7.3f}  {t['p50']:>7.3f}"
                    )
            return linhas

        def _espalhamento(rotulo: str, vetores: list[list[float]]) -> list[str]:
            """O que separa o vizinho mais proximo do mais distante.

            ESTA E A PERGUNTA QUE A TABELA LEVANTOU. Se `d_max - d_min` for
            pequeno, `exp(-lambda*d)` quase nao diferencia — e o `N_eff` perto
            de `K` nao e um lambda mal escolhido, e sim a geometria do top-K.

            `lambda` NECESSARIO PARA UMA RAZAO ALVO: queremos que o vizinho mais
            distante do top-K receba `1/r` da massa do mais proximo. Como

                w_max / w_min = exp(lambda * (d_max - d_min))

            entao `lambda = ln(r) / espalhamento`.
            """
            import math as _m

            if not vetores:
                return [f"-- {rotulo}: sem consultas --"]
            espalhamentos = [max(d) - min(d) for d in vetores]
            minimos = [min(d) for d in vetores]
            maximos = [max(d) for d in vetores]
            e = _p(espalhamentos)
            necessarios = [_m.log(10.0) / s for s in espalhamentos if s > 1e-12]
            linhas = [
                f"-- {rotulo}: a GEOMETRIA do top-K --",
                f"  d_min      p10/p50/p90  "
                f"{_p(minimos)['p10']:.4f}/{_p(minimos)['p50']:.4f}/{_p(minimos)['p90']:.4f}",
                f"  d_max      p10/p50/p90  "
                f"{_p(maximos)['p10']:.4f}/{_p(maximos)['p50']:.4f}/{_p(maximos)['p90']:.4f}",
                f"  espalhamento p10/p50/p90  {e['p10']:.4f}/{e['p50']:.4f}/{e['p90']:.4f}",
            ]
            if necessarios:
                n = _p(necessarios)
                linhas.append(
                    f"  lambda para razao 10:1  p10/p50/p90  "
                    f"{n['p10']:.2f}/{n['p50']:.2f}/{n['p90']:.2f}"
                )
            return linhas

        _relatar(
            "PR-06.5 - sensibilidade de lambda (GEOMETRIA, nao qualidade)",
            [
                f"queries                 {len(queries)}",
                f"consultas de estado     {len(por_k_estado[10])}",
                f"consultas de trajetoria {len(por_k_traj[10])}",
                "",
                *_espalhamento("ESTADO K=20", por_k_estado[20]),
                "",
                *_espalhamento("TRAJETORIA K=20", por_k_traj[20]),
                "",
                *_tabela("ESTADO", por_k_estado),
                "",
                *_tabela("TRAJETORIA", por_k_traj),
                "",
                "ISTO MEDE CONCENTRACAO DE PESOS, e nao qualidade de previsao.",
                "Nenhum desfecho foi lido para produzir esta tabela.",
            ],
        )

        assert por_k_estado[10], "o cenário precisa de consultas de estado"
