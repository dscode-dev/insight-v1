"""O benchmark PAREADO — Parquet exato contra projeção exata.

AS DUAS METADES RESPONDEM A MESMA COISA. O gate semântico já provou igualdade
de universo, distância, evidência e top-K nos dois caminhos; o que sobra medir é
o CUSTO de chegar lá.

O GATE MEDE O QUE ESTE PR MUDA. A projeção substitui a AQUISIÇÃO dos
candidatos; ela não toca na leitura da linha da QUERY, que continua vindo do
Parquet nos dois caminhos. Por isso o critério primário é o lado do CANDIDATO,
e o de ponta a ponta é «melhorou», e não um múltiplo:

    candidate-side  >= 1.5x       o que a projeção controla
    total p50/p95   estritamente menor

O ALVO ANTIGO DE 2x DE PONTA A PONTA FOI APOSENTADO COMO DEFEITO DE
ESPECIFICAÇÃO, e a aritmética é a prova: com a query-side medida em 18,21 ms de
um total Parquet de 34,01 ms, o teto teórico com custo de candidato ZERO seria
34,01/18,21 ~ 1,87x. Um alvo de 2x exigia otimizar trabalho que este PR não
podia tocar.

A ORDEM É ALTERNADA e a condição é MORNA — as duas declaradas, e iguais para os
dois caminhos.
"""

from __future__ import annotations

import statistics
import time
from typing import Any

import pytest

from sports_intelligence.application.use_cases.projected_retrieval import (
    universe_filter_for,
)

pytestmark = [pytest.mark.performance, pytest.mark.integration]

K = 10
QUERIES = 60
#: O MESMO tamanho de corpus do baseline do PR-06.3 (47 candidatos).
PARTIDAS = 96

#: O gate do lado do candidato, CONGELADO antes de medir a trajetória.
GATE_CANDIDATO = 1.5


def _p(valores: list[float]) -> dict[str, float]:
    o = sorted(valores)
    n = len(o)
    return {
        "p50": statistics.median(o),
        "p95": o[min(n - 1, int(0.95 * n))],
        "p99": o[min(n - 1, int(0.99 * n))],
        "max": o[-1],
    }


