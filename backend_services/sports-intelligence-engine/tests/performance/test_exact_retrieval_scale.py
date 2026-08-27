"""O BENCHMARK DO PR-06.1: quanto custa o oráculo.

O QUE ELE MEDE, e por que cada número existe:

    uma query        universo, comparáveis, duração, candidatos/s, avaliações
                     de distância/s, pico de memória, objetos e bytes lidos
    muitas queries   p50, p95, p99 e máximo do caminho exato OFFLINE
    a atrição        a fração dos candidatos que sobrevive ao caso completo, e
                     a fração das queries que é comparável
    a memória        ela segue o LOTE, e não o universo

O QUE ELE NÃO É. **Não é SLO.** Um oráculo de força bruta não tem promessa de
latência a cumprir — a promessa de latência é do caminho indexado, que é do
PR-06.4. Estes números existem para dizer QUANTO custa a verdade, e para que o
índice aproximado tenha contra o que ser comparado.

E ELE NÃO OTIMIZA. Se a varredura custar caro, o número entra no relatório do
jeito que saiu: «otimizar até ficar rápido» produziria um oráculo mais barato e
menos comparável, e o PR-06.4 perderia a régua.

O CRITÉRIO É A FORMA DA CURVA, e nunca o segundo absoluto.
"""

from __future__ import annotations

import statistics
import time
from typing import Any, Final

import pytest

from sports_intelligence.domain.retrieval.query import QueryNotComparableError
from tests.performance.test_resolution_100k import _relatar
from tests.support.instrumentation import medindo

pytestmark = pytest.mark.performance

#: Quantas queries o cenário multi-query executa.
#:
#: O NÚMERO É O QUE O CENÁRIO TEM. O corpus do E2E de recuperação são doze
#: partidas; a metade de avaliação tem sete, e sete vezes noventa e um cortes
#: dão seiscentas e trinta e sete queries possíveis. Cem é uma amostra
#: determinística delas — as cem primeiras em ordem de leitura, e não uma
#: amostra aleatória.
QUERIES_DO_LOTE: Final[int] = 100

K: Final[int] = 10


