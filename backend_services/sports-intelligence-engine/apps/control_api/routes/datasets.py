"""As rotas do registro de intake.

O UPLOAD É `application/octet-stream` COM O NOME NUM CABEÇALHO, e não
`multipart/form-data`. A escolha custa um pouco de familiaridade e paga em
duas coisas concretas:

    o corpo é o arquivo, e nada mais       nenhum parser de multipart entre a
                                           rede e o nosso hash; um parser a
                                           menos na fronteira menos confiável
                                           que existe

    o limite é cobrado enquanto lê         com multipart, quem decide quando
                                           parar é a biblioteca, e a maioria
                                           bufferiza a parte inteira antes de
                                           entregá-la

Como é exatamente um arquivo por requisição, o envelope de multipart não
resolveria nada que já não esteja resolvido.

`Content-Length` NÃO É USADO COMO LIMITE. Ele é do cliente, e um cliente que
mente sobre o tamanho é justamente o que o limite existe para conter. O teto é
cobrado bloco a bloco durante a leitura, em `StreamingReceiver`.

NENHUMA ROTA DE LEITURA DO CONTEÚDO. Não há `GET /files/{id}/download`. O
arquivo bruto é evidência, não um serviço de arquivos, e publicar um caminho
de leitura transformaria o Control Plane num CDN de dados licenciados.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response, status

from apps.control_api.deps import ActorDep, ContainerDep
from apps.control_api.schemas import (
    CreateDatasetIn,
    DatasetOut,
    DatasetPageOut,
    DatasetSummaryOut,
    FileOut,
    ManifestOut,
    StageIn,
    UploadOut,
    ValidateIn,
    ValidationOut,
)
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.formats import resolve_declared_format
from sports_intelligence.domain.datasets.lifecycle import DatasetLifecycle
from sports_intelligence.domain.datasets.models import DatasetFilter, Page
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.domain.shared.temporal import parse_instant

router = APIRouter(prefix="/v1/datasets", tags=["datasets"])

_CORRELACAO = "X-Correlation-Id"


@router.post("", response_model=DatasetOut, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    corpo: CreateDatasetIn,
    contêiner: ContainerDep,
    ator: ActorDep,
    resposta: Response,
    request: Request,
) -> DatasetOut:
    """Registra o dataset. 201 quando cria, 200 quando já existia.

    A DIFERENÇA DE STATUS É O CONTRATO DA IDEMPOTÊNCIA. Devolver 201 nas duas
    faria o cliente acreditar que criou algo que já estava lá — e um script de
    carga que confia nisso conta datasets criados que ele não criou.
    """
    dataset, criado = await contêiner.register.execute(
        actor=ator,
        name=corpo.name,
        version=corpo.parsed_version(),
        source=corpo.source.to_domain(),
        declared_competitions=frozenset(corpo.declared_competitions),
        declared_seasons=tuple(corpo.declared_seasons),
        description=corpo.description,
        correlation_id=request.headers.get(_CORRELACAO),
    )
    resposta.status_code = (
        status.HTTP_201_CREATED if criado else status.HTTP_200_OK
    )
    return DatasetOut.of(dataset)


@router.get("", response_model=DatasetPageOut)
async def list_datasets(
    contêiner: ContainerDep,
    _: ActorDep,
    competition: Annotated[CompetitionCode | None, Query()] = None,
    lifecycle: Annotated[DatasetLifecycle | None, Query()] = None,
    origin: Annotated[str | None, Query()] = None,
    source_name: Annotated[str | None, Query(max_length=120)] = None,
    created_after: Annotated[str | None, Query(description="ISO-8601 com fuso")] = None,
    created_before: Annotated[str | None, Query(description="ISO-8601 com fuso")] = None,
    limit: Annotated[int, Query(ge=1, le=Page.MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DatasetPageOut:
    """Lista com filtro e paginação. O teto do `limit` é do servidor."""
    filtros = DatasetFilter(
        competition=competition,
        lifecycle=lifecycle,
        origin=origin,
        source_name=source_name,
        created_after=parse_instant(created_after) if created_after else None,
        created_before=parse_instant(created_before) if created_before else None,
    )
    itens, total = await contêiner.listing.execute(
        filters=filtros, page=Page(limit=limit, offset=offset)
    )
    return DatasetPageOut(
        items=[DatasetSummaryOut.of(i) for i in itens],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{dataset_id}", response_model=DatasetOut)
async def get_dataset(
    dataset_id: str, contêiner: ContainerDep, _: ActorDep
) -> DatasetOut:
    return DatasetOut.of(await contêiner.get.execute(_id(dataset_id)))


@router.get("/{dataset_id}/files", response_model=list[FileOut])
async def list_files(
    dataset_id: str, contêiner: ContainerDep, _: ActorDep
) -> list[FileOut]:
    dataset = await contêiner.get.execute(_id(dataset_id))
    return DatasetOut.of(dataset).files


@router.post(
    "/{dataset_id}/files",
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    dataset_id: str,
    request: Request,
    contêiner: ContainerDep,
    ator: ActorDep,
    resposta: Response,
    x_filename: Annotated[str, Header(alias="X-Filename", max_length=512)],
    file_format: Annotated[str, Query(alias="format", description="PARQUET | CSV | JSONL")],
) -> UploadOut:
    """Recebe UM arquivo, em stream, com o corpo cru.

    O NOME VEM NO CABEÇALHO E É SANITIZADO ANTES DE TOCAR QUALQUER CAMINHO —
    `../../etc/passwd`, nome com byte nulo e nome de 4 KB são entradas
    plausíveis num endpoint aberto a operador. O nome limpo é metadado; quem
    decide onde os bytes moram é o hash do conteúdo.

    O FORMATO É DECLARADO e conferido depois contra os bytes. A extensão do
    nome não é consultada em momento nenhum: renomear um arquivo é gratuito.
    """
    resultado = await contêiner.attach.execute(
        actor=ator,
        dataset_id=_id(dataset_id),
        filename=x_filename,
        file_format=resolve_declared_format(file_format),
        stream=request.stream(),
        correlation_id=request.headers.get(_CORRELACAO),
    )
    atual = await contêiner.get.execute(_id(dataset_id))
    saida = next(
        f for f in DatasetOut.of(atual).files if f.id == str(resultado.file.id)
    )
    # 200 E NÃO 201 NO REENVIO: nada foi criado, e dizer que foi levaria um
    # cliente a contar como novo o arquivo que ele já tinha mandado.
    resposta.status_code = (
        status.HTTP_200_OK if resultado.was_duplicate else status.HTTP_201_CREATED
    )
    return UploadOut(
        file=saida,
        was_duplicate=resultado.was_duplicate,
        bytes_written=resultado.bytes_written,
        dataset_lifecycle=atual.lifecycle.value,
    )


@router.post("/{dataset_id}/validate", response_model=ValidationOut)
async def validate_dataset(
    dataset_id: str,
    contêiner: ContainerDep,
    ator: ActorDep,
    request: Request,
    corpo: ValidateIn | None = None,
) -> ValidationOut:
    """Roda a validação estrutural e devolve o relatório.

    SÍNCRONA NESTA V1 — ver `ValidateDataset`. A resposta já traz o id do
    relatório, então trocar a execução por um worker depois é passar a
    responder 202 com o mesmo id, sem mudar a forma de nada.
    """
    relatorio = await contêiner.validate.execute(
        actor=ator,
        dataset_id=_id(dataset_id),
        contract=corpo.contract.to_domain() if corpo and corpo.contract else None,
        correlation_id=request.headers.get(_CORRELACAO),
    )
    return ValidationOut.of(relatorio)


@router.get("/{dataset_id}/validation", response_model=ValidationOut)
async def get_validation(
    dataset_id: str,
    contêiner: ContainerDep,
    _: ActorDep,
    report_id: Annotated[str | None, Query()] = None,
) -> ValidationOut:
    return ValidationOut.of(
        await contêiner.validation.execute(_id(dataset_id), report_id=report_id)
    )


@router.get("/{dataset_id}/manifest", response_model=ManifestOut)
async def get_manifest(
    dataset_id: str, contêiner: ContainerDep, _: ActorDep
) -> ManifestOut:
    """O manifesto congelado: qual entrada exata foi validada."""
    return ManifestOut.of(await contêiner.manifest.execute(_id(dataset_id)))


@router.post("/{dataset_id}/stage", response_model=DatasetOut)
async def stage_dataset(
    dataset_id: str,
    corpo: StageIn,
    contêiner: ContainerDep,
    ator: ActorDep,
    request: Request,
) -> DatasetOut:
    """Promove para `STAGED`.

    `STAGED` significa: bruto recebido, preservado e estruturalmente apto a
    ENTRAR em resolução de identidade e fusão. NÃO significa apto a alimentar
    inteligência — e a resposta diz isso num campo próprio
    (`intelligence_ready: false`) para que nenhum consumidor precise inferir.
    """
    dataset = await contêiner.stage.execute(
        actor=ator,
        dataset_id=_id(dataset_id),
        reason=corpo.reason,
        correlation_id=request.headers.get(_CORRELACAO),
    )
    return DatasetOut.of(dataset)


def _id(bruto: str) -> DatasetId:
    """Traduz o id da URL, com erro de validação em vez de 500."""
    try:
        return DatasetId.parse(bruto)
    except ValueError as erro:
        raise ValidationError(f"{bruto!r} não é um identificador de dataset") from erro