class TestOCustoDaProjecao:
    """PR-06.4 — o que a projeção economiza, nos dois caminhos de produção."""

    async def test_parquet_contra_projecao(self, database: Any, object_store: Any) -> None:
        from sports_intelligence.domain.retrieval.trajectory_coverage import (
            QueryInsufficientTrajectoryEvidenceError,
        )
        from sports_intelligence.domain.retrieval.trajectory_window import (
            TrajectoryNotApplicableError,
        )
        from tests.performance.test_resolution_100k import _relatar
        from tests.support.projection_e2e import montar_projecoes
        from tests.support.retrieval_e2e import queries_disponiveis
        from tests.support.trajectory_e2e import dataset_com_movimento

        dados = await dataset_com_movimento(database, object_store, partidas=PARTIDAS)
        proj = await montar_projecoes(dados, database)
        conteiner = dados["conteiner"]
        versao = dados["versao_n"]
        leitor = proj["reader"]

        queries = await queries_disponiveis(
            conteiner.source,
            dataset_name="match-state-normalized",
            version=str(versao.version),
            limite=QUERIES,
        )
        assert queries

        # ================================================== ESTADO ==
        e_parquet: list[float] = []
        e_proj: list[float] = []
        e_resolve: list[float] = []
        e_lookup: list[float] = []
        e_decode: list[float] = []
        e_compute: list[float] = []
        universos: list[float] = []

        for i, (chave, _) in enumerate(queries):
            # O `resolve` é o custo COMPARTILHADO: os dois caminhos o pagam, e
            # medi-lo à parte é o que permite isolar o lado do candidato.
            marca = time.perf_counter()
            await conteiner.retrieve_aware.resolve(version_id=versao.id, key=chave)
            e_resolve.append((time.perf_counter() - marca) * 1000)

            if i % 2 == 0:
                m = time.perf_counter()
                await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=K)
                e_parquet.append((time.perf_counter() - m) * 1000)
                s = await proj["projected_state"].execute(
                    projection_version=proj["state_version"],
                    version_id=versao.id,
                    key=chave,
                    k=K,
                )
                e_proj.append(s.timings.total_ms)
            else:
                s = await proj["projected_state"].execute(
                    projection_version=proj["state_version"],
                    version_id=versao.id,
                    key=chave,
                    k=K,
                )
                e_proj.append(s.timings.total_ms)
                m = time.perf_counter()
                await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=K)
                e_parquet.append((time.perf_counter() - m) * 1000)

            e_lookup.append(s.timings.lookup_ms)
            e_decode.append(s.timings.decode_ms)
            e_compute.append(s.timings.compute_ms)
            universos.append(float(s.universe_rows))

        # ================================================== TRAJETÓRIA ==
        t_parquet: list[float] = []
        t_proj: list[float] = []
        t_resolve: list[float] = []
        t_lookup: list[float] = []
        t_decode: list[float] = []
        t_compute: list[float] = []
        t_universos: list[float] = []
        nao_aplicaveis = recusadas = 0

        for i, (chave, _) in enumerate(queries):
            try:
                marca = time.perf_counter()
                await conteiner.retrieve_trajectory.resolve(version_id=versao.id, key=chave)
                resolucao_ms = (time.perf_counter() - marca) * 1000
            except (TrajectoryNotApplicableError, QueryInsufficientTrajectoryEvidenceError):
                nao_aplicaveis += 1
                continue

            try:
                if i % 2 == 0:
                    m = time.perf_counter()
                    await conteiner.retrieve_trajectory.execute(
                        version_id=versao.id, key=chave, k=K
                    )
                    bruto = (time.perf_counter() - m) * 1000
                    s = await proj["projected_trajectory"].execute(
                        projection_version=proj["trajectory_version"],
                        version_id=versao.id,
                        key=chave,
                        k=K,
                    )
                else:
                    s = await proj["projected_trajectory"].execute(
                        projection_version=proj["trajectory_version"],
                        version_id=versao.id,
                        key=chave,
                        k=K,
                    )
                    m = time.perf_counter()
                    await conteiner.retrieve_trajectory.execute(
                        version_id=versao.id, key=chave, k=K
                    )
                    bruto = (time.perf_counter() - m) * 1000
            except (TrajectoryNotApplicableError, QueryInsufficientTrajectoryEvidenceError):
                recusadas += 1
                continue

            t_resolve.append(resolucao_ms)
            t_parquet.append(bruto)
            t_proj.append(s.timings.total_ms)
            t_lookup.append(s.timings.lookup_ms)
            t_decode.append(s.timings.decode_ms)
            t_compute.append(s.timings.compute_ms)
            t_universos.append(float(s.universe_rows))

        assert t_parquet, "nenhuma query de trajetória mediu"

        def _candidato(total: list[float], resolve: list[float]) -> float:
            """O custo do lado do candidato = total menos o compartilhado."""
            return statistics.median(total) - statistics.median(resolve)

        pe, pp = _p(e_parquet), _p(e_proj)
        e_cand_parquet = _candidato(e_parquet, e_resolve)
        e_cand_proj = _candidato(e_proj, e_resolve)
        e_speedup = e_cand_parquet / e_cand_proj
        e_teto = pe["p50"] / statistics.median(e_resolve)

        te, tp = _p(t_parquet), _p(t_proj)
        t_cand_parquet = _candidato(t_parquet, t_resolve)
        t_cand_proj = _candidato(t_proj, t_resolve)
        t_speedup = t_cand_parquet / t_cand_proj
        t_teto = te["p50"] / statistics.median(t_resolve)

        # ---- leitura de objetos, UMA query --------------------------------
        chave0, _ = queries[0]
        leitor.reset_counters()
        conteiner.source.reset_counters()
        await proj["projected_state"].execute(
            projection_version=proj["state_version"],
            version_id=versao.id,
            key=chave0,
            k=K,
        )
        obj_proj = conteiner.source.objects_read
        sql_proj = leitor.universe_queries
        conteiner.source.reset_counters()
        await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave0, k=K)
        obj_parquet = conteiner.source.objects_read

        contexto = await conteiner.retrieve_aware.resolve(version_id=versao.id, key=chave0)
        plano = await leitor.explain_state_universe(
            projection_version=proj["state_version"],
            universe=universe_filter_for(
                competition=contexto.resolution.competition,
                position=contexto.resolution.snapshot.position,
                exclude_match_id=contexto.resolution.snapshot.key.match_key,
            ),
        )

        _relatar(
            "PR-06.4 - projecao EXATA contra o oraculo Parquet",
            [
                "-- o insumo (fora desta conta) --",
                f"partidas                {PARTIDAS}",
                f"projecao STATE          {proj['state_build'].rows_written:_} linhas "
                f"em {proj['state_build'].duration_s:.1f}s",
                f"projecao TRAJETORIA     {proj['trajectory_build'].rows_written:_} linhas "
                f"em {proj['trajectory_build'].duration_s:.1f}s",
                "",
                "-- condicao --",
                "morna; ordem ALTERNADA por query; mesma query set nos dois caminhos",
                f"queries                 {len(queries)}",
                f"  trajetoria medida     {len(t_parquet)}",
                f"  nao aplicaveis        {nao_aplicaveis}",
                f"  recusadas             {recusadas}",
                "",
                "================ ESTADO ================",
                f"universo p50            {statistics.median(universos):.0f} candidatos",
                f"Parquet   p50 {pe['p50']:7.2f}  p95 {pe['p95']:7.2f}  p99 {pe['p99']:7.2f} ms",
                f"projetado p50 {pp['p50']:7.2f}  p95 {pp['p95']:7.2f}  p99 {pp['p99']:7.2f} ms",
                f"total speedup           {pe['p50'] / pp['p50']:.2f}x",
                f"query-side (comum)      {statistics.median(e_resolve):.2f} ms",
                f"candidate-side Parquet  {e_cand_parquet:.2f} ms",
                f"candidate-side projecao {e_cand_proj:.2f} ms",
                f"CANDIDATE SPEEDUP       {e_speedup:.2f}x  (gate >= {GATE_CANDIDATO}x) "
                f"{'PASSA' if e_speedup >= GATE_CANDIDATO else 'REPROVA'}",
                f"teto de Amdahl          {e_teto:.2f}x",
                f"  lookup {statistics.median(e_lookup):.2f}  "
                f"decode {statistics.median(e_decode):.2f}  "
                f"calculo {statistics.median(e_compute):.2f} ms",
                "",
                "============== TRAJETORIA ==============",
                f"universo p50            {statistics.median(t_universos):.0f} candidatos",
                f"Parquet   p50 {te['p50']:7.2f}  p95 {te['p95']:7.2f}  p99 {te['p99']:7.2f} ms",
                f"projetado p50 {tp['p50']:7.2f}  p95 {tp['p95']:7.2f}  p99 {tp['p99']:7.2f} ms",
                f"total speedup           {te['p50'] / tp['p50']:.2f}x",
                f"query-side (comum)      {statistics.median(t_resolve):.2f} ms",
                f"candidate-side Parquet  {t_cand_parquet:.2f} ms",
                f"candidate-side projecao {t_cand_proj:.2f} ms",
                f"CANDIDATE SPEEDUP       {t_speedup:.2f}x  (gate >= {GATE_CANDIDATO}x) "
                f"{'PASSA' if t_speedup >= GATE_CANDIDATO else 'REPROVA'}",
                f"teto de Amdahl          {t_teto:.2f}x",
                f"  lookup {statistics.median(t_lookup):.2f}  "
                f"decode {statistics.median(t_decode):.2f}  "
                f"calculo {statistics.median(t_compute):.2f} ms",
                "",
                "-- leitura de objetos, UMA query (estado) --",
                f"Parquet  objetos        {obj_parquet}",
                f"projecao objetos        {obj_proj}  (so a QUERY)",
                f"projecao consultas SQL  {sql_proj}",
                "",
                "-- o plano --",
                *[f"  {linha}" for linha in plano.splitlines()[:3]],
            ],
        )

        # ---- os gates -----------------------------------------------------
        assert sql_proj == 1, "uma consulta por query, e nunca uma por candidato"
        assert obj_proj < obj_parquet
        assert "Seq Scan" not in plano

        # Gate C — melhoria MATERIAL do lado do candidato.
        assert e_speedup >= GATE_CANDIDATO, (
            f"ESTADO: candidate-side {e_speedup:.2f}x < {GATE_CANDIDATO}x"
        )
        assert t_speedup >= GATE_CANDIDATO, (
            f"TRAJETORIA: candidate-side {t_speedup:.2f}x < {GATE_CANDIDATO}x"
        )

        # Gate D — ponta a ponta estritamente melhor, nos dois percentis.
        assert pp["p50"] < pe["p50"], "ESTADO: p50 projetado nao e menor"
        assert pp["p95"] < pe["p95"], "ESTADO: p95 projetado nao e menor"
        assert tp["p50"] < te["p50"], "TRAJETORIA: p50 projetado nao e menor"
        assert tp["p95"] < te["p95"], "TRAJETORIA: p95 projetado nao e menor"
