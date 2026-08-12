"""POST /v1/query — perguntar ao Atlas em uma das cinco categorias.

    GET  /v1/query/categorias   o que dá para perguntar, e o que cada uma olha
    POST /v1/query              a consulta

A resposta é sempre DESCRITIVA: o que aconteceu em partidas parecidas, com a
escala ao lado do score e a incerteza nomeada. Nada aqui afirma coisa alguma
sobre a partida consultada.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, status

from atlas.api.deps import get_container, require_internal_token
from atlas.vector.lenses import LENTES, NAO_DESCREVEM_DESFECHO
from atlas.vector.query import SCHEMA, Consulta

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/query",
    tags=["query"],
    dependencies=[Depends(require_internal_token)],
)


@router.get("/categorias")
async def categorias() -> dict:
    """As cinco lentes, com a pergunta e as dimensões que cada uma usa.

    Servido pelo serviço para que quem monta uma consulta não precise
    descobrir em outro lugar o que existe — e para que a lista não possa
    divergir do código que a aplica.
    """
    return {
        "schema_version": SCHEMA,
        "categorias": [
            {
                "categoria": l.categoria,
                "pergunta": l.pergunta,
                "descreve": l.descreve,
                "dimensoes": list(l.pesos),
                "filtros": list(l.filtros),
                # A validação NÃO vem aqui: ela é por competição, e esta
                # rota não sabe qual será consultada. Um número nesta lista
                # seria lido como "o valor da lente", que é justamente a
                # afirmação que deixou de existir. Quem quer a cobertura
                # pergunta em /v1/query/validacao.
                "descreve_desfecho_quando_conclusiva": (
                    l.categoria not in NAO_DESCREVEM_DESFECHO
                ),
            }
            for l in LENTES.values()
        ],
    }


@router.post("")
async def consultar(body: dict = Body(...), container=Depends(get_container)) -> dict:
    try:
        consulta = Consulta.from_dict(body)
    except ValueError as erro:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(erro)
        ) from None

    if consulta.categoria not in LENTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"categoria desconhecida: {consulta.categoria!r} — "
                f"use uma de {', '.join(sorted(LENTES))}"
            ),
        )

    resposta = await container.query_service.responder(consulta)
    logger.info(
        "atlas_query",
        extra={
            "categoria": consulta.categoria,
            "vizinhos": resposta.get("vizinhanca", {}).get("encontrados", 0),
            "incerteza": resposta.get("incerteza", {}).get("score"),
        },
    )
    return resposta


@router.get("/validacao")
async def validacao(container=Depends(get_container)) -> dict:
    """Onde o Atlas pode afirmar alguma coisa — e onde ele só tem vizinhos.

    A pergunta que a rede social precisa fazer antes de publicar: cada lente
    vira um post, e um post de uma lente não demonstrada naquela competição é
    uma frase com a mesma forma de uma medida e nenhuma medida por trás.

    Devolve a medida crua por (lente, competição) e um resumo por competição.
    Competição sem linha nenhuma não é omitida do resumo: "nunca medida" é a
    resposta, e uma ausência silenciosa seria lida como "sem ressalvas".
    """
    repositorio = container.query_service.validacoes
    medidas = await repositorio.carregar()
    return {
        "schema_version": SCHEMA,
        "por_lente_e_competicao": [
            m.as_dict() | {"lente": m.lente} for m in medidas.values()
        ],
        "cobertura": await repositorio.cobertura(),
    }
