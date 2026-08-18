"""As rotas do corpus histórico. Control Plane, e por três razões.

MUDAM O SISTEMA. Criar dataset, compor e publicar produzem conteúdo imutável
que tudo o que vem depois vai ler. Um endereço exposto a tráfego de leitura não
é lugar para uma operação que grava dez mil linhas de pertinência.

SÃO PRIVILEGIADAS. Publicar é decidir que ESTE conteúdo passa a ser o corpus, e
a trilha registra quem decidiu — `is_decision` exige motivo (§76 do PR-04.2).

SÃO CARAS. A composição de dez mil partidas concorreria por conexão com o
plano de consulta, e o sintoma seria latência de leitura sem causa aparente.

TODA RESPOSTA DIZ `vector_active: false` (§4, §72). Um corpus `READY` é um
corpus que pode ser LIDO; ele não tem feature, não tem `MatchStateVector` e não
está indexado em lugar nenhum. Deixar o consumidor inferir isso é como a
próxima fase começa a ser usada antes de existir.

O CAMINHO É O MESMO DA CLI (§78). As duas entram pelos casos de uso de
`application/use_cases/corpus.py`; uma orquestração própria por porta faria
uma delas ganhar uma verificação que a outra não tem.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field

from apps.control_api.deps import ActorDep, ContainerDep
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.corpus.scope import CorpusScope, ScopeEntry
from sports_intelligence.domain.corpus.versions import (
    DatasetVersionStatus,
    VersionInputs,
)
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.shared.errors import NotFoundError, ValidationError
from sports_intelligence.domain.shared.identity import CompetitionId, SeasonId
from sports_intelligence.domain.shared.versioning import DatasetVersion

router = APIRouter(prefix="/v1/historical-corpus", tags=["corpus"])

_CORRELACAO = "X-Correlation-Id"


# ------------------------------------------------------------- schemas ----


class CreateDatasetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class DatasetOut(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: str
    created_by: str


class ScopeEntryIn(BaseModel):
    """Uma (competição, temporada) do escopo — POR ID, e não por nome (§65).

    Casar por nome de time e data aproximada é como um fato da temporada A
    entra na temporada B, e o histórico passa a somar duas edições diferentes
    na mesma linha.
    """

    competition: CompetitionCode
    season_label: str = Field(min_length=1, max_length=32)
    competition_id: str
    season_id: str


class BuildVersionIn(BaseModel):
    """A composição de uma versão. Nenhum parâmetro de POLÍTICA aqui.

    Afrouxar um critério é uma política nova COM VERSÃO, e não um campo de
    requisição — senão duas versões sob a mesma política significariam coisas
    diferentes, e comparar corpus deixaria de valer (a mesma regra do PR-03).
    """

    version: str = Field(pattern=r"^\d+\.\d+$")
    usage: UsageScope
    scope: list[ScopeEntryIn] = Field(min_length=1, max_length=200)
    build_run_ids: list[str] = Field(min_length=1, max_length=200)
    quality_run_ids: list[str] = Field(default_factory=list, max_length=200)
    quality_run_id: str | None = Field(
        default=None,
        description="A execução de qualidade de onde vêm os vereditos agregados",
    )
    build_output_fingerprints: list[str] = Field(default_factory=list, max_length=200)
    fusion_run_ids: list[str] = Field(default_factory=list, max_length=200)
    resolution_run_ids: list[str] = Field(default_factory=list, max_length=200)


class PublishVersionIn(BaseModel):
    """O gate. O MOTIVO É OBRIGATÓRIO.

    Publicar é uma decisão administrativa (`AuditAction.is_decision`), e uma
    decisão sem motivo é a linha de trilha que ninguém entende seis meses
    depois — que é exatamente quando ela é lida.
    """

    reason: str = Field(min_length=3, max_length=500)
    supersede_previous: bool = True


class VersionOut(BaseModel):
    id: str
    dataset_id: str
    version: str
    usage: str
    status: str
    match_count: int
    corpus_fingerprint: str | None
    manifest_id: str | None
    created_at: str
    completed_at: str | None
    failure_reason: str | None
    superseded_by: str | None
    #: DITO EM TODA RESPOSTA (§72). Pronto para ser LIDO ≠ espaço vetorial.
    vector_active: bool = False


class BuildVersionOut(BaseModel):
    version: VersionOut
    members_written: int
    objects_written: int
    materialized: bool
    corpus_fingerprint: str
    #: O manifesto MONTADO e ainda não publicado — para que o operador possa
    #: conferir contagens e cobertura ANTES de decidir publicar (§67).
    manifest: dict[str, Any]


class ManifestOut(BaseModel):
    schema_version: str
    document: dict[str, Any]
    vector_active: bool = False


# ---------------------------------------------------------------- rotas ----


@router.post("/datasets", response_model=DatasetOut, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    corpo: CreateDatasetIn,
    contêiner: ContainerDep,
    ator: ActorDep,
    request: Request,
) -> DatasetOut:
    """Declara a identidade lógica do corpus. Não cria conteúdo nenhum."""
    criado = await contêiner.corpus.create_dataset.execute(
        actor=ator,
        name=corpo.name,
        description=corpo.description,
        correlation_id=request.headers.get(_CORRELACAO),
    )
    return DatasetOut(
        id=criado.id,
        name=criado.name,
        description=criado.description,
        created_at=criado.created_at.isoformat(),
        created_by=criado.created_by.id,
    )


@router.get("/datasets", response_model=list[DatasetOut])
async def list_datasets(
    contêiner: ContainerDep,
    _: ActorDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DatasetOut]:
    encontrados, _total = await contêiner.corpus.datasets.list_datasets(limit=limit, offset=offset)
    return [
        DatasetOut(
            id=d.id,
            name=d.name,
            description=d.description,
            created_at=d.created_at.isoformat(),
            created_by=d.created_by.id,
        )
        for d in encontrados
    ]


@router.post(
    "/datasets/{dataset_id}/versions",
    response_model=BuildVersionOut,
    status_code=status.HTTP_201_CREATED,
)
async def build_version(
    dataset_id: str,
    corpo: BuildVersionIn,
    contêiner: ContainerDep,
    ator: ActorDep,
    request: Request,
) -> BuildVersionOut:
    """Compõe a versão. Ela termina em `VALIDATING` e NÃO publicada (§12).

    Síncrona nesta V1, como a validação do PR-02 e a resolução do PR-03. O
    contrato já suporta a troca por worker: a versão tem id próprio e estado
    persistido, então passar a responder 202 com o mesmo id é trocar quem
    executa, e não o que o cliente vê.
    """
    saida = await contêiner.corpus.build_version.execute(
        actor=ator,
        dataset_id=dataset_id,
        version=_versao(corpo.version),
        scope=_escopo(corpo),
        inputs=_entradas(corpo),
        quality_run_id=corpo.quality_run_id,
        correlation_id=request.headers.get(_CORRELACAO),
    )
    return BuildVersionOut(
        version=_version_out(saida.version),
        members_written=saida.members_written,
        objects_written=saida.objects_written,
        materialized=saida.materialized,
        corpus_fingerprint=saida.manifest.corpus_fingerprint.value,
        manifest=saida.manifest.as_canonical(),
    )


@router.post("/versions/{version_id}/publish", response_model=VersionOut)
async def publish_version(
    version_id: str,
    corpo: PublishVersionIn,
    contêiner: ContainerDep,
    ator: ActorDep,
    request: Request,
) -> VersionOut:
    """O GATE. Confere contagem, impressão e manifesto, e congela (§67, §68).

    O MANIFESTO É REMONTADO PELA COMPOSIÇÃO e não vem do cliente. Aceitá-lo no
    corpo permitiria publicar uma descrição que não corresponde ao conteúdo —
    e a conferência do §67 estaria conferindo o que o cliente afirmou.
    """
    publicada = await contêiner.corpus.publish_version.execute(
        actor=ator,
        version_id=version_id,
        reason=corpo.reason,
        supersede_previous=corpo.supersede_previous,
        correlation_id=request.headers.get(_CORRELACAO),
    )
    return _version_out(publicada)


@router.get("/datasets/{dataset_id}/versions", response_model=list[VersionOut])
async def list_versions(
    dataset_id: str,
    contêiner: ContainerDep,
    _: ActorDep,
    version_status: Annotated[DatasetVersionStatus | None, Query(alias="status")] = None,
    usage: Annotated[UsageScope | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[VersionOut]:
    encontradas, _total = await contêiner.corpus.datasets.list_versions(
        dataset_id, status=version_status, usage=usage, limit=limit, offset=offset
    )
    return [_version_out(v) for v in encontradas]


@router.get("/versions/{version_id}", response_model=VersionOut)
async def get_version(version_id: str, contêiner: ContainerDep, _: ActorDep) -> VersionOut:
    versao = await contêiner.corpus.datasets.version_by_id(version_id)
    if versao is None:
        raise NotFoundError(f"versão de corpus {version_id} não encontrada")
    return _version_out(versao)


@router.get("/versions/{version_id}/manifest", response_model=ManifestOut)
async def get_manifest(version_id: str, contêiner: ContainerDep, _: ActorDep) -> ManifestOut:
    """O manifesto publicado — a descrição completa do que a versão contém."""
    manifesto = await contêiner.corpus.manifests.by_version(version_id)
    if manifesto is None:
        raise NotFoundError(f"versão {version_id} sem manifesto publicado")
    return ManifestOut(schema_version=manifesto.schema_version, document=manifesto.as_canonical())


@router.get("/datasets/{dataset_id}/latest", response_model=VersionOut)
async def latest_ready(
    dataset_id: str,
    contêiner: ContainerDep,
    _: ActorDep,
    usage: Annotated[UsageScope, Query()] = UsageScope.RESEARCH,
) -> VersionOut:
    """Qual é o corpus ATUAL deste escopo. `SUPERSEDED` não conta aqui.

    São duas perguntas e elas têm rotas diferentes: esta responde «qual é o
    corpus atual»; `/versions` responde «quais corpus existem», e ali o
    histórico importa (§79).
    """
    versao = await contêiner.corpus.datasets.latest_ready(dataset_id, usage=usage)
    if versao is None:
        raise NotFoundError(f"o dataset {dataset_id} não tem versão publicada em {usage.value}")
    return _version_out(versao)


# ---------------------------------------------------------------- apoio ----


def _versao(texto: str) -> DatasetVersion:
    maior, _, menor = texto.partition(".")
    return DatasetVersion(major=int(maior), minor=int(menor))


def _escopo(corpo: BuildVersionIn) -> CorpusScope:
    return CorpusScope.of(
        *(
            ScopeEntry(
                competition=e.competition,
                season_label=e.season_label,
                competition_id=CompetitionId(_uuid(e.competition_id)),
                season_id=SeasonId(_uuid(e.season_id)),
            )
            for e in corpo.scope
        ),
        usage=corpo.usage,
    )


def _entradas(corpo: BuildVersionIn) -> VersionInputs:
    return VersionInputs(
        build_run_ids=tuple(corpo.build_run_ids),
        quality_run_ids=tuple(corpo.quality_run_ids),
        build_output_fingerprints=tuple(ContentHash(f) for f in corpo.build_output_fingerprints),
        fusion_run_ids=tuple(corpo.fusion_run_ids),
        resolution_run_ids=tuple(corpo.resolution_run_ids),
    )


def _version_out(versao: Any) -> VersionOut:
    return VersionOut(
        id=versao.id,
        dataset_id=versao.dataset_id,
        version=str(versao.version),
        usage=versao.usage.value,
        status=versao.status.value,
        match_count=versao.match_count,
        corpus_fingerprint=(
            None if versao.corpus_fingerprint is None else versao.corpus_fingerprint.value
        ),
        manifest_id=versao.manifest_id,
        created_at=versao.created_at.isoformat(),
        completed_at=(None if versao.completed_at is None else versao.completed_at.isoformat()),
        failure_reason=versao.failure_reason,
        superseded_by=versao.superseded_by,
    )


def _uuid(texto: str) -> Any:
    import uuid

    try:
        return uuid.UUID(texto)
    except ValueError as erro:
        raise ValidationError(f"{texto!r} não é um identificador válido") from erro
