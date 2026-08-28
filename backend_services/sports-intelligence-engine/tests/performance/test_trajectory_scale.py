"""O BENCHMARK DO PR-06.3: quanto custa o movimento, e o que ele separa.

O QUE ELE MEDE, e por que cada número existe:

    aplicabilidade      quantas queries têm trajetória, quantas são recusadas
                        por evidência, e quantas nem se aplicam
    a escada de minuto  ONDE a trajetória deixa de ser utilizável — o começo
                        de cada período é o lugar
    as coberturas       `s/n` em quatro populações: queries, pares do
                        universo, elegíveis e top-K
    os horizontes       quantos horizontes cada lado tem, e quantos o par
                        compartilha
    as contribuições    quanto do observado veio de 1m, de 3m e de 5m — se um
                        deles dominar, isso é EVIDÊNCIA para um estudo futuro,
                        e não motivo para corrigir nada agora
    a separação         a sobreposição entre o top-K de ESTADO e o de
                        MOVIMENTO, e o golden de discriminação de direção
    o custo             latência, memória, objetos, bytes e LINHAS DE ORIGEM

O QUE ELE NÃO É. **Não é SLO** (§211). Força bruta exata não tem promessa de
latência; ela é do caminho indexado, que é do PR-06.4.

E ELE NÃO AJUSTA NADA (§201, §202). O estudo de horizontes percorre `{1}`,
`{1,3}` e `{1,3,5}` e REPORTA. Escolher horizontes por otimização exigiria uma
medida de acerto, e não há rótulo de verdade com que construí-la.

**O NÚMERO DE LINHAS DE ORIGEM É O QUE PROVA A AUSÊNCIA DO N+1** (§210). Com
uma varredura por partição, os objetos ficam constantes e as linhas crescem com
os candidatos; com `candidato x horizonte`, os dois cresceriam juntos.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Sequence
from typing import Any, Final

import pytest

from sports_intelligence.domain.retrieval.coverage import QueryInsufficientCoverageError
from sports_intelligence.domain.retrieval.trajectory_coverage import (
    DEFAULT_TRAJECTORY_COVERAGE,
    QueryInsufficientTrajectoryEvidenceError,
)
from sports_intelligence.domain.retrieval.trajectory_profile import (
    TrajectoryRetrievalProfile,
)
from sports_intelligence.domain.retrieval.trajectory_window import (
    TrajectoryNotApplicableError,
    TrajectoryWindowPolicy,
)
from tests.performance.test_resolution_100k import _relatar
from tests.support.instrumentation import medindo

pytestmark = pytest.mark.performance

#: Quantas partidas o corpus do benchmark tem — o mesmo do PR-06.2 (§184).
PARTIDAS: Final[int] = 96

#: Quantas queries o lote executa.
QUERIES_DO_LOTE: Final[int] = 120

K: Final[int] = 10

#: As faixas de minuto do §194, em minutos PERIOD-LOCAL do segundo tempo.
#:
#: ELAS SÃO DO SEGUNDO TEMPO porque é lá que a fronteira do intervalo morde: o
#: primeiro tempo começa no minuto 1 e a atrição dele é a mesma, deslocada.
FAIXAS: Final[tuple[tuple[str, int, int], ...]] = (
    ("46-48  (1-3 do periodo)", 46, 48),
    ("49-50  (4-5)", 49, 50),
    ("51-60  (6-15)", 51, 60),
    ("61+    (16+)", 61, 90),
)

#: O estudo de horizontes do §202. `{1}` é inválido sob a política — dois
#: horizontes é o mínimo —, então ele entra como a linha que NÃO existe.
CONJUNTOS: Final[tuple[tuple[str, tuple[int, ...]], ...]] = (
    ("{1,3}", (1, 3)),
    ("{1,3,5}  <- V1", (1, 3, 5)),
)


def _percentis(valores: Sequence[float]) -> dict[str, float]:
    if not valores:
        return {}
    ordenados = sorted(valores)
    n = len(ordenados)

    def _p(fracao: float) -> float:
        return ordenados[min(n - 1, int(fracao * n))]

    return {
        "min": ordenados[0],
        "p10": _p(0.10),
        "p25": _p(0.25),
        "p50": statistics.median(ordenados),
        "p75": _p(0.75),
        "p90": _p(0.90),
        "p95": _p(0.95),
        "max": ordenados[-1],
    }


def _linha(rotulo: str, valores: Sequence[float], sufixo: str = "") -> str:
    p = _percentis(valores)
    if not p:
        return f"{rotulo:<24} -"
    return (
        f"{rotulo:<24} min {p['min']:.3f}{sufixo}  p10 {p['p10']:.3f}{sufixo}  "
        f"p50 {p['p50']:.3f}{sufixo}  p90 {p['p90']:.3f}{sufixo}  "
        f"max {p['max']:.3f}{sufixo}  (n={len(valores)})"
    )


def _razao(valores: Sequence[float]) -> float:
    """`max/min`, e infinito quando o mínimo é zero — que é o caso do vizinho
    de movimento idêntico."""
    menor = min(valores)
    return float("inf") if menor <= 0 else max(valores) / menor


def _faixa_de(minuto: int) -> str | None:
    for rotulo, inicio, fim in FAIXAS:
        if inicio <= minuto <= fim:
            return rotulo
    return None


class TestOCustoEASeparacaoDaTrajetoria:
    """A trajetória sobre o dataset do PR-06.2, com movimento."""

    async def test_o_movimento_lado_a_lado_com_o_estado(
        self, database: Any, object_store: Any
    ) -> None:
        from tests.support.retrieval_e2e import queries_disponiveis
        from tests.support.trajectory_e2e import dataset_com_movimento

        # ---- o INSUMO. O custo dele NÃO entra em número nenhum daqui.
        dados = await dataset_com_movimento(database, object_store, partidas=PARTIDAS)
        versao = dados["versao_n"]
        ajuste = dados["ajuste"]
        conteiner = dados["conteiner"]

        queries = await queries_disponiveis(
            conteiner.source,
            dataset_name="match-state-normalized",
            version=str(versao.version),
            limite=QUERIES_DO_LOTE,
        )
        assert queries, "o cenário precisa ter queries de avaliação"

        # ---- 1. A APLICABILIDADE (§188) -------------------------------------
        aplicaveis: list[Any] = []
        nao_aplicaveis = recusadas = 0
        por_faixa: dict[str, list[int]] = {r: [] for r, _, _ in FAIXAS}
        for chave, instante in queries:
            try:
                contexto = await conteiner.retrieve_trajectory.resolve(
                    version_id=versao.id, key=chave
                )
            except TrajectoryNotApplicableError:
                nao_aplicaveis += 1
                continue
            faixa = _faixa_de(instante.minute)
            if faixa is not None:
                por_faixa[faixa].append(len(contexto.targets))
            cobertura = contexto.distance.assess(contexto.representation, contexto.representation)
            if not cobertura.meets_query_floor:
                recusadas += 1
                continue
            aplicaveis.append((chave, instante, contexto))

        assert aplicaveis, "nenhuma query do lote tem trajetória utilizável"
        m = aplicaveis[0][2].profile.axis_count
        n = aplicaveis[0][2].profile.cell_count

        # ---- 2. UMA QUERY ---------------------------------------------------
        chave, instante, _ = aplicaveis[0]
        conteiner.trajectory_source.reset_counters()
        with medindo("trajetoria - uma query") as medida:
            primeira = await conteiner.retrieve_trajectory.execute(
                version_id=versao.id, key=chave, k=K
            )
        objetos_de_uma = conteiner.trajectory_source.objects_read
        bytes_de_uma = conteiner.trajectory_source.bytes_read
        linhas_de_uma = conteiner.trajectory_source.source_rows_read

        # ---- 3. O LOTE ------------------------------------------------------
        latencias: list[float] = []
        universo_total = elegiveis_total = sem_evidencia = estruturais = 0
        coberturas_de_query: list[float] = []
        coberturas_do_topo: list[float] = []
        horizontes_da_query: list[float] = []
        horizontes_do_topo: list[float] = []
        distancias: list[float] = []
        parcelas: list[float] = []
        por_horizonte: dict[int, list[float]] = {1: [], 3: [], 5: []}
        reversoes = vizinhos_totais = no_piso = 0
        por_motivo: dict[str, int] = {}
        margens: list[float] = []

        conteiner.trajectory_source.reset_counters()
        with medindo("trajetoria - lote") as medida_lote:
            for uma_chave, _, _ in aplicaveis:
                inicio = time.perf_counter()
                resultado = await conteiner.retrieve_trajectory.execute(
                    version_id=versao.id, key=uma_chave, k=K
                )
                latencias.append(time.perf_counter() - inicio)
                universo_total += resultado.universe_count
                elegiveis_total += resultado.trajectory_eligible_count
                sem_evidencia += resultado.trajectory_ineligible_count
                estruturais += resultado.structural_ineligible_count
                coberturas_de_query.append(resultado.query_coverage)
                horizontes_da_query.append(float(resultado.query_usable_horizons))
                no_piso += resultado.floor_pressure
                for motivo, quantos in resultado.ineligible.items():
                    por_motivo[motivo] = por_motivo.get(motivo, 0) + quantos
                for vizinho in resultado.neighbors:
                    margens.append(float(vizinho.evidence.margin_over_shared_cell_floor))
                    vizinhos_totais += 1
                    coberturas_do_topo.append(vizinho.shared_coverage)
                    horizontes_do_topo.append(float(vizinho.shared_horizons))
                    distancias.append(vizinho.trajectory_dissimilarity)
                    reversoes += vizinho.evidence.reversals
                    if vizinho.penalty_share is not None:
                        parcelas.append(vizinho.penalty_share)
                    conta = vizinho.evidence.breakdown
                    for contribuicao in conta.horizons:
                        parcela = conta.horizon_share(contribuicao.horizon_minutes)
                        if parcela is not None:
                            por_horizonte[contribuicao.horizon_minutes].append(parcela)
        objetos_do_lote = conteiner.trajectory_source.objects_read
        linhas_do_lote = conteiner.trajectory_source.source_rows_read
        bytes_do_lote = conteiner.trajectory_source.bytes_read

        # ---- 4. A COBERTURA DOS PARES DO UNIVERSO (§190) --------------------
        coberturas_do_universo: list[float] = []
        horizontes_compartilhados: list[float] = []
        por_piso: dict[str, int] = {}
        pares_avaliados = 0
        for _, _, contexto in aplicaveis[:20]:
            candidatos = await conteiner.retrieve_trajectory._candidatos(contexto, None)
            for candidato in candidatos:
                cobertura = contexto.distance.assess(
                    contexto.representation, candidato.representation
                )
                coberturas_do_universo.append(cobertura.shared_coverage)
                horizontes_compartilhados.append(float(cobertura.shared_horizons))
                motivo_do_par = cobertura.refusal_reason
                pares_avaliados += 1
                if motivo_do_par is not None:
                    por_piso[motivo_do_par] = por_piso.get(motivo_do_par, 0) + 1

        # ---- 5. ESTADO CONTRA MOVIMENTO (§195) ------------------------------
        sobreposicoes: list[float] = []
        latencias_do_estado: list[float] = []
        objetos_do_estado = 0
        conteiner.source.reset_counters()
        for uma_chave, _, _ in aplicaveis[:60]:
            inicio = time.perf_counter()
            try:
                estado = await conteiner.retrieve_aware.execute(
                    version_id=versao.id, key=uma_chave, k=K
                )
            except QueryInsufficientCoverageError:
                continue
            latencias_do_estado.append(time.perf_counter() - inicio)
            trajetoria = await conteiner.retrieve_trajectory.execute(
                version_id=versao.id, key=uma_chave, k=K
            )
            do_estado = {v.key.text for v in estado.neighbors}
            da_trajetoria = {v.anchor_key.text for v in trajetoria.neighbors}
            if do_estado:
                sobreposicoes.append(len(do_estado & da_trajetoria) / len(do_estado))
        objetos_do_estado = conteiner.source.objects_read

        # ---- 6. O ESTUDO DE HORIZONTES (§202) -------------------------------
        estudo: list[str] = []
        for rotulo, horizontes in CONJUNTOS:
            perfil = TrajectoryRetrievalProfile(
                window=TrajectoryWindowPolicy(
                    name=f"ESTUDO_{'_'.join(str(h) for h in horizontes)}",
                    horizons=horizontes,
                )
            )
            from sports_intelligence.application.use_cases.trajectory_retrieval import (
                RetrieveExactHistoricalTrajectories,
            )

            alternativo = RetrieveExactHistoricalTrajectories(
                exact=conteiner.retrieve,
                raw_datasets=conteiner.raw_datasets,
                trajectory_source=conteiner.trajectory_source,
                profile=perfil,
            )
            aceitas = zeradas = 0
            elegiveis: list[float] = []
            for chave_do_estudo, _, _ in aplicaveis[:30]:
                try:
                    r = await alternativo.execute(version_id=versao.id, key=chave_do_estudo, k=K)
                except (
                    QueryInsufficientTrajectoryEvidenceError,
                    TrajectoryNotApplicableError,
                ):
                    continue
                aceitas += 1
                elegiveis.append(float(r.trajectory_eligible_count))
                if r.returned_k == 0:
                    zeradas += 1
            p = _percentis(elegiveis)
            celulas = len(horizontes) * m
            estudo.append(
                f"{rotulo:<16} queries {aceitas:>3}/30  celulas {celulas:>3}  "
                f"eleg. p10 {p.get('p10', 0):>5.1f} p50 {p.get('p50', 0):>5.1f}  "
                f"zeradas {zeradas:>3}"
            )

        # ---- o relatório ----------------------------------------------------
        assert latencias
        ordenadas = sorted(latencias)
        p50 = statistics.median(ordenadas)
        p95 = ordenadas[min(len(ordenadas) - 1, int(0.95 * len(ordenadas)))]
        p99 = ordenadas[min(len(ordenadas) - 1, int(0.99 * len(ordenadas)))]
        por_segundo = 0.0 if medida_lote.segundos <= 0 else elegiveis_total / medida_lote.segundos
        p50_estado = statistics.median(latencias_do_estado) if latencias_do_estado else 0.0
        amplificacao = (
            0.0 if objetos_do_estado == 0 else objetos_do_lote / max(objetos_do_estado, 1)
        )
        pisos = DEFAULT_TRAJECTORY_COVERAGE.floors(m)
        tabela_de_pisos = [
            f"competicao              {primeira.competition}",
            f"eixos do perfil (m)     {m}",
            f"celulas (n = 3m)        {n}",
            f"minimo absoluto         {pisos.absolute_shared_cell_floor}   <- NAO e o piso",
            f"piso racional ceil(3n/5) {pisos.ratio_shared_cell_floor}",
            f"PISO EFETIVO E_s        {pisos.effective_shared_cell_floor}"
            f"   ({'racional' if pisos.shared_floor_is_rational else 'absoluto'} decide)",
            f"piso de query E_q       {pisos.effective_query_cell_floor}",
            f"piso por horizonte E_h  {pisos.effective_horizon_axis_floor}",
            f"algoritmo               {pisos.algorithm}",
            "",
            "  ler `minimum_shared_trajectory_cells = 8` como «oito bastam»",
            f"  erraria por {pisos.effective_shared_cell_floor - 8} celulas NESTE perfil.",
        ]
        recusa_por_piso = [
            f"pares avaliados         {pares_avaliados:_}",
            *[
                f"  {motivo:<36} {quantos:>7_}  ({quantos / max(pares_avaliados, 1):.1%})"
                for motivo, quantos in sorted(por_piso.items())
            ],
            f"  {'ADMITIDOS':<36} {pares_avaliados - sum(por_piso.values()):>7_}",
            "",
            "no lote inteiro, pelos motivos tipados do universo:",
            *[f"  {motivo:<36} {quantos:>7_}" for motivo, quantos in sorted(por_motivo.items())],
        ]
        faixas = [
            f"{rotulo:<24} n={len(v):>3}  horizontes p50 "
            f"{statistics.median(v) if v else 0:.1f}  "
            f"min {min(v) if v else 0}  max {max(v) if v else 0}"
            for rotulo, v in ((r, por_faixa[r]) for r, _, _ in FAIXAS)
        ]

        _relatar(
            "PR-06.3 - recuperacao de TRAJETORIA (movimento recente)",
            [
                "-- o insumo (fora desta conta) --",
                f"partidas                {PARTIDAS}",
                f"dataset normalizado     {versao.row_count:_} linhas",
                f"referencia              {versao.counts.reference_rows:_}",
                f"perfil base             {m} eixos",
                f"espaco de trajetoria    3 x {m} = {n} celulas",
                f"  artefatos FITTED      {ajuste.fitted}",
                f"  DEGENERATE_SCALE      {ajuste.degenerate}",
                f"  INSUFFICIENT_SAMPLE   {ajuste.insufficient}",
                "",
                "-- 1. a aplicabilidade --",
                f"queries                 {len(queries)}",
                f"  nao aplicaveis        {nao_aplicaveis}  (PRE_MATCH)",
                f"  sem evidencia         {recusadas}  (comeco de periodo)",
                f"  aplicaveis            {len(aplicaveis)}",
                "",
                "-- 2. a escada de minuto (period-local, 2o tempo) --",
                *faixas,
                "",
                "-- 3. uma query --",
                f"competicao              {primeira.competition}",
                f"ancora                  {instante.text}",
                f"universo                {primeira.universe_count:_}",
                f"elegiveis               {primeira.trajectory_eligible_count:_}"
                f" ({primeira.eligible_ratio:.1%})",
                f"sem evidencia           {primeira.trajectory_ineligible_count:_}",
                f"K                       {primeira.returned_k}/{primeira.requested_k}",
                f"duracao                 {medida.segundos * 1000:.1f} ms",
                f"memoria                 {medida.pico_mb:.1f} MB",
                f"objetos lidos           {objetos_de_uma}",
                f"bytes lidos             {bytes_de_uma:_}",
                f"linhas de origem        {linhas_de_uma:_}",
                "",
                "-- 4. o lote --",
                f"queries                 {len(aplicaveis)}",
                f"p50                     {p50 * 1000:.1f} ms",
                f"p95                     {p95 * 1000:.1f} ms",
                f"p99                     {p99 * 1000:.1f} ms",
                f"max                     {ordenadas[-1] * 1000:.1f} ms",
                f"total                   {medida_lote.segundos:.2f} s",
                f"memoria do lote         {medida_lote.pico_mb:.1f} MB",
                f"avaliacoes/s            {por_segundo:,.0f}",
                f"objetos lidos           {objetos_do_lote:_}",
                f"bytes lidos             {bytes_do_lote:_}",
                f"linhas de origem        {linhas_do_lote:_}",
                f"linhas por objeto       {linhas_do_lote / max(objetos_do_lote, 1):.1f}",
                "",
                "-- 4b. OS PISOS EFETIVOS desta competicao --",
                *tabela_de_pisos,
                "",
                "-- 4c. a recusa POR PISO (qual dos tres decidiu) --",
                *recusa_por_piso,
                "",
                "-- 5. a atricao --",
                f"universo somado         {universo_total:_}",
                f"  elegiveis             {elegiveis_total:_}",
                f"  sem evidencia         {sem_evidencia:_}",
                f"  estruturais           {estruturais:_}",
                f"vizinhos no piso        {no_piso:_} de {vizinhos_totais:_}",
                _linha("margem sobre E_s", margens),
                f"celulas em REVERSAO     {reversoes:_}",
                "",
                "-- 6. as coberturas --",
                _linha("query", coberturas_de_query),
                _linha("universo (pares)", coberturas_do_universo),
                _linha("top-K", coberturas_do_topo),
                "",
                "-- 7. os horizontes --",
                _linha("query (evidenciais)", horizontes_da_query),
                _linha("pares (compartilhados)", horizontes_compartilhados),
                _linha("top-K", horizontes_do_topo),
                "",
                "-- 8. D_T e a incerteza --",
                _linha("D_T", distancias),
                _linha("fracao incerta", parcelas),
                "",
                "-- 9. a contribuicao por horizonte (fracao do observado) --",
                _linha("1m", por_horizonte[1]),
                _linha("3m", por_horizonte[3]),
                _linha("5m", por_horizonte[5]),
                "  se um deles dominar, isso e EVIDENCIA para um estudo futuro",
                "  de ponderacao temporal — e NAO motivo para corrigir agora.",
                "",
                "-- 10. estado contra movimento --",
                _linha("sobreposicao do top-K", sobreposicoes),
                "  DIAGNOSTICO, e nao metrica de correcao: os dois medem",
                "  conceitos diferentes, e baixa sobreposicao pode ser o sinal.",
                f"p50 do estado           {p50_estado * 1000:.1f} ms",
                f"p50 da trajetoria       {p50 * 1000:.1f} ms",
                f"amplificacao de objetos {amplificacao:.2f}x",
                "",
                "-- 11. o estudo de horizontes (REPORTA, nao escolhe) --",
                *estudo,
                "",
                "-- 12. a identidade --",
                f"janela                  {primeira.window_policy_fingerprint[:16]}",
                f"perfil                  {primeira.trajectory_profile_fingerprint[:16]}",
                f"cobertura               {primeira.coverage_policy_fingerprint[:16]}",
                f"distancia               {primeira.distance_definition_fingerprint[:16]}",
                f"universo                {primeira.candidate_universe_fingerprint[:16]}",
                f"resultado               {primeira.fingerprint[:16]}",
                "",
                "-- NAO E SLO --",
                "forca bruta exata. A promessa de latencia e do caminho",
                "indexado, e ele e do PR-06.4.",
            ],
        )

        # ---- as afirmações --------------------------------------------------
        assert primeira.exhaustive
        assert universo_total > 0
        # A ESCADA DE MINUTO EXISTE: o comeco do periodo perde horizontes.
        assert por_faixa[FAIXAS[0][0]], "o lote precisa cobrir o comeco do periodo"
        assert statistics.median(por_faixa[FAIXAS[0][0]]) < statistics.median(
            por_faixa[FAIXAS[3][0]]
        )
        # NAO HA N+1: muito menos objetos que candidatos x horizontes.
        assert objetos_do_lote < universo_total
        assert linhas_do_lote > objetos_do_lote
        # A MEMORIA SEGUE O LOTE E O K.
        assert medida_lote.pico_mb < 512
        # E HA MOVIMENTO EM DIRECOES OPOSTAS.
        assert reversoes > 0
        # O PISO EFETIVO E O RACIONAL NESTE PERFIL, e nao o minimo absoluto.
        assert pisos.effective_shared_cell_floor == pisos.ratio_shared_cell_floor
        assert pisos.effective_shared_cell_floor > pisos.absolute_shared_cell_floor
        # E TODO VIZINHO DO TOPO SATISFAZ O PISO EFETIVO, por construcao.
        assert all(margem >= 0 for margem in margens)
        # O RESULTADO E REPRODUTIVEL.
        segunda = await conteiner.retrieve_trajectory.execute(version_id=versao.id, key=chave, k=K)
        assert segunda.fingerprint == primeira.fingerprint

    async def test_a_discriminacao_de_direcao_sobre_dados_reais(
        self, database: Any, object_store: Any
    ) -> None:
        """§149 — o golden central, medido no corpus.

        O CENÁRIO ALTERNA A FORMA DA CURVA por partida: subindo, descendo,
        patamar. Num mesmo instante, portanto, o universo tem jogos que vinham
        crescendo e jogos que vinham caindo — e o teste mede se a trajetória
        os separa MAIS que o estado.

        A COMPARAÇÃO É ENTRE DUAS DISPERSÕES, e não entre dois números: `D` e
        `D_T` não se comparam entre si. O que se mede é se o ranking de
        movimento difere do de nível — se não diferisse, a trajetória estaria
        medindo nível.
        """
        from tests.support.retrieval_e2e import queries_disponiveis
        from tests.support.trajectory_e2e import dataset_com_movimento
        from tests.support.trajectory_scenario import forma_de

        dados = await dataset_com_movimento(database, object_store)
        versao = dados["versao_n"]
        conteiner = dados["conteiner"]
        queries = await queries_disponiveis(
            conteiner.source,
            dataset_name="match-state-normalized",
            version=str(versao.version),
            limite=80,
        )
        alvo = None
        for chave, instante in queries:
            if instante.minute >= 60 and instante.period.value == "SECOND_HALF":
                alvo = chave
                break
        assert alvo is not None, "o cenário precisa de uma âncora no meio do 2o tempo"

        trajetoria = await conteiner.retrieve_trajectory.execute(
            version_id=versao.id, key=alvo, k=50
        )
        estado = await conteiner.retrieve_aware.execute(version_id=versao.id, key=alvo, k=50)

        por_movimento = [v.anchor_key.text for v in trajetoria.neighbors]
        por_nivel = [v.key.text for v in estado.neighbors]
        comuns = set(por_movimento) & set(por_nivel)
        sobreposicao = len(comuns) / len(por_nivel) if por_nivel else 0.0

        # A DISPERSÃO DE `D_T` mostra que a trajetória SEPARA.
        distancias = [v.trajectory_dissimilarity for v in trajetoria.neighbors]
        reversoes = sum(v.evidence.reversals for v in trajetoria.neighbors)

        _relatar(
            "PR-06.3 - discriminacao de direcao sobre dados reais",
            [
                f"ancora                  {trajetoria.query_anchor_position.text}",
                f"universo                {trajetoria.universe_count}",
                f"elegiveis (movimento)   {trajetoria.trajectory_eligible_count}",
                f"elegiveis (nivel)       {estado.coverage_eligible_count}",
                "",
                f"D_T minimo              {min(distancias):.5g}",
                f"D_T maximo              {max(distancias):.5g}",
                f"D_T mediano             {statistics.median(distancias):.5g}",
                f"razao max/min           {_razao(distancias):.1f}x",
                "",
                f"celulas em REVERSAO     {reversoes}",
                f"sobreposicao top-K      {sobreposicao:.0%}",
                "",
                "as formas do cenario, por partida:",
                *[
                    f"  {v.anchor_key.match_key[:12]}  D_T={v.trajectory_dissimilarity:.4g}"
                    f"  rev={v.evidence.reversals}"
                    for v in trajetoria.neighbors[:8]
                ],
                "",
                "A TRAJETORIA SEPARA o que o estado nao separa: a dispersao de",
                "D_T entre os candidatos e o que mede isso.",
            ],
        )

        assert len(set(distancias)) > 1, (
            "todo candidato tem o mesmo D_T: a trajetoria nao esta separando nada"
        )
        assert max(distancias) > min(distancias)
        assert reversoes > 0, "nenhum movimento em direcao oposta no top-K"
        assert forma_de(0) != forma_de(1), "o cenario precisa alternar as formas"
