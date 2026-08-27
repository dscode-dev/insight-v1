"""O BENCHMARK DO PR-06.2: quanto custa a cobertura, e o que ela recupera.

O QUE ELE MEDE, e por que cada número existe:

    as duas políticas   a MESMA query, o MESMO universo, sob caso completo e
                        sob cobertura compartilhada. A diferença entre os dois
                        é a única coisa que este PR introduziu
    a recuperação       quantos candidatos a MAIS receberam distância, em
                        absoluto e em razão, e quantas queries saíram do zero
    as coberturas       a distribuição de `s/m` em três populações: todo o
                        universo, os elegíveis, e o top-K
    a pressão do piso   quantos elegíveis e quantos vizinhos estão EXATAMENTE
                        na fronteira
    a incerteza         `PenaltyShare` — que fração do número de cada vizinho
                        é ausência, e não discrepância medida
    o custo             latência de uma e de muitas queries, memória, I/O

O QUE ELE NÃO É. **Não é SLO** (§168). Força bruta offline não tem promessa de
latência a cumprir; a promessa é do caminho indexado, que é do PR-06.4.

E ELE NÃO AJUSTA NADA (§160, §162). A tabela de sensibilidade percorre cinco
pisos e REPORTA; ela não escolhe. Escolher um piso por otimização exigiria uma
medida de acerto, e não há rótulo com que construí-la antes do PR-06.5 — o que
sairia de um otimizador seria o piso que maximiza uma métrica inventada.

O CENÁRIO TEM AUSÊNCIA DE VERDADE, e é isso que separa este benchmark do do
PR-06.1 (§146). Lá todo candidato tinha cobertura cheia; aqui a distribuição de
`s` tem três valores, e um deles está abaixo do piso.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Sequence
from typing import Any, Final

import pytest

from sports_intelligence.domain.retrieval.coverage import (
    DEFAULT_COVERAGE_POLICY,
    AvailabilityCoveragePolicy,
    QueryInsufficientCoverageError,
    RationalFloor,
)
from tests.performance.test_resolution_100k import _relatar
from tests.support.instrumentation import medindo

pytestmark = pytest.mark.performance

#: Quantas partidas o corpus do benchmark tem.
#:
#: NOVENTA E SEIS, E NÃO DEZOITO. O §146 diz, por extenso, que a fixture do
#: PR-06.1 — cinco candidatos por query — não sustenta um benchmark científico.
#: Com noventa e seis partidas a metade de referência tem quase cinquenta, e o
#: universo de um instante passa a ter dezenas de candidatos com coberturas
#: diferentes.
PARTIDAS: Final[int] = 96

#: Quantas queries o lote executa.
QUERIES_DO_LOTE: Final[int] = 100

K: Final[int] = 10

#: Os pisos do estudo de sensibilidade (§158). O `3/5` é o da V1.
PISOS: Final[tuple[tuple[str, AvailabilityCoveragePolicy], ...]] = (
    (
        "1/2",
        AvailabilityCoveragePolicy(
            name="SENSIBILIDADE_1_2",
            shared_coverage_floor=RationalFloor(1, 2),
            query_coverage_floor=RationalFloor(1, 2),
        ),
    ),
    ("3/5  <- V1", DEFAULT_COVERAGE_POLICY),
    (
        "2/3",
        AvailabilityCoveragePolicy(
            name="SENSIBILIDADE_2_3",
            shared_coverage_floor=RationalFloor(2, 3),
            query_coverage_floor=RationalFloor(2, 3),
        ),
    ),
    (
        "3/4",
        AvailabilityCoveragePolicy(
            name="SENSIBILIDADE_3_4",
            shared_coverage_floor=RationalFloor(3, 4),
            query_coverage_floor=RationalFloor(3, 4),
        ),
    ),
    (
        "1/1",
        AvailabilityCoveragePolicy(
            name="SENSIBILIDADE_1_1",
            shared_coverage_floor=RationalFloor(1, 1),
            query_coverage_floor=RationalFloor(1, 1),
        ),
    ),
)


def _percentis(valores: Sequence[float]) -> dict[str, float]:
    """Os percentis do §80, quando a amostra os comporta."""
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


def _linha_de_percentis(rotulo: str, valores: Sequence[float], sufixo: str = "") -> str:
    p = _percentis(valores)
    if not p:
        return f"{rotulo:<22} -"
    return (
        f"{rotulo:<22} min {p['min']:.2f}{sufixo}  p10 {p['p10']:.2f}{sufixo}  "
        f"p50 {p['p50']:.2f}{sufixo}  p90 {p['p90']:.2f}{sufixo}  "
        f"max {p['max']:.2f}{sufixo}  (n={len(valores)})"
    )


class TestOCustoEOGanhoDaCobertura:
    """As duas políticas sobre o mesmo universo, e a diferença medida."""

    async def test_as_duas_politicas_lado_a_lado(self, database: Any, object_store: Any) -> None:
        from tests.support.availability_e2e import dataset_com_ausencia
        from tests.support.retrieval_e2e import queries_disponiveis

        # ---- o INSUMO. O custo dele NÃO entra em número nenhum daqui.
        dados = await dataset_com_ausencia(database, object_store, partidas=PARTIDAS)
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

        contexto = await conteiner.retrieve_aware.resolve(version_id=versao.id, key=queries[0][0])
        m = contexto.resolution.profile.axis_count

        # ---- 1. UMA QUERY ---------------------------------------------------
        chave, instante = queries[0]
        conteiner.source.reset_counters()
        with medindo("cobertura - uma query") as medida:
            primeira = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=K)
        objetos_de_uma = conteiner.source.objects_read
        bytes_de_uma = conteiner.source.bytes_read

        # ---- 2. O LOTE, SOB AS DUAS POLÍTICAS -------------------------------
        latencias: list[float] = []
        comparaveis = rejeitadas_aa = rejeitadas_cc = 0
        universo_total = elegiveis_total = completos_total = 0
        sem_cobertura = estruturais = 0
        recuperacao_absoluta = 0
        recuperadas_do_zero = 0
        coberturas_de_query: list[float] = []
        coberturas_do_universo: list[float] = []
        coberturas_elegiveis: list[float] = []
        coberturas_do_topo: list[float] = []
        parcelas_de_incerteza: list[float] = []
        observados: list[float] = []
        incertezas: list[float] = []
        sobreposicoes: list[float] = []
        elegiveis_no_piso = vizinhos_no_piso = vizinhos_totais = 0

        conteiner.source.reset_counters()
        with medindo("cobertura - lote") as medida_lote:
            for uma_chave, _ in queries:
                inicio = time.perf_counter()
                comparacao = await conteiner.compare.execute(
                    version_id=versao.id, key=uma_chave, k=K
                )
                latencias.append(time.perf_counter() - inicio)
                if comparacao.availability_aware_rejected:
                    rejeitadas_aa += 1
                if comparacao.complete_case_rejected:
                    rejeitadas_cc += 1
                if comparacao.availability_aware_rejected:
                    continue
                comparaveis += 1
                universo_total += comparacao.universe_count
                elegiveis_total += comparacao.availability_aware_eligible
                completos_total += comparacao.complete_case_comparable
                recuperacao_absoluta += comparacao.candidate_recovery
                if comparacao.recovered_from_zero:
                    recuperadas_do_zero += 1
                if comparacao.top_k_overlap is not None:
                    sobreposicoes.append(comparacao.top_k_overlap)
                coberturas_de_query.append(comparacao.query_available_count / m)

                resultado = await conteiner.retrieve_aware.execute(
                    version_id=versao.id, key=uma_chave, k=K
                )
                sem_cobertura += resultado.coverage_ineligible_count
                estruturais += resultado.structural_ineligible_count
                vizinhos_totais += resultado.returned_k
                vizinhos_no_piso += resultado.floor_pressure
                for vizinho in resultado.neighbors:
                    coberturas_do_topo.append(vizinho.shared_coverage)
                    observados.append(vizinho.evidence.observed_squared_sum)
                    incertezas.append(vizinho.evidence.missing_penalty_sum)
                    if vizinho.penalty_share is not None:
                        parcelas_de_incerteza.append(vizinho.penalty_share)

        # ---- 3. A DISTRIBUIÇÃO DE COBERTURA DO UNIVERSO INTEIRO -------------
        # ELA É MEDIDA SOBRE OS PARES, e não sobre o top-K: o §79 pede as três
        # populações, e a do universo é a única que mostra o que o piso recusa.
        from sports_intelligence.domain.retrieval.availability import (
            availability_mask,
            count,
            shared_mask,
        )

        for uma_chave, _ in queries[:20]:
            ctx = await conteiner.retrieve_aware.resolve(version_id=versao.id, key=uma_chave)
            perfil = ctx.resolution.profile
            mq = availability_mask(
                feature_keys=perfil.feature_keys,
                values=ctx.resolution.snapshot.values,
                availabilities=ctx.resolution.snapshot.availabilities,
                owner="query",
            )
            for candidato in await conteiner.retrieve.candidates(ctx.resolution):
                mc = availability_mask(
                    feature_keys=perfil.feature_keys,
                    values=candidato.values,
                    availabilities=candidato.availabilities,
                    owner=candidato.key.text,
                )
                s = count(shared_mask(mq, mc))
                coberturas_do_universo.append(s / perfil.axis_count)
                if DEFAULT_COVERAGE_POLICY.admits_pair(shared=s, profile_axes=perfil.axis_count):
                    coberturas_elegiveis.append(s / perfil.axis_count)
                    if not DEFAULT_COVERAGE_POLICY.admits_pair(
                        shared=s - 1, profile_axes=perfil.axis_count
                    ):
                        elegiveis_no_piso += 1

        # ---- 4. A SENSIBILIDADE AO PISO -------------------------------------
        sensibilidade: list[str] = []
        for rotulo, politica in PISOS:
            comparaveis_do_piso = 0
            zerados = 0
            elegiveis: list[int] = []
            coberturas_k: list[float] = []
            for uma_chave, _ in queries[:30]:
                try:
                    r = await conteiner.retrieve_aware.execute(
                        version_id=versao.id, key=uma_chave, k=K, coverage_policy=politica
                    )
                except Exception as erro:
                    if type(erro).__name__ not in {
                        "QueryInsufficientCoverageError",
                        "ProfileInsufficientEvidenceError",
                    }:
                        raise
                    continue
                comparaveis_do_piso += 1
                elegiveis.append(r.coverage_eligible_count)
                if r.returned_k == 0:
                    zerados += 1
                coberturas_k.extend(v.shared_coverage for v in r.neighbors)
            p = _percentis([float(e) for e in elegiveis])
            sensibilidade.append(
                f"{rotulo:<12} queries {comparaveis_do_piso:>3}/30  "
                f"eleg. p10 {p.get('p10', 0):>5.1f} p50 {p.get('p50', 0):>5.1f}  "
                f"zeradas {zerados:>3}  "
                f"cob. do K p50 "
                f"{(statistics.median(coberturas_k) if coberturas_k else 0):.0%}"
            )

        # ---- o relatório ----------------------------------------------------
        assert latencias
        ordenadas = sorted(latencias)
        p50 = statistics.median(ordenadas)
        p95 = ordenadas[min(len(ordenadas) - 1, int(0.95 * len(ordenadas)))]
        p99 = ordenadas[min(len(ordenadas) - 1, int(0.99 * len(ordenadas)))]
        por_segundo = 0.0 if medida_lote.segundos <= 0 else elegiveis_total / medida_lote.segundos
        relativa = 0.0 if not completos_total else recuperacao_absoluta / completos_total

        _relatar(
            "PR-06.2 - recuperacao ciente de disponibilidade",
            [
                "-- o insumo (fora desta conta) --",
                f"partidas                {PARTIDAS}",
                f"dataset normalizado     {versao.row_count:_} linhas",
                f"referencia              {versao.counts.reference_rows:_}",
                f"avaliacao               {versao.counts.evaluation_rows:_}",
                f"perfil resolvido        {m} eixos",
                f"  artefatos FITTED      {ajuste.fitted}",
                f"  DEGENERATE_SCALE      {ajuste.degenerate}",
                f"  INSUFFICIENT_SAMPLE   {ajuste.insufficient}",
                f"piso da V1              {DEFAULT_COVERAGE_POLICY.shared_coverage_floor.text}"
                f" e {DEFAULT_COVERAGE_POLICY.minimum_shared_axes} eixos",
                "",
                "-- 1. uma query --",
                f"competicao              {primeira.competition}",
                f"instante                {instante.text}",
                f"universo                {primeira.universe_count:_}",
                f"elegiveis               {primeira.coverage_eligible_count:_}"
                f" ({primeira.eligible_ratio:.1%})",
                f"sem cobertura           {primeira.coverage_ineligible_count:_}",
                f"estruturais             {primeira.structural_ineligible_count:_}",
                f"K                       {primeira.returned_k}/{primeira.requested_k}",
                f"duracao                 {medida.segundos * 1000:.1f} ms",
                f"memoria                 {medida.pico_mb:.1f} MB",
                f"objetos lidos           {objetos_de_uma}",
                f"bytes lidos             {bytes_de_uma:_}",
                "",
                "-- 2. o lote (as DUAS politicas por query) --",
                f"queries                 {len(queries)}",
                f"  comparaveis (AA)      {comparaveis}",
                f"  rejeitadas (AA)       {rejeitadas_aa}",
                f"  rejeitadas (CC)       {rejeitadas_cc}",
                f"p50                     {p50 * 1000:.1f} ms",
                f"p95                     {p95 * 1000:.1f} ms",
                f"p99                     {p99 * 1000:.1f} ms",
                f"max                     {ordenadas[-1] * 1000:.1f} ms",
                f"total                   {medida_lote.segundos:.2f} s",
                f"memoria do lote         {medida_lote.pico_mb:.1f} MB",
                f"avaliacoes/s            {por_segundo:,.0f}",
                f"objetos lidos           {conteiner.source.objects_read:_}",
                f"bytes lidos             {conteiner.source.bytes_read:_}",
                "",
                "-- 3. a recuperacao de candidatos --",
                f"universo somado         {universo_total:_}",
                f"  caso completo         {completos_total:_}",
                f"  ciente de disp.       {elegiveis_total:_}",
                f"recuperacao absoluta    {recuperacao_absoluta:+_}",
                f"recuperacao relativa    {relativa:+.1%}",
                f"queries que saiam vazias{recuperadas_do_zero:>4}",
                f"sem cobertura (somado)  {sem_cobertura:_}",
                f"estruturais (somado)    {estruturais:_}",
                "",
                "-- 4. as coberturas --",
                _linha_de_percentis("query", coberturas_de_query),
                _linha_de_percentis("universo (pares)", coberturas_do_universo),
                _linha_de_percentis("elegiveis", coberturas_elegiveis),
                _linha_de_percentis("top-K", coberturas_do_topo),
                "",
                "-- 5. a pressao do piso --",
                f"elegiveis no piso       {elegiveis_no_piso:_} de {len(coberturas_elegiveis):_}",
                f"vizinhos no piso        {vizinhos_no_piso:_} de {vizinhos_totais:_}",
                "",
                "-- 6. observado contra incerteza --",
                _linha_de_percentis("observado", observados),
                _linha_de_percentis("incerteza", incertezas),
                _linha_de_percentis("fracao incerta", parcelas_de_incerteza),
                "",
                "-- 7. a sobreposicao com o caso completo --",
                _linha_de_percentis("top-K comum", sobreposicoes),
                "  DIAGNOSTICO, e nao metrica de correcao: uma sobreposicao",
                "  baixa e o comportamento pretendido.",
                "",
                "-- 8. a sensibilidade ao piso (REPORTA, nao escolhe) --",
                *sensibilidade,
                "",
                "-- 9. a identidade --",
                f"perfil                  {primeira.resolved_profile_fingerprint[:16]}",
                f"cobertura               {primeira.coverage_policy_fingerprint[:16]}",
                f"distancia               {primeira.distance_definition_fingerprint[:16]}",
                f"universo                {primeira.candidate_universe_fingerprint[:16]}",
                f"resultado               {primeira.fingerprint[:16]}",
                "",
                "-- NAO E SLO --",
                "forca bruta offline. A promessa de latencia e do caminho",
                "indexado, e ele e do PR-06.4.",
            ],
        )

        # ---- as afirmações --------------------------------------------------
        assert primeira.exhaustive
        assert universo_total > 0
        # A RECUPERACAO E POSITIVA, e o cenario tem ausencia de verdade.
        assert recuperacao_absoluta > 0
        assert sem_cobertura > 0, "o piso não recusou ninguém: o cenário perdeu a ausência"
        assert len(set(coberturas_do_universo)) > 1
        # A MEMORIA SEGUE O LOTE E O K, e nao o universo.
        assert medida_lote.pico_mb < 512
        # E O RESULTADO E REPRODUTIVEL.
        segunda = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=K)
        assert segunda.fingerprint == primeira.fingerprint

    async def test_uma_query_sem_cobertura_nao_varre(
        self, database: Any, object_store: Any
    ) -> None:
        """§86 — a recusa da query custa ZERO leitura de candidato.

        ELE É UM BENCHMARK, e não um teste de comportamento: o comportamento
        tem teste próprio no domínio. O que se mede aqui é que a recusa não
        paga o preço da varredura — que é o que a torna barata o bastante para
        ser o caminho normal de uma query incompleta.
        """
        from tests.support.availability_e2e import dataset_com_ausencia
        from tests.support.retrieval_e2e import queries_disponiveis

        dados = await dataset_com_ausencia(database, object_store)
        versao = dados["versao_n"]
        conteiner = dados["conteiner"]
        queries = await queries_disponiveis(
            conteiner.source,
            dataset_name="match-state-normalized",
            version=str(versao.version),
            limite=1,
        )
        chave = queries[0][0]
        contexto = await conteiner.retrieve_aware.resolve(version_id=versao.id, key=chave)
        m = contexto.resolution.profile.axis_count

        # AS DUAS LINHAS DE BASE. A primeira é o que custa só ACHAR a query;
        # a segunda, a recuperação completa. A recusa tem de custar a primeira.
        conteiner.source.reset_counters()
        await conteiner.retrieve_aware.resolve(version_id=versao.id, key=chave)
        objetos_da_query = conteiner.source.objects_read
        bytes_da_query = conteiner.source.bytes_read

        conteiner.source.reset_counters()
        await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=K)
        objetos_da_varredura = conteiner.source.objects_read
        bytes_da_varredura = conteiner.source.bytes_read

        conteiner.source.reset_counters()
        with medindo("recusa da query") as medida, pytest.raises(QueryInsufficientCoverageError):
            await conteiner.retrieve_aware.execute(
                version_id=versao.id,
                key=chave,
                k=K,
                coverage_policy=AvailabilityCoveragePolicy(
                    name="QUERY_IMPOSSIVEL",
                    minimum_profile_axes=1,
                    minimum_query_available_axes=m + 1,
                    minimum_shared_axes=1,
                ),
            )
        _relatar(
            "PR-06.2 - o custo de recusar uma query",
            [
                f"perfil                  {m} eixos",
                f"duracao                 {medida.segundos * 1000:.1f} ms",
                "",
                "                        recusa   so a query   varredura",
                f"objetos lidos           {conteiner.source.objects_read:>6}"
                f"   {objetos_da_query:>10}   {objetos_da_varredura:>9}",
                f"bytes lidos             {conteiner.source.bytes_read:>6_}"
                f"   {bytes_da_query:>10_}   {bytes_da_varredura:>9_}",
                "",
                "A RECUSA CUSTA EXATAMENTE O QUE CUSTA ACHAR A QUERY, e nada",
                "alem: nenhum candidato e lido. O que sobra e a DIVIDA DE",
                "BUSCA DA QUERY medida no PR-06.1 — `load_query` varre a",
                "metade de AVALIACAO ate achar a chave.",
            ],
        )
        # NENHUM CANDIDATO FOI LIDO: a recusa custa a busca da query, e so.
        assert conteiner.source.objects_read == objetos_da_query
        assert conteiner.source.bytes_read == bytes_da_query
