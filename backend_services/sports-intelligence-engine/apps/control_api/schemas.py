"""Os DTOs da fronteira HTTP. Eles não são o domínio, e é o ponto.

POR QUE NÃO EXPOR `Dataset` DIRETO NO FastAPI. Funciona — dataclasses são
serializáveis — e amarra o contrato público à forma interna: renomear um campo
do agregado vira uma mudança quebrando clientes, e a pressão passa a ser não
renomear. O modelo de domínio deixa de evoluir por causa de quem o consome.

Com DTO, a tradução é um lugar explícito. Ela também é onde campos ficam DE
FORA de propósito:

    `object_key`     é a topologia do bucket. Publicá-la convida alguém a
                     construir uma URL a partir dela, e o arquivo bruto não
                     tem caminho de leitura pela API.
    `provenance`     completa, com os quatro carimbos, é ruído no JSON e
                     está inteira no manifesto para quem precisar.

O QUE ENTRA E NÃO DEVERIA SER ÓBVIO: `sha256` de cada arquivo. Ele é o que
permite ao operador conferir, do lado dele, que o que chegou foi o que ele
mandou — `sha256sum arquivo.csv` e comparar. Sem isso, "recebido" é uma
afirmação que ele tem de aceitar.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, Field, field_validator

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.manifest import DatasetManifest
from sports_intelligence.domain.datasets.models import Dataset, DatasetSummary
from sports_intelligence.domain.datasets.schema import DatasetSchemaContract, DetectedType
from sports_intelligence.domain.datasets.source import DatasetSource
from sports_intelligence.domain.datasets.validation import DatasetValidationReport
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import parse_instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

MAX_DECLARED_SEASONS: Final[int] = 100


class SourceIn(BaseModel):
    """A ficha de origem, como o cliente a envia."""

    source_name: str = Field(min_length=2, max_length=120)
    source_type: SourceType
    license_class: LicenseClass
    retrieved_at: str = Field(description="ISO-8601 COM fuso explícito")
    source_url: str | None = None
    publisher: str | None = None
    provider_id: str | None = None
    notes: str | None = Field(default=None, max_length=2000)

    def to_domain(self) -> DatasetSource:
        from sports_intelligence.domain.shared.identity import ProviderId

        return DatasetSource(
            source_name=self.source_name,
            source_type=self.source_type,
            license_class=self.license_class,
            # `parse_instant` RECUSA data sem fuso, e a recusa é o valor: um
            # `retrieved_at` sem fuso seria interpretado como UTC, e a coleta
            # de uma fonte brasileira cairia três horas fora — o suficiente
            # para mudar o dia, que costuma fazer parte da identidade.
            retrieved_at=parse_instant(self.retrieved_at),
            source_url=self.source_url,
            publisher=self.publisher,
            provider_id=ProviderId(self.provider_id) if self.provider_id else None,
            notes=self.notes,
        )


class CreateDatasetIn(BaseModel):
    name: str = Field(min_length=3, max_length=63)
    version: str = Field(default="v1.0", description="vMAJOR.MINOR")
    source: SourceIn
    declared_competitions: list[CompetitionCode] = Field(min_length=1)
    declared_seasons: list[str] = Field(default_factory=list, max_length=MAX_DECLARED_SEASONS)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("version")
    @classmethod
    def _versao_valida(cls, valor: str) -> str:
        DatasetVersion.parse(valor)
        return valor

    def parsed_version(self) -> DatasetVersion:
        return DatasetVersion.parse(self.version)


class SchemaContractIn(BaseModel):
    """O contrato de ingestão. Opcional, e nunca o schema canônico.

    Ele fala a língua da FONTE — `home`, `away`, `odds_h`. Nada aqui declara
    que `home` é um time; essa tradução é do PR-03.
    """

    required_columns: list[str] = Field(default_factory=list, max_length=512)
    expected_columns: list[str] = Field(default_factory=list, max_length=512)
    declared_types: dict[str, DetectedType] = Field(default_factory=dict)

    def to_domain(self) -> DatasetSchemaContract:
        return DatasetSchemaContract(
            required_columns=frozenset(self.required_columns),
            expected_columns=frozenset(self.expected_columns),
            declared_types=dict(self.declared_types),
        )


class ValidateIn(BaseModel):
    contract: SchemaContractIn | None = None


class StageIn(BaseModel):
    """Promover é decisão humana, e decisão humana tem motivo.

    `min_length=3` no motivo: um campo obrigatório que aceita `"x"` é um campo
    opcional com passo a mais.
    """

    reason: str = Field(min_length=3, max_length=500)


class FileOut(BaseModel):
    id: str
    filename: str
    format: str
    sha256: str
    size_bytes: int
    staging_state: str
    uploaded_at: str
    uploaded_by: str
    row_count: int | None = None
    column_count: int | None = None


class SourceOut(BaseModel):
    source_name: str
    source_type: str
    license_class: str
    retrieved_at: str
    source_url: str | None
    publisher: str | None
    provider_id: str | None
    needs_license_review: bool


class DatasetOut(BaseModel):
    id: str
    name: str
    version: str
    lifecycle: str
    description: str | None
    declared_competitions: list[str]
    declared_seasons: list[str]
    source: SourceOut
    files: list[FileOut]
    stored_file_count: int
    pending_file_count: int
    total_bytes: int
    created_at: str
    created_by: str
    latest_validation_id: str | None
    #: DITO EXPLICITAMENTE, em todo dataset, inclusive nos `STAGED`. Sem este
    #: campo, um consumidor futuro leria `lifecycle == "STAGED"` e concluiria
    #: que o dado está pronto para uso — que é a confusão que o ADR-0016
    #: existe para impedir.
    intelligence_ready: bool = False

    @classmethod
    def of(cls, dataset: Dataset) -> DatasetOut:
        return cls(
            id=str(dataset.id),
            name=dataset.name,
            version=str(dataset.version),
            lifecycle=dataset.lifecycle.value,
            description=dataset.description,
            declared_competitions=sorted(c.value for c in dataset.declared_competitions),
            declared_seasons=list(dataset.declared_seasons),
            source=SourceOut(
                source_name=dataset.source.source_name,
                source_type=dataset.source.source_type.value,
                license_class=dataset.source.license_class.value,
                retrieved_at=dataset.source.retrieved_at.isoformat(),
                source_url=dataset.source.source_url,
                publisher=dataset.source.publisher,
                provider_id=str(dataset.source.provider_id)
                if dataset.source.provider_id
                else None,
                needs_license_review=dataset.needs_license_review,
            ),
            files=[
                FileOut(
                    id=str(f.id),
                    filename=f.safe_filename,
                    format=f.format.value,
                    sha256=f.content_hash.value,
                    size_bytes=f.size_bytes,
                    staging_state=f.staging_state.value,
                    uploaded_at=f.uploaded_at.isoformat(),
                    uploaded_by=f.uploaded_by,
                    row_count=f.row_count,
                    column_count=f.column_count,
                )
                for f in dataset.files
            ],
            stored_file_count=len(dataset.stored_files),
            pending_file_count=len(dataset.pending_files),
            total_bytes=dataset.total_bytes,
            created_at=dataset.created_at.isoformat(),
            created_by=dataset.created_by,
            latest_validation_id=dataset.latest_validation_id,
        )


class DatasetSummaryOut(BaseModel):
    id: str
    name: str
    version: str
    lifecycle: str
    source_name: str
    source_type: str
    license_class: str
    declared_competitions: list[str]
    file_count: int
    total_bytes: int
    created_at: str | None

    @classmethod
    def of(cls, resumo: DatasetSummary) -> DatasetSummaryOut:
        return cls(
            id=str(resumo.id),
            name=resumo.name,
            version=str(resumo.version),
            lifecycle=resumo.lifecycle.value,
            source_name=resumo.source_name,
            source_type=resumo.source_type,
            license_class=resumo.license_class,
            declared_competitions=sorted(c.value for c in resumo.declared_competitions),
            file_count=resumo.file_count,
            total_bytes=resumo.total_bytes,
            created_at=resumo.created_at.isoformat() if resumo.created_at else None,
        )


class DatasetPageOut(BaseModel):
    items: list[DatasetSummaryOut]
    total: int
    limit: int
    offset: int


class UploadOut(BaseModel):
    file: FileOut
    #: `True` quando os bytes já estavam registrados. NÃO é erro: reenviar é
    #: operação normal, e dizer isso é melhor que devolver 409 para uma
    #: situação que convergiu.
    was_duplicate: bool
    bytes_written: int
    dataset_lifecycle: str


class IssueOut(BaseModel):
    code: str
    severity: str
    message: str
    file_id: str | None
    location: str | None
    occurrences: int


class ColumnOut(BaseModel):
    name: str
    detected_type: str
    nullable: bool | None
    null_count: int | None
    samples: list[str]


class SchemaObservationOut(BaseModel):
    file_id: str
    row_count: int
    column_count: int
    truncated_columns: bool
    columns: list[ColumnOut]


class ValidationOut(BaseModel):
    id: str
    dataset_id: str
    dataset_version: str
    status: str
    validator_version: str
    files_checked: int
    rows_observed: int
    issue_count: int
    #: Quantas issues foram GUARDADAS. Diferente de `issue_count` quando o
    #: teto foi atingido — e a diferença precisa ser visível, senão um
    #: relatório truncado em 200 afirmaria que houve 200.
    issues_returned: int
    truncated: bool
    can_stage: bool
    started_at: str
    generated_at: str
    execution_error: str | None
    issues: list[IssueOut]
    schema_observations: list[SchemaObservationOut]

    @classmethod
    def of(cls, r: DatasetValidationReport) -> ValidationOut:
        return cls(
            id=r.id,
            dataset_id=str(r.dataset_id),
            dataset_version=str(r.dataset_version),
            status=r.status.value,
            validator_version=str(r.validator_version),
            files_checked=r.files_checked,
            rows_observed=r.rows_observed,
            issue_count=r.issue_count,
            issues_returned=len(r.issues),
            truncated=r.truncated,
            can_stage=not r.has_blocking_issues,
            started_at=r.started_at.isoformat(),
            generated_at=r.generated_at.isoformat(),
            execution_error=r.execution_error,
            issues=[
                IssueOut(
                    code=i.code.value,
                    severity=str(i.severity),
                    message=i.message,
                    file_id=i.file_id,
                    location=i.location,
                    occurrences=i.occurrences,
                )
                for i in r.issues
            ],
            schema_observations=[
                SchemaObservationOut(
                    file_id=o.file_id,
                    row_count=o.row_count,
                    column_count=o.column_count,
                    truncated_columns=o.truncated_columns,
                    columns=[
                        ColumnOut(
                            name=c.name,
                            detected_type=c.detected_type.value,
                            nullable=c.nullable,
                            null_count=c.null_count,
                            samples=list(c.samples),
                        )
                        for c in o.columns
                    ],
                )
                for o in r.schema_observations
            ],
        )


class ManifestOut(BaseModel):
    fingerprint: str
    body: dict[str, Any]
    created_at: str

    @classmethod
    def of(cls, m: DatasetManifest) -> ManifestOut:
        """O manifesto sai na forma CANÔNICA, mais a impressão.

        A canônica e não a persistida: é ela que foi hasheada, e é ela que o
        cliente pode reserializar para conferir a impressão por conta própria.
        Devolver uma forma diferente da que gerou o hash tornaria a
        verificação independente impossível.
        """
        return cls(
            fingerprint=m.fingerprint.value,
            body=m.as_canonical(),
            created_at=m.created_at.isoformat(),
        )
