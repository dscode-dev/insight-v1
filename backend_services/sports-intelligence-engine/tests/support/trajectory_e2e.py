"""A montagem do E2E do PR-06.3 — o corpus com MOVIMENTO, até `READY`.

ELE REUSA TUDO DO PR-06.2 e troca só a posição dos chutes. O caminho é o
mesmo, e o perfil resolvido tem de sair IGUAL: a comparação entre estado e
trajetória só significa alguma coisa quando os dois medem sobre os mesmos
eixos.
"""

from __future__ import annotations

from typing import Any

from sports_intelligence.adapters.postgres.database import Database


async def montar_corpus_com_movimento(
    database: Database, object_store: Any, *, partidas: int | None = None
) -> dict[str, Any]:
    """O corpus READY do cenário com curvas — pelo caminho real."""
    from tests.integration.test_match_state_e2e import (
        _CABECALHO,
        _REGIME,
        EVENTOS,
        montar_corpus_publicado,
    )
    from tests.support import trajectory_scenario as roteiro
    from tests.support.retrieval_scenario import semear_traducoes, tabela_de_tipos

    corpus = (
        roteiro.cenario(_REGIME)
        if partidas is None
        else roteiro.cenario(_REGIME, partidas=partidas)
    )
    return await montar_corpus_publicado(
        database,
        object_store,
        cenario=corpus,
        fonte_publica=roteiro.fonte_publica(corpus),
        fonte_de_eventos=roteiro.fonte_de_eventos(corpus, _CABECALHO),
        fonte_de_odds=roteiro.fonte_de_odds(corpus),
        traducoes=semear_traducoes(EVENTOS),
        tabela_de_tipos=tabela_de_tipos(EVENTOS),
    )


async def dataset_com_movimento(
    database: Database, object_store: Any, *, partidas: int | None = None
) -> dict[str, Any]:
    """Corpus → dataset cru → ajuste → normalizado PUBLICADO → contêiner."""
    from tests.support.dataset_e2e import Montagem, construir_versao, divisao_na_mediana
    from tests.support.normalized_e2e import (
        ATOR,
        MontagemNormalizada,
        publicar_versao_crua,
    )
    from tests.support.retrieval_e2e import (
        montar_recuperacao,
        publicar_versao_normalizada,
    )

    publicado = await montar_corpus_com_movimento(database, object_store, partidas=partidas)
    montagem = Montagem(database, object_store)
    saida = await construir_versao(
        montagem, publicado, split=await divisao_na_mediana(database, publicado)
    )
    crua = await publicar_versao_crua(
        {"montagem": montagem, "saida": saida, "publicado": publicado}
    )
    normalizada = MontagemNormalizada(
        database, object_store, reference_end_exclusive=crua.spec.reference_end_exclusive
    )
    ajuste = await normalizada.ajustar.execute(
        source_version_id=crua.id, raw_dataset_name="match-state-raw", actor=ATOR
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
    conteiner = montar_recuperacao(
        database, object_store, reference_end_exclusive=crua.spec.reference_end_exclusive
    )
    return {**dados, "conteiner": conteiner, "ajuste": ajuste, "versao_crua": crua}


async def ancoras_por_minuto(
    fonte: Any, *, dataset_name: str, version: str, minutos: tuple[int, ...]
) -> dict[int, Any]:
    """Uma chave de AVALIAÇÃO para cada minuto pedido do SEGUNDO tempo.

    ELA EXISTE PARA OS CENÁRIOS DE HORIZONTE (§181 ao §183). O E2E precisa de
    âncoras em minutos específicos — 47 tem um horizonte, 49 tem dois, 51 tem
    três — e procurá-las varrendo `queries_disponiveis` faria cada teste
    depender da ordem de leitura do bucket.
    """
    import io

    import pyarrow.parquet as pq

    from sports_intelligence.domain.features.dataset.rows import (
        HistoricalFeatureSnapshotKey,
    )
    from sports_intelligence.domain.features.dataset.split import DatasetSplit

    procurados = set(minutos)
    encontradas: dict[int, Any] = {}
    for chave in await fonte._objetos(
        dataset_name=dataset_name, version=version, split=DatasetSplit.EVALUATION
    ):
        bruto = await fonte._baixar(chave)
        tabela = pq.read_table(
            io.BytesIO(bruto), columns=["match_id", "grid_index", "period", "minute"]
        )
        for partida, indice, fase, minuto in zip(
            tabela.column("match_id").to_pylist(),
            tabela.column("grid_index").to_pylist(),
            tabela.column("period").to_pylist(),
            tabela.column("minute").to_pylist(),
            strict=True,
        ):
            if str(fase) != "SECOND_HALF" or int(minuto) not in procurados:
                continue
            encontradas.setdefault(
                int(minuto),
                HistoricalFeatureSnapshotKey(match_key=str(partida), grid_index=int(indice)),
            )
        if len(encontradas) == len(procurados):
            break
    return encontradas
