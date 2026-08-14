"""As rotas de resolução e fusão. Control Plane, nunca no Query API.

POR QUE NÃO NO QUERY API (§70). Estas operações MUDAM o sistema: criam
decisões de identidade, mapeamentos e saídas de fusão. Um pico de leitura no
plano de consulta não pode competir por recurso com uma execução de resolução
sobre cem mil registros — e uma decisão de identidade não deve ser alcançável
pelo endereço que atende usuário final.

O ATOR VEM DE QUEM AUTENTICOU, como em todo o Control Plane. E aqui ele tem
peso extra: resolver um item da fila de revisão produz uma decisão com método
`MANUAL_REVIEW`, e o domínio recusa a combinação de método manual com ator de
serviço. A trilha registra quem decidiu, não por onde a decisão passou.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field

from apps.control_api.deps import ActorDep, ContainerDep
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.review import ReviewFilter, ReviewStatus
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import (
    DatasetId,
    EntityId,
    ProviderId,
)
from sports_intelligence.domain.sources.mapping import (
    SourceFieldMapping,
    SourceMappingDefinition,
    ValueTransform,
)
from sports_intelligence.domain.sources.semantics import SemanticRole

router = APIRouter(prefix="/v1", tags=["resolution"])

_CORRELACAO = "X-Correlation-Id"


# ------------------------------------------------------------- schemas ----


class FieldMappingIn(BaseModel):
    """Uma coluna e o papel que ela carrega. INERTE — nada aqui é executado."""

    column: str = Field(max_length=128)
    role: SemanticRole
    transform: ValueTransform = ValueTransform.TRIM
    date_format: str | None = None
    timezone: str | None = None


class SourceMappingIn(BaseModel):
    provider_id: str = Field(description="Quem publica os ids deste arquivo")
    fields: list[FieldMappingIn] = Field(min_length=1, max_length=128)
    version: int = Field(default=1, ge=1)
    conventions: dict[str, str] = Field(default_factory=dict)
    description: str | None = Field(default=None, max_length=1000)


class SourceMappingOut(BaseModel):
    id: str
    dataset_id: str
    provider_id: str
    version: int
    status: str
    fields: list[dict[str, Any]]
    conventions: dict[str, str]
    created_at: str
    created_by: str


class RunResolutionIn(BaseModel):
    """Nenhum parâmetro de política aqui, e é deliberado.

    Afrouxar um limiar precisa ser uma POLÍTICA nova com versão, não um campo
    de requisição — senão duas execuções sob a mesma versão significariam
    coisas diferentes, e a comparação entre elas deixaria de valer.
    """

    reason: str | None = Field(default=None, max_length=500)


class ResolutionRunOut(BaseModel):
    id: str
    dataset_id: str
    status: str
    resolver_version: str
    normalizer_version: str
    policy_version: str
    manifest_fingerprint: str
    total: int
    resolved: int
    unresolved: int
    ambiguous: int
    review_required: int
    rejected: int
    automatic_rate: float | None
    started_at: str
    completed_at: str | None
    duration_seconds: float | None
    #: DITO EM TODA RESPOSTA. A saída de uma resolução não é conhecimento
    #: histórico ativo, e nenhum consumidor deveria precisar inferir isso.
    historical_active: bool = False


class DecisionOut(BaseModel):
    id: str
    subject_type: str
    source_raw: str
    source_normalized: str
    status: str
    method: str
    confidence: float
    canonical_entity_id: str | None
    #: `dataset:arquivo:linha`. É o que permite ao operador sair de uma
    #: decisão e chegar à LINHA que a produziu — sem isso, «esta decisão veio
    #: do dataset X» é onde a investigação para. `None` na decisão manual,
    #: que herda a referência do item de fila.
    record_ref: str | None
    evidence: list[str]
    alternatives: list[dict[str, Any]]
    reason: str | None


class ReviewItemOut(BaseModel):
    id: str
    run_id: str
    subject_type: str
    source_raw: str
    record_ref: str
    reason_status: str
    status: str
    candidates: list[dict[str, Any]]
    created_at: str
    assigned_to: str | None


class ResolveReviewIn(BaseModel):
    """A escolha humana. `chosen_entity_id` ausente = rejeitar todos.

    O MOTIVO É OBRIGATÓRIO nos dois casos. Rejeitar sem motivo produz um item
    fechado que ninguém entende seis meses depois — e a próxima execução o
    recolocaria na fila.
    """

    chosen_entity_id: str | None = None
    reason: str = Field(min_length=3, max_length=1000)


class RunFusionIn(BaseModel):
    resolution_run_ids: list[str] = Field(min_length=1, max_length=20)


class FusionRunOut(BaseModel):
    id: str
    status: str
    policy_version: str
    input_resolution_runs: list[str]
    groups: int
    multi_source_groups: int
    fields_selected: int
    conflicts: int
    unresolved_conflicts: int
    output_fingerprint: str | None
    started_at: str
    completed_at: str | None
    historical_active: bool = False


class ConflictOut(BaseModel):
    canonical_match_id: str
    field_name: str
    values: str


# -------------------------------------------------------------- rotas ----


@router.post(
    "/datasets/{dataset_id}/source-mapping",
    response_model=SourceMappingOut,
    status_code=status.HTTP_201_CREATED,
)
async def register_source_mapping(
    dataset_id: str,
    corpo: SourceMappingIn,
    contêiner: ContainerDep,
    ator: ActorDep,
    request: Request,
) -> SourceMappingOut:
    """Declara qual coluna carrega qual papel semântico.

    ISTO NÃO RESOLVE NADA. `home` vira `HOME_TEAM_NAME`, que é uma afirmação
    sobre o ARQUIVO — o operador pode fazê-la olhando o cabeçalho. Dizer que
    `home` carrega um `TeamId` seria uma afirmação sobre o mundo, e ela exige
    resolução com evidência e possibilidade de falhar.
    """
    identificador = _dataset_id(dataset_id)
    dataset = await contêiner.get.execute(identificador)
    definicao = SourceMappingDefinition.draft(
        dataset_id=identificador,
        dataset_version=dataset.version,
        provider_id=ProviderId(corpo.provider_id),
        version=corpo.version,
        fields=tuple(
            SourceFieldMapping(
                column=f.column,
                role=f.role,
                transform=f.transform,
                date_format=f.date_format,
                timezone=f.timezone,
            )
            for f in corpo.fields
        ),
        at=contêiner.clock.now(),
        created_by=ator.id,
        conventions=corpo.conventions,
        description=corpo.description,
    )
    gravado = await contêiner.resolution.register_mapping.execute(
        actor=ator,
        dataset_id=identificador,
        definition=definicao,
        correlation_id=request.headers.get(_CORRELACAO),
    )
    return _mapping_out(gravado)


@router.get("/datasets/{dataset_id}/source-mapping", response_model=SourceMappingOut)
async def get_source_mapping(
    dataset_id: str, contêiner: ContainerDep, _: ActorDep
) -> SourceMappingOut:
    ativo = await contêiner.resolution.source_mappings.active_for(_dataset_id(dataset_id))
    if ativo is None:
        from sports_intelligence.domain.shared.errors import NotFoundError

        raise NotFoundError(f"dataset {dataset_id} sem mapeamento de fonte ativo")
    return _mapping_out(ativo)


@router.post(
    "/datasets/{dataset_id}/resolution-runs",
    response_model=ResolutionRunOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_resolution_run(
    dataset_id: str,
    corpo: RunResolutionIn,
    contêiner: ContainerDep,
    ator: ActorDep,
    request: Request,
) -> ResolutionRunOut:
    """Executa a resolução. Síncrona nesta V1, como a validação do PR-02.

    O CONTRATO JÁ SUPORTA A TROCA POR WORKER: a execução tem id próprio e
    estado persistido, então passar a responder 202 com o mesmo id é trocar
    quem chama `execute` — não a forma de nada.
    """
    _ = corpo
    saida = await contêiner.run_resolution_for_dataset(
        actor=ator,
        dataset_id=_dataset_id(dataset_id),
        correlation_id=request.headers.get(_CORRELACAO),
    )
    return _run_out(saida.run)


@router.get(
    "/datasets/{dataset_id}/resolution-runs", response_model=list[ResolutionRunOut]
)
async def list_resolution_runs(
    dataset_id: str,
    contêiner: ContainerDep,
    _: ActorDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[ResolutionRunOut]:
    """As execuções de um dataset. PLURAL é o ponto: o mesmo dataset passa por
    várias, com versões diferentes de resolver, e todas coexistem."""
    execucoes = await contêiner.resolution.resolution_runs.for_dataset(
        _dataset_id(dataset_id), limit=limit
    )
    return [_run_out(e) for e in execucoes]


@router.get("/resolution-runs/{run_id}", response_model=ResolutionRunOut)
async def get_resolution_run(
    run_id: str, contêiner: ContainerDep, _: ActorDep
) -> ResolutionRunOut:
    return _run_out(await contêiner.resolution.get_resolution_run.execute(run_id))


@router.get("/resolution-runs/{run_id}/decisions", response_model=list[DecisionOut])
async def list_decisions(
    run_id: str,
    contêiner: ContainerDep,
    _: ActorDep,
    subject: Annotated[SubjectType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DecisionOut]:
    decisoes, _total = await contêiner.resolution.list_decisions.execute(
        run_id, subject=subject, limit=limit, offset=offset
    )
    return [
        DecisionOut(
            id=d.id,
            subject_type=d.subject_type.value,
            source_raw=d.source_value.raw,
            source_normalized=d.source_value.normalized,
            status=d.status.value,
            method=d.method.value,
            confidence=d.confidence.value,
            canonical_entity_id=str(d.canonical_entity_id)
            if d.canonical_entity_id
            else None,
            record_ref=d.record_ref,
            evidence=[str(e) for e in d.evidence],
            alternatives=[
                {
                    "entity_id": str(a.canonical_entity_id),
                    "evidence": a.evidence_summary,
                    "label": a.label,
                    "score": a.score,
                }
                for a in d.alternatives
            ],
            reason=d.reason,
        )
        for d in decisoes
    ]


@router.get("/resolution-review", response_model=list[ReviewItemOut])
async def list_review(
    contêiner: ContainerDep,
    _: ActorDep,
    item_status: Annotated[ReviewStatus | None, Query(alias="status")] = None,
    subject: Annotated[SubjectType | None, Query()] = None,
    run_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReviewItemOut]:
    """A fila de revisão. O default mostra os abertos — que é o que se olha."""
    itens, _total = await contêiner.resolution.list_review.execute(
        filters=ReviewFilter(
            status=item_status or ReviewStatus.OPEN, subject_type=subject, run_id=run_id
        ),
        limit=limit,
        offset=offset,
    )
    return [
        ReviewItemOut(
            id=i.id,
            run_id=i.run_id,
            subject_type=i.subject.subject_type.value,
            source_raw=i.subject.source_value.raw,
            record_ref=i.subject.record_ref,
            reason_status=i.reason_status.value,
            status=i.status.value,
            candidates=[
                {
                    "entity_id": str(c.canonical_entity_id),
                    "evidence": c.evidence_summary,
                    "label": c.label,
                    "score": c.score,
                }
                for c in i.candidates
            ],
            created_at=i.created_at.isoformat(),
            assigned_to=i.assigned_to.id if i.assigned_to else None,
        )
        for i in itens
    ]


@router.post("/resolution-review/{item_id}/resolve", response_model=DecisionOut)
async def resolve_review(
    item_id: str,
    corpo: ResolveReviewIn,
    contêiner: ContainerDep,
    ator: ActorDep,
    request: Request,
) -> DecisionOut:
    """Um humano escolhe um candidato.

    A DECISÃO QUE SAI DAQUI É EVIDÊNCIA (§31): método `MANUAL_REVIEW`, ator
    humano, motivo obrigatório. E ela grava o alias que faz a PRÓXIMA
    execução resolver sozinha — que é o ciclo que a fila existe para fechar.
    """
    if corpo.chosen_entity_id is None:
        raise ValidationError(
            "escolha ausente: use /reject para recusar todos os candidatos"
        )
    decisao = await contêiner.resolution.resolve_review.execute(
        actor=ator,
        item_id=item_id,
        chosen=EntityId.parse(corpo.chosen_entity_id),
        reason=corpo.reason,
        correlation_id=request.headers.get(_CORRELACAO),
    )
    return DecisionOut(
        id=decisao.id,
        subject_type=decisao.subject_type.value,
        source_raw=decisao.source_value.raw,
        source_normalized=decisao.source_value.normalized,
        status=decisao.status.value,
        method=decisao.method.value,
        confidence=decisao.confidence.value,
        canonical_entity_id=str(decisao.canonical_entity_id)
        if decisao.canonical_entity_id
        else None,
        record_ref=decisao.record_ref,
        evidence=[str(e) for e in decisao.evidence],
        alternatives=[],
        reason=decisao.reason,
    )


@router.post("/resolution-review/{item_id}/reject", response_model=DecisionOut)
async def reject_review(
    item_id: str,
    corpo: ResolveReviewIn,
    contêiner: ContainerDep,
    ator: ActorDep,
    request: Request,
) -> DecisionOut:
    """Nenhum candidato serve. TAMBÉM produz decisão.

    Sem ela, o item rejeitado seria indistinguível de um item que ninguém
    olhou — e a próxima execução o recolocaria na fila, indefinidamente.
    """
    decisao = await contêiner.resolution.resolve_review.execute(
        actor=ator,
        item_id=item_id,
        chosen=None,
        reason=corpo.reason,
        correlation_id=request.headers.get(_CORRELACAO),
    )
    return DecisionOut(
        id=decisao.id,
        subject_type=decisao.subject_type.value,
        source_raw=decisao.source_value.raw,
        source_normalized=decisao.source_value.normalized,
        status=decisao.status.value,
        method=decisao.method.value,
        confidence=decisao.confidence.value,
        canonical_entity_id=None,
        record_ref=decisao.record_ref,
        evidence=[str(e) for e in decisao.evidence],
        alternatives=[],
        reason=decisao.reason,
    )


@router.post(
    "/fusion-runs", response_model=FusionRunOut, status_code=status.HTTP_201_CREATED
)
async def start_fusion_run(
    corpo: RunFusionIn,
    contêiner: ContainerDep,
    ator: ActorDep,
    request: Request,
) -> FusionRunOut:
    """Funde as saídas de execuções de resolução declaradas.

    SÓ IDENTIDADE PROVADA ENTRA. Registros cuja partida ficou `AMBIGUOUS` não
    aparecem em grupo nenhum, e a diferença entre lidos e agrupados é
    reportada.
    """
    saida = await contêiner.run_fusion_for_runs(
        actor=ator,
        resolution_run_ids=corpo.resolution_run_ids,
        correlation_id=request.headers.get(_CORRELACAO),
    )
    return _fusion_out(saida.run)


@router.get("/fusion-runs/{run_id}", response_model=FusionRunOut)
async def get_fusion_run(
    run_id: str, contêiner: ContainerDep, _: ActorDep
) -> FusionRunOut:
    return _fusion_out(await contêiner.resolution.get_fusion_run.execute(run_id))


@router.get("/fusion-runs/{run_id}/conflicts", response_model=list[ConflictOut])
async def list_conflicts(
    run_id: str,
    contêiner: ContainerDep,
    _: ActorDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ConflictOut]:
    """Os conflitos não resolvidos. O que o operador de fato abre.

    UM CONFLITO PRESERVADO NÃO É FALHA. Ele é o resultado desejável quando a
    política não sabe decidir: escolher por desempate arbitrário produziria um
    número de aparência decidida que ninguém revisaria.
    """
    conflitos = await contêiner.resolution.list_conflicts.execute(run_id, limit=limit)
    return [
        ConflictOut(canonical_match_id=m, field_name=c, values=v) for m, c, v in conflitos
    ]


# ---------------------------------------------------------- tradução ----


def _dataset_id(bruto: str) -> DatasetId:
    try:
        return DatasetId.parse(bruto)
    except ValueError as erro:
        raise ValidationError(f"{bruto!r} não é um identificador de dataset") from erro


def _mapping_out(m: SourceMappingDefinition) -> SourceMappingOut:
    return SourceMappingOut(
        id=m.id,
        dataset_id=str(m.dataset_id),
        provider_id=str(m.provider_id),
        version=m.version,
        status=m.status.value,
        fields=[
            {"column": f.column, "role": f.role.value, "transform": f.transform.value}
            for f in m.fields
        ],
        conventions=dict(m.conventions),
        created_at=m.created_at.isoformat(),
        created_by=m.created_by,
    )


def _run_out(run: Any) -> ResolutionRunOut:
    return ResolutionRunOut(
        id=run.id,
        dataset_id=str(run.dataset_id),
        status=run.status.value,
        resolver_version=str(run.versions.resolver),
        normalizer_version=str(run.versions.normalizer),
        policy_version=str(run.versions.policy),
        manifest_fingerprint=run.manifest_fingerprint.value,
        total=run.counts.total,
        resolved=run.counts.resolved,
        unresolved=run.counts.unresolved,
        ambiguous=run.counts.ambiguous,
        review_required=run.counts.review_required,
        rejected=run.counts.rejected,
        automatic_rate=run.counts.automatic_rate,
        started_at=run.started_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        duration_seconds=run.duration_seconds,
    )


def _fusion_out(run: Any) -> FusionRunOut:
    return FusionRunOut(
        id=run.id,
        status=run.status.value,
        policy_version=str(run.policy_version),
        input_resolution_runs=list(run.input_resolution_run_ids),
        groups=run.counts.groups,
        multi_source_groups=run.counts.multi_source_groups,
        fields_selected=run.counts.fields_selected,
        conflicts=run.counts.conflicts,
        unresolved_conflicts=run.counts.unresolved_conflicts,
        output_fingerprint=run.output_fingerprint.value
        if run.output_fingerprint
        else None,
        started_at=run.started_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )

