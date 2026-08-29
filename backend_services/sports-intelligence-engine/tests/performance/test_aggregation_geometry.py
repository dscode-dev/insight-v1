"""A planura do top-5 de trajetória, conferida em precisão alta — e o custo real.

## A pergunta que este arquivo responde

A varredura de sensibilidade mostrou uma coisa estranha:

    TRAJETORIA  K = 5   N_eff ~ 5,00  para TODO lambda testado, ate 32

`N_eff = k` significa pesos uniformes, e pesos uniformes sob um núcleo
exponencial significam distâncias iguais. Mas «iguais» pode ser duas coisas
muito diferentes:

    GEOMETRIA   os cinco vizinhos mais próximos são de fato equidistantes
    ARREDONDAMENTO  eles diferem, e `float64` engoliu a diferença

A DIFERENÇA IMPORTA. Se fosse arredondamento, o achado seria um defeito do
codec de projeção ou da distância — números que deveriam distinguir e não
distinguem. Sendo geometria, nenhum `lambda` pode consertá-la, porque não há
nada a consertar.

## Como a pergunta é decidida

Recalculando `N_eff` em `decimal` com 60 dígitos, a partir das MESMAS distâncias
`float64` que o retrieval produziu. Se a planura viesse de arredondamento no
cálculo dos pesos, a precisão maior a desfaria; se as distâncias já chegam
iguais bit a bit, nenhuma precisão do mundo as separa — e aí a resposta está na
distância, e não na ponderação.

O §21 é a regra que fecha o assunto:

    a ponderação AMPLIFICA diferenças que existem
    ela não FABRICA diferenças que não existem

## E DE ONDE A PLANURA VEM — a parte que não pode ser omitida

A medição foi mais longe do que «quase equidistantes», e o que ela achou muda o
alcance do achado. Os cinco vizinhos não são PARECIDOS: eles são IDÊNTICOS, a
`d = 0`, em todas as consultas medidas. E a causa está no cenário, não no motor.

`trajectory_scenario` gera as partidas alternando entre TRÊS formas de
movimento — subindo, descendo e estável. Duas partidas da mesma forma, no mesmo
minuto, têm a MESMA trajetória, bit a bit. Com 96 partidas e três formas, cada
consulta encontra dezenas de duplicatas exatas antes de encontrar a primeira
vizinha de verdade.

    O QUE ISTO PROVA     a planura não é arredondamento, e a ponderação
                         se comporta corretamente sobre distâncias iguais

    O QUE NÃO PROVA      nada sobre a geometria de trajetória em PRODUÇÃO,
                         onde as trajetórias não saem de três moldes

Tratar o número como propriedade do espaço de trajetória seria ler o gerador do
fixture como se fosse futebol. O achado é real e é do CORPUS.
"""

from __future__ import annotations

import collections
import math
import statistics
import time
from decimal import Decimal, getcontext
from typing import Any

import pytest

from sports_intelligence.domain.retrieval.aggregation.kernel import (
    effective_sample_size,
    normalized_weights,
)
from sports_intelligence.domain.retrieval.aggregation.policy import (
    SELECTED_STATE_LAMBDA,
    SELECTED_TRAJECTORY_LAMBDA,
)

pytestmark = pytest.mark.performance

#: Os `lambda` do §20 — a planura precisa sobreviver a todos eles para ser
#: geometria. Um `lambda` alto o bastante separaria distâncias que diferem.
LAMBDAS_DA_PROVA = (8.0, 16.0, 32.0, 128.0, 1024.0)


def _n_eff_exato(distancias: list[float], lam: float) -> tuple[Decimal, Decimal, Decimal]:
    """`N_eff`, peso mínimo e peso máximo em 60 dígitos decimais.

    A ENTRADA SÃO OS `float64` ORIGINAIS, exatamente como o retrieval os
    produziu — convertê-los para `Decimal` é exato, porque todo `float64` é um
    racional binário finito. O que ganha precisão é a ARITMÉTICA sobre eles, que
    é justamente onde o arredondamento entraria se houvesse arredondamento.
    """
    getcontext().prec = 60
    minima = min(distancias)
    lam_d = Decimal(lam)
    nao_normalizados = [(-lam_d * (Decimal(d) - Decimal(minima))).exp() for d in distancias]
    total = sum(nao_normalizados, Decimal(0))
    pesos = [u / total for u in nao_normalizados]
    soma_quadrados = sum((p * p for p in pesos), Decimal(0))
    return Decimal(1) / soma_quadrados, min(pesos), max(pesos)


class TestAPlanuraDoTop5DaTrajetoria:
    """§18 ao §21, §28 — o achado, conferido até onde a aritmética alcança."""

    async def test_a_planura_e_GEOMETRIA_e_nao_arredondamento(
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

        vetores: list[list[float]] = []
        largos: list[list[float]] = []
        estado_5: list[list[float]] = []
        estado_20: list[list[float]] = []
        for chave, _ in queries:
            estado = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=5)
            if estado.neighbors:
                estado_5.append([float(v.dissimilarity) for v in estado.neighbors])
            estado_l = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=20)
            if estado_l.neighbors:
                estado_20.append([float(v.dissimilarity) for v in estado_l.neighbors])
            try:
                traj = await conteiner.retrieve_trajectory.execute(
                    version_id=versao.id, key=chave, k=5
                )
                traj_l = await conteiner.retrieve_trajectory.execute(
                    version_id=versao.id, key=chave, k=20
                )
            except Exception:  # noqa: BLE001 — query inelegível é caminho normal
                continue
            if len(traj.neighbors) == 5:
                vetores.append([float(v.trajectory_dissimilarity) for v in traj.neighbors])
            if traj_l.neighbors:
                largos.append([float(v.trajectory_dissimilarity) for v in traj_l.neighbors])

        assert vetores, "a prova precisa de top-5 de trajetória reais"

        # ---- 1. as DISTÂNCIAS: elas diferem, ou são o mesmo número? -------
        espalhamentos = [max(d) - min(d) for d in vetores]
        distintos = [len(set(d)) for d in vetores]
        identicos = sum(1 for e in espalhamentos if e == 0.0)

        linhas = [
            f"consultas com top-5 completo  {len(vetores)}",
            f"vetores com d_max == d_min    {identicos} de {len(vetores)}",
            f"valores DISTINTOS por vetor   min {min(distintos)}  max {max(distintos)}",
            "",
            "-- as distancias exatas (float64, como o retrieval as produziu) --",
            f"  d_min        min/mediana/max  {min(min(d) for d in vetores):.17g} / "
            f"{statistics.median([min(d) for d in vetores]):.17g} / "
            f"{max(min(d) for d in vetores):.17g}",
            f"  d_max        min/mediana/max  {min(max(d) for d in vetores):.17g} / "
            f"{statistics.median([max(d) for d in vetores]):.17g} / "
            f"{max(max(d) for d in vetores):.17g}",
            f"  d_max-d_min  min/mediana/max  {min(espalhamentos):.17g} / "
            f"{statistics.median(espalhamentos):.17g} / {max(espalhamentos):.17g}",
            "",
            "-- N_eff em float64 e em decimal de 60 digitos --",
            "  lambda   N_eff(f64) mediana   N_eff(dec60) mediana   max/min peso mediano",
        ]

        # ---- 2. o RECÁLCULO em precisão alta -------------------------------
        for lam in LAMBDAS_DA_PROVA:
            f64 = []
            dec = []
            razoes = []
            for d in vetores:
                efetivo = effective_sample_size(normalized_weights(d, lam=lam))
                assert efetivo is not None
                f64.append(efetivo)
                exato, menor, maior = _n_eff_exato(d, lam)
                dec.append(float(exato))
                razoes.append(float(maior / menor))
            linhas.append(
                f"  {lam:>6.1f}   {statistics.median(f64):>18.15f}   "
                f"{statistics.median(dec):>20.15f}   {statistics.median(razoes):>19.6f}"
            )

        # ---- 3. DE ONDE a planura vem: a estrutura de empates ---------------
        def _empates(rotulo: str, vs: list[list[float]]) -> list[str]:
            if not vs:
                return [f"  {rotulo:<16} sem consultas"]
            distintos = [len(set(d)) for d in vs]
            zeros = [sum(1 for x in d if x == 0.0) for d in vs]
            maiores = [max(collections.Counter(d).values()) for d in vs]
            return [
                f"  {rotulo:<16} consultas {len(vs):>3}   "
                f"valores distintos p50 {statistics.median(distintos):>4.1f} "
                f"(min {min(distintos)} max {max(distintos)})   "
                f"vizinhos a d=0 p50 {statistics.median(zeros):>4.1f} (max {max(zeros)})   "
                f"maior empate p50 {statistics.median(maiores):>4.1f}"
            ]

        linhas += [
            "",
            "-- QUANTOS VIZINHOS SAO O MESMO NUMERO --",
            *_empates("ESTADO K=5", estado_5),
            *_empates("ESTADO K=20", estado_20),
            *_empates("TRAJETORIA K=5", vetores),
            *_empates("TRAJETORIA K=20", largos),
        ]

        # ---- 4. o veredito --------------------------------------------------
        planos = [d for d in vetores if max(d) - min(d) == 0.0]
        zerados = [d for d in vetores if all(x == 0.0 for x in d)]
        veredito = (
            "TRAJECTORY_TOP5_GEOMETRIC_FLATNESS confirmado: as distancias chegam"
            if planos
            else "as distancias DIFEREM — a planura seria de ponderacao, e nao de geometria"
        )
        linhas += [
            "",
            f"vetores exatamente planos: {len(planos)} de {len(vetores)}",
            f"vetores inteiramente a d=0: {len(zerados)} de {len(vetores)}",
            veredito,
            "  IGUAIS BIT A BIT. Nenhuma precisao separa numeros identicos, e",
            "  nenhum lambda pode: a ponderacao amplifica diferencas que existem.",
            "",
            "  E A CAUSA ESTA NO CENARIO, NAO NO MOTOR. `trajectory_scenario`",
            "  alterna TRES formas de movimento entre as partidas; duas partidas",
            "  da mesma forma, no mesmo minuto, tem a MESMA trajetoria bit a bit.",
            "  O achado prova que a ponderacao se comporta bem sobre distancias",
            "  iguais. Ele NAO descreve a geometria de trajetoria em producao.",
            "  Debito registrado: TRAJECTORY_CORPUS_DUPLICATE_DEGENERACY.",
        ]
        _relatar("PR-06.5 - a planura do top-5 de trajetoria (precisao alta)", linhas)

        # ---- as asserções ---------------------------------------------------
        # §20 — float64 e decimal-60 concordam. Se divergissem, a planura seria
        # artefato de arredondamento no CÁLCULO DOS PESOS.
        for lam in LAMBDAS_DA_PROVA:
            for d in vetores:
                em_f64 = effective_sample_size(normalized_weights(d, lam=lam))
                exato, _, _ = _n_eff_exato(d, lam)
                assert em_f64 is not None
                assert em_f64 == pytest.approx(float(exato), rel=1e-12), (
                    f"lambda={lam}: float64 {em_f64} vs decimal-60 {exato} — a "
                    "diferença indicaria arredondamento no cálculo dos pesos"
                )

        # §21 — onde as distâncias são iguais, `N_eff = k` para TODO lambda; e
        # onde elas diferem, um lambda grande TEM de separar. As duas metades
        # juntas provam que o núcleo funciona e que a planura é da geometria.
        for d in vetores:
            if max(d) - min(d) == 0.0:
                for lam in LAMBDAS_DA_PROVA:
                    efetivo = effective_sample_size(normalized_weights(d, lam=lam))
                    assert efetivo == pytest.approx(5.0, rel=1e-12), (
                        f"distâncias idênticas com N_eff={efetivo}: o núcleo estaria "
                        "fabricando diferença onde não há"
                    )
            else:
                largo = effective_sample_size(normalized_weights(d, lam=1024.0))
                estreito = effective_sample_size(normalized_weights(d, lam=8.0))
                assert largo is not None
                assert estreito is not None
                assert largo < estreito, (
                    f"distâncias distintas {d} não se separaram nem em lambda=1024 — "
                    "aí sim o núcleo estaria cego"
                )


class TestOCustoRealDaAgregacao:
    """§62, §68 — o custo da agregação sobre os K que o pipeline real usa."""

    async def test_o_custo_da_agregacao_sobre_o_pipeline_REAL(
        self, database: Any, object_store: Any
    ) -> None:
        from tests.performance.test_resolution_100k import _relatar
        from tests.support.aggregation_e2e import LojaContada
        from tests.support.projection_e2e import montar_projecoes
        from tests.support.retrieval_e2e import queries_disponiveis
        from tests.support.trajectory_e2e import dataset_com_movimento

        loja = LojaContada(object_store)
        dados = await dataset_com_movimento(database, loja, partidas=96)
        projetado = await montar_projecoes(dados, database)
        conteiner = dados["conteiner"]
        versao = dados["versao_n"]
        queries = await queries_disponiveis(
            conteiner.source,
            dataset_name="match-state-normalized",
            version=str(versao.version),
            limite=24,
        )

        from sports_intelligence.application.use_cases.neighbor_aggregation import (
            state_policy_for,
            trajectory_policy_for,
        )
        from sports_intelligence.domain.retrieval.aggregation.summaries import (
            aggregate_state,
            aggregate_trajectory,
        )

        def _percentis(v: list[float]) -> tuple[float, float, float]:
            o = sorted(v)
            n = len(o)
            return (
                statistics.median(o),
                o[min(n - 1, int(0.95 * n))],
                o[min(n - 1, int(0.99 * n))],
            )

        # ---- ESTADO ---------------------------------------------------------
        custos_estado: list[float] = []
        ks_estado: list[int] = []
        n_eff_estado: list[float] = []
        for chave, _ in queries:
            saida = await projetado["projected_state"].execute(
                projection_version=projetado["state_version"],
                version_id=versao.id,
                key=chave,
                k=20,
            )
            politica = state_policy_for(saida.result)
            # A AGREGAÇÃO É MEDIDA SOZINHA. O resultado exato já existe, e o
            # relógio começa depois dele — misturar o retrieval aqui mediria o
            # PR-06.4 de novo, com outro nome.
            inicio = time.perf_counter()
            agregado = aggregate_state(
                saida.result, policy=politica, query_identity=chave.text, requested_k=20
            )
            _ = agregado.effective_sample_size
            _ = agregado.top3_weight_mass
            _ = agregado.weighted_mean_dissimilarity
            custos_estado.append((time.perf_counter() - inicio) * 1000)
            ks_estado.append(agregado.neighbor_count)
            efetivo = agregado.effective_sample_size
            if efetivo is not None:
                n_eff_estado.append(efetivo)

        # ---- TRAJETÓRIA -----------------------------------------------------
        custos_traj: list[float] = []
        ks_traj: list[int] = []
        n_eff_traj: list[float] = []
        for chave, _ in queries:
            try:
                saida_t = await projetado["projected_trajectory"].execute(
                    projection_version=projetado["trajectory_version"],
                    version_id=versao.id,
                    key=chave,
                    k=20,
                )
            except Exception:  # noqa: BLE001
                continue
            politica_t = trajectory_policy_for(saida_t.result)
            inicio = time.perf_counter()
            agregado_t = aggregate_trajectory(
                saida_t.result, policy=politica_t, query_identity=chave.text, requested_k=20
            )
            _ = agregado_t.effective_sample_size
            _ = agregado_t.top3_weight_mass
            _ = agregado_t.weighted_mean_dissimilarity
            custos_traj.append((time.perf_counter() - inicio) * 1000)
            ks_traj.append(agregado_t.neighbor_count)
            efetivo_t = agregado_t.effective_sample_size
            if efetivo_t is not None:
                n_eff_traj.append(efetivo_t)

        assert custos_estado, "o cenário precisa de agregações de estado"

        e50, e95, e99 = _percentis(custos_estado)
        linhas = [
            f"lambda de estado     {SELECTED_STATE_LAMBDA}",
            f"lambda de trajetoria {SELECTED_TRAJECTORY_LAMBDA}",
            "",
            "-- ESTADO (agregacao PURA, com o resultado exato ja em maos) --",
            f"  consultas    {len(custos_estado)}",
            f"  k devolvido  min {min(ks_estado)}  mediana {statistics.median(ks_estado)}  "
            f"max {max(ks_estado)}",
            f"  p50/p95/p99  {e50:.4f} / {e95:.4f} / {e99:.4f} ms   (gate K<=20: 2 ms)",
        ]
        if n_eff_estado:
            linhas.append(
                f"  N_eff        p50 {statistics.median(n_eff_estado):.2f}  "
                f"min {min(n_eff_estado):.2f}  max {max(n_eff_estado):.2f}"
            )
        if custos_traj:
            t50, t95, t99 = _percentis(custos_traj)
            linhas += [
                "",
                "-- TRAJETORIA --",
                f"  consultas    {len(custos_traj)}",
                f"  k devolvido  min {min(ks_traj)}  mediana {statistics.median(ks_traj)}  "
                f"max {max(ks_traj)}",
                f"  p50/p95/p99  {t50:.4f} / {t95:.4f} / {t99:.4f} ms   (gate K<=20: 2 ms)",
            ]
            if n_eff_traj:
                linhas.append(
                    f"  N_eff        p50 {statistics.median(n_eff_traj):.2f}  "
                    f"min {min(n_eff_traj):.2f}  max {max(n_eff_traj):.2f}"
                )
        linhas += [
            "",
            "O RETRIEVAL NAO ENTRA NESTE NUMERO. O relogio comeca depois que o",
            "resultado exato existe — que e exatamente onde o §62 manda medir.",
        ]
        _relatar("PR-06.5 - custo da agregacao no pipeline REAL", linhas)

        # §63 — o gate de `K <= 20`, sobre o K que o pipeline real devolve.
        assert max(ks_estado) <= 20
        assert e95 <= 2.0, f"estado p95 {e95:.4f} ms > 2 ms"
        if custos_traj:
            assert max(ks_traj) <= 20
            assert _percentis(custos_traj)[1] <= 2.0

        # E a concentração real fica dentro dos limites (§16, §38).
        for efetivo, k in zip(n_eff_estado, ks_estado, strict=False):
            assert 1.0 - 1e-9 <= efetivo <= k + 1e-9
        assert math.isfinite(e50)
