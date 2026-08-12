"""POST /v1/intake/matches — a porta HTTP da ingestão.

Uma das duas portas; a outra é `scripts/atlas_intake.py`. Ambas chamam
`atlas.intake.service.ingest` e não fazem mais nada — nenhuma valida por
conta própria, nenhuma escreve direto. Dois caminhos de escrita que cada um
conhece as regras acabam discordando delas, e a discordância é silenciosa.

O CÓDIGO HTTP DIZ O QUE ACONTECEU COM O LOTE:

    200  tudo aceito
    207  o lote foi processado e o corpo traz o resultado de cada linha
    4xx  o lote NÃO foi processado (sem X-Operator, corpo inválido)

207 cobre tanto o lote parcial quanto o inteiramente recusado, e isso é
deliberado. A primeira versão devolvia 422 quando nada era aceito, o que é
semanticamente defensável e na prática ruim: a cadeia console → Control
Plane → Atlas trata 4xx como erro de upstream e descarta o corpo — que é
exatamente o relatório dizendo POR QUE cada linha foi recusada. Um código de
status que torna a explicação inalcançável é pior que nenhum.

E 207 quer dizer literalmente "o corpo traz um status por item", que é o
caso mesmo quando todos os itens falharam. O que 4xx passa a significar aqui
é só uma coisa: o lote nem chegou a ser avaliado.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from atlas.api.deps import get_container, require_internal_token
from atlas.intake.composition import BLOCOS, PRECEDENCIA
from atlas.intake.contract import SCHEMA_VERSION, example, example_parcial
from atlas.intake.service import SimulacaoRepository, ingest

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/intake",
    tags=["intake"],
    dependencies=[Depends(require_internal_token)],
)

#: Um lote grande demais mantém uma transação e uma conexão HTTP abertas por
#: minutos. Arquivos maiores que isto são o caso de uso do CLI, que não tem
#: cliente esperando do outro lado.
MAX_BATCH = 5_000


class MatchBatch(BaseModel):
    matches: list[dict] = Field(min_length=1, max_length=MAX_BATCH)


def _operator(x_operator: str | None) -> str:
    """Quem está mandando. Exigido, não deduzido.

    Sem isto, `ingested_by` vira "api" para todo mundo e a primeira pergunta
    quando um número não fecha — quem colocou isto aqui — deixa de ter
    resposta.
    """
    operator = (x_operator or "").strip()
    if not operator:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cabeçalho X-Operator é obrigatório: identifica quem ingeriu",
        )
    return operator[:128]


@router.get("/contract")
async def contract() -> dict:
    """O contrato vigente e um registro que passa nele.

    Servido pelo próprio serviço para que quem monta o arquivo não precise
    procurar a versão certa em lugar nenhum — e para que o exemplo não possa
    divergir do código que o valida.

    Vêm dois exemplos. O completo é uma fonte que traz tudo; o parcial são
    duas contribuições que sozinhas não viram partida e juntas viram — que é
    o caso real, porque nenhuma fonte pública gratuita traz os quatro blocos.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "example": example(),
        "blocks": list(BLOCOS),
        "source_precedence": list(PRECEDENCIA),
        "composition_example": example_parcial(),
    }


@router.post("/matches")
async def ingest_matches(
    response: Response,
    body: MatchBatch = Body(...),
    simulate: bool = Query(
        default=False,
        alias="simular",
        description="valida o lote inteiro e não grava nada",
    ),
    x_operator: str | None = Header(default=None, alias="X-Operator"),
    container=Depends(get_container),
) -> dict:
    operator = _operator(x_operator)
    repository = container.intake_repository

    target = SimulacaoRepository(await repository.count()) if simulate else repository
    report = await ingest(body.matches, target, via="api", by=operator)

    if simulate or report.rejected == 0:
        response.status_code = status.HTTP_200_OK
    else:
        # Inclui o lote inteiramente recusado — ver o docstring do módulo.
        response.status_code = status.HTTP_207_MULTI_STATUS

    logger.info(
        "atlas_intake_batch",
        extra={
            "via": "api", "operator": operator, "simulated": simulate,
            "submitted": report.submitted, "accepted": report.accepted,
            "rejected": report.rejected, "delta": report.total_after - report.total_before,
        },
    )
    return {**report.as_dict(), "simulated": simulate}


@router.get("/coverage")
async def coverage(container=Depends(get_container)) -> dict:
    """O que o Atlas tem, por competição e temporada."""
    rows = await container.intake_repository.coverage()
    return {"total": sum(row["matches"] for row in rows), "by_season": rows}


@router.get("/rejections")
async def rejections(
    limit: int = Query(default=50, ge=1, le=500),
    container=Depends(get_container),
) -> dict:
    """As últimas recusas, com o motivo de cada uma.

    Existe porque a resposta da ingestão é efêmera: quem enviou pode tê-la
    ignorado, e aí "o Atlas não tem essa partida" viraria mistério.
    """
    return {"rejections": await container.intake_repository.recent_rejections(limit)}


@router.get("/conflicts")
async def conflicts(
    limit: int = Query(default=50, ge=1, le=500),
    container=Depends(get_container),
) -> dict:
    """Desacordos entre fontes sobre o mesmo fato.

    Duas fontes trazendo blocos diferentes e o caso normal — e o ponto de
    compor. Conflito e quando duas trazem o MESMO fato com valores
    diferentes: um placar 2-1 e um 2-2 significam que uma delas esta errada.
    A precedencia resolve qual vence; isto mostra que houve desacordo, para
    que uma fonte ruim seja revista antes de contaminar uma temporada.
    """
    return {"conflicts": await container.intake_repository.conflitos_recentes(limit)}
