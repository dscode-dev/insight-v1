"""A montagem do E2E do PR-06.2 — o corpus com ausência, até `READY`.

ELE REUSA TUDO DO PR-06.1 e troca só o cenário. O caminho é o mesmo: fonte
pública, cotações, resolução, fusão, qualidade, build, canonicalização de
eventos, publicação do corpus, dataset cru, ajuste, normalização, publicação.

O QUE MUDA É O CONTEÚDO DAS FONTES, e a mudança tem um propósito só: produzir
candidatos com coberturas DIFERENTES. Ver o cabeçalho de
`availability_scenario` para a conta.
"""

from __future__ import annotations

from typing import Any

from sports_intelligence.adapters.postgres.database import Database


async def montar_corpus_com_ausencia(
    database: Database, object_store: Any, *, partidas: int | None = None
) -> dict[str, Any]:
    """O corpus READY do cenário com ausência, pelo caminho real."""
    from tests.integration.test_match_state_e2e import (
        _CABECALHO,
        _REGIME,
        EVENTOS,
        montar_corpus_publicado,
    )
    from tests.support import availability_scenario as roteiro
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


async def dataset_com_ausencia(
    database: Database, object_store: Any, *, partidas: int | None = None
) -> dict[str, Any]:
    """Corpus → dataset cru → ajuste → normalizado PUBLICADO.

    ELA DEVOLVE O CONTÊINER JUNTO, e não só a versão: os testes precisam do
    grafo montado sob a fronteira DAQUELA versão crua, e reconstruí-lo em cada
    teste é como duas montagens divergem em silêncio.
    """
    from tests.support.dataset_e2e import Montagem, construir_versao, divisao_na_mediana
    from tests.support.normalized_e2e import (
        ATOR,
        MontagemNormalizada,
        publicar_versao_crua,
    )
    from tests.support.retrieval_e2e import montar_recuperacao, publicar_versao_normalizada

    publicado = await montar_corpus_com_ausencia(database, object_store, partidas=partidas)
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
    return {**dados, "conteiner": conteiner, "ajuste": ajuste}