class TestOCustoDoOraculo:
    """Uma query e cem queries, sobre o dataset normalizado de verdade."""

    async def test_uma_query_e_o_lote_de_queries(
        self,
        database: Any,
        object_store: Any,
    ) -> None:
        from tests.support.dataset_e2e import (
            Montagem,
            construir_versao,
            divisao_na_mediana,
        )
        from tests.support.normalized_e2e import (
            ATOR,
            MontagemNormalizada,
            publicar_versao_crua,
        )
        from tests.support.retrieval_e2e import (
            montar_corpus_de_recuperacao,
            montar_recuperacao,
            publicar_versao_normalizada,
            queries_disponiveis,
        )

        # ---- o INSUMO. O custo dele NÃO entra em número nenhum daqui: ele
        # está medido nos baselines do PR-05.5.1 e do PR-05.5.2.
        publicado = await montar_corpus_de_recuperacao(database, object_store)
        montagem = Montagem(database, object_store)
        saida = await construir_versao(
            montagem,
            publicado,
            split=await divisao_na_mediana(database, publicado),
        )
        crua = await publicar_versao_crua(
            {"montagem": montagem, "saida": saida, "publicado": publicado}
        )
        normalizada = MontagemNormalizada(
            database,
            object_store,
            reference_end_exclusive=crua.spec.reference_end_exclusive,
        )
        ajuste = await normalizada.ajustar.execute(
            source_version_id=crua.id,
            raw_dataset_name="match-state-raw",
            actor=ATOR,
        )
        dados = await publicar_versao_normalizada(
            {
                "montagem": montagem,
                "saida": saida,
                "publicado": publicado,
                "versao_crua": crua,
                "montagem_n": normalizada,
                "ajuste": ajuste,
            }
        )
        versao = dados["versao_n"]

        conteiner = montar_recuperacao(
            database,
            object_store,
            reference_end_exclusive=crua.spec.reference_end_exclusive,
        )
        queries = await queries_disponiveis(
            conteiner.source,
            dataset_name="match-state-normalized",
            version=str(versao.version),
            limite=QUERIES_DO_LOTE,
        )
        assert queries, "o cenário precisa ter queries de avaliação"

        # ---- 1. UMA QUERY --------------------------------------------------
        chave, instante = queries[0]
        contexto = await conteiner.retrieve.resolve(version_id=versao.id, key=chave)
        conteiner.source.reset_counters()
        with medindo("recuperacao - uma query") as medida:
            primeiro = await conteiner.retrieve.execute(version_id=versao.id, key=chave, k=K)
        objetos_de_uma = conteiner.source.objects_read
        bytes_de_uma = conteiner.source.bytes_read

        # ---- 2. O LOTE DE QUERIES ------------------------------------------
        latencias: list[float] = []
        comparaveis = rejeitadas = 0
        universo_total = comparavel_total = 0
        inelegiveis: dict[str, int] = {}
        conteiner.source.reset_counters()
        with medindo("recuperacao - lote") as medida_lote:
            for uma_chave, _ in queries:
                inicio = time.perf_counter()
                try:
                    resultado = await conteiner.retrieve.execute(
                        version_id=versao.id, key=uma_chave, k=K
                    )
                except QueryNotComparableError:
                    rejeitadas += 1
                    continue
                latencias.append(time.perf_counter() - inicio)
                comparaveis += 1
                universo_total += resultado.universe_count
                comparavel_total += resultado.comparable_count
                for motivo, contagem in resultado.ineligible.items():
                    inelegiveis[motivo] = inelegiveis.get(motivo, 0) + contagem

        assert latencias, "nenhuma query do lote foi comparável"
        ordenadas = sorted(latencias)
        p50 = statistics.median(ordenadas)
        p95 = ordenadas[min(len(ordenadas) - 1, int(0.95 * len(ordenadas)))]
        p99 = ordenadas[min(len(ordenadas) - 1, int(0.99 * len(ordenadas)))]
        avaliacoes = comparavel_total
        razao = 0.0 if not universo_total else comparavel_total / universo_total
        taxa_de_query = comparaveis / len(queries)
        por_segundo = 0.0 if medida_lote.segundos <= 0 else avaliacoes / medida_lote.segundos

        _relatar(
            "PR-06.1 - recuperacao exata (oraculo de forca bruta)",
            [
                "-- o insumo (fora desta conta) --",
                f"dataset normalizado     {versao.row_count:_} linhas",
                f"referencia              {versao.counts.reference_rows:_}",
                f"avaliacao               {versao.counts.evaluation_rows:_}",
                f"perfil resolvido        {contexto.profile.axis_count} eixos",
                f"  artefatos FITTED      {ajuste.fitted}",
                f"  DEGENERATE_SCALE      {ajuste.degenerate}",
                f"  INSUFFICIENT_SAMPLE   {ajuste.insufficient}",
                "",
                "-- 1. uma query --",
                f"competicao              {primeiro.competition}",
                f"instante                {instante.text}",
                f"universo                {primeiro.universe_count:_}",
                f"comparaveis             {primeiro.comparable_count:_}",
                f"K                       {primeiro.returned_k}/{primeiro.requested_k}",
                f"duracao                 {medida.segundos * 1000:.1f} ms",
                f"memoria                 {medida.pico_bytes / 1_048_576:.1f} MB",
                f"objetos lidos           {objetos_de_uma}",
                f"bytes lidos             {bytes_de_uma:_}",
                "",
                "-- 2. o lote de queries --",
                f"queries                 {len(queries)}",
                f"  comparaveis           {comparaveis}",
                f"  rejeitadas            {rejeitadas}",
                f"taxa de comparabilidade {taxa_de_query:.1%}",
                f"p50                     {p50 * 1000:.1f} ms",
                f"p95                     {p95 * 1000:.1f} ms",
                f"p99                     {p99 * 1000:.1f} ms",
                f"max                     {ordenadas[-1] * 1000:.1f} ms",
                f"total                   {medida_lote.segundos:.2f} s",
                f"memoria do lote         {medida_lote.pico_bytes / 1_048_576:.1f} MB",
                f"avaliacoes de distancia {avaliacoes:_}",
                f"avaliacoes/s            {por_segundo:,.0f}",
                f"objetos lidos           {conteiner.source.objects_read:_}",
                f"bytes lidos             {conteiner.source.bytes_read:_}",
                "",
                "-- 3. a atricao --",
                f"universo somado         {universo_total:_}",
                f"comparaveis somados     {comparavel_total:_}",
                f"razao de comparaveis    {razao:.1%}",
                *(
                    f"  inelegivel {motivo:<28} {contagem:_}"
                    for motivo, contagem in sorted(inelegiveis.items())
                ),
                "",
                "-- 4. a identidade --",
                f"universo                {primeiro.candidate_universe_fingerprint[:16]}",
                f"perfil                  {primeiro.resolved_profile_fingerprint[:16]}",
                f"distancia               {primeiro.distance_definition_fingerprint[:16]}",
                f"resultado               {primeiro.fingerprint[:16]}",
                "",
                "-- NAO E SLO --",
                "forca bruta offline. A promessa de latencia e do caminho",
                "indexado, e ele e do PR-06.4.",
            ],
        )

        # ---- as afirmações -------------------------------------------------

        # O RESULTADO É EXAUSTIVO, e a contabilidade fecha.
        assert primeiro.exhaustive
        assert primeiro.comparable_count <= primeiro.universe_count
        assert primeiro.returned_k == min(K, primeiro.comparable_count)

        # A MEMÓRIA SEGUE O LOTE. Cem queries sobre o mesmo universo não podem
        # acumular: o oráculo mede e descarta, e o que fica é `K`.
        assert medida_lote.pico_bytes < 512 * 1_048_576, (
            f"o lote reteve {medida_lote.pico_bytes:_} bytes: o oráculo deveria "
            "segurar apenas o lote de leitura e os K melhores"
        )

        # O DETERMINISMO SEMÂNTICO, sob variação de tempo.
        repetido = await conteiner.retrieve.execute(version_id=versao.id, key=chave, k=K)
        assert repetido.fingerprint == primeiro.fingerprint
