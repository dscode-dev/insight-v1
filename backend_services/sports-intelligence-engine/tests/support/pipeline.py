"""O pipeline inteiro, montado com adapters de verdade dos dois lados.

POR QUE O BENCHMARK NÃO MEDE A FUNÇÃO PURA DO RESOLVER (§7). Medir
`TeamResolver.resolve` num laço diria quanto custa comparar strings, que é a
parte que já sabemos ser barata e que não é onde um pipeline de ingestão
morre. Ele morre na ida ao banco, na serialização das decisões e no `INSERT`
de um milhão de linhas de evidência.

Então o que este arquivo monta é o CAMINHO OPERACIONAL COMPLETO:

    bytes no object store
      → dataset registrado, validado e STAGED     (PR-02, de verdade)
      → mapeamento de fonte ativo
      → leitura em lotes
      → normalização
      → carga em massa de candidatos              (PostgreSQL real)
      → resolução
      → persistência de decisões, evidências e alternativas
      → fusão

O mesmo objeto serve ao benchmark e à integração multi-fonte, e é deliberado:
duas montagens divergiriam, e a divergência apareceria como «o benchmark mede
um sistema, o teste prova outro».
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any, final

from apps.resolution_composition import (
    ResolutionContainer,
    build_resolution_container,
    read_batches,
    resolved_match_map,
    to_resolved_records,
)
from sports_intelligence.adapters.event_bus import CollectingEventPublisher
from sports_intelligence.adapters.postgres.audit import PostgresAuditLog
from sports_intelligence.adapters.postgres.database import Database, PostgresUnitOfWork
from sports_intelligence.adapters.postgres.dataset_registry import (
    PostgresDatasetFileRepository,
    PostgresDatasetManifestRepository,
    PostgresDatasetRepository,
    PostgresDatasetValidationRepository,
)
from sports_intelligence.application.use_cases.datasets import (
    AttachDatasetFile,
    RegisterDataset,
    StageDataset,
    ValidateDataset,
)
from sports_intelligence.application.use_cases.fusion import FusionOutput
from sports_intelligence.application.use_cases.resolution import ResolutionOutput
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.formats import DatasetFormat
from sports_intelligence.domain.datasets.models import Dataset
from sports_intelligence.domain.datasets.source import DatasetSource
from sports_intelligence.domain.fusion.models import ResolvedSourceRecord
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.identity import DatasetId, ProviderId
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import Instant, instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.domain.sources.mapping import (
    SourceFieldMapping,
    SourceMappingDefinition,
)
from sports_intelligence.domain.sources.records_kind import RecordKind
from sports_intelligence.ingestion.historical.raw_archive import RawDatasetArchive
from sports_intelligence.ingestion.validation.structural import (
    StructuralValidator,
    ValidationLimits,
)
from sports_intelligence.ports.clock import FrozenClock

AGORA: Instant = instant(datetime(2026, 8, 13, 12, 0, tzinfo=UTC))
V1 = DatasetVersion(major=1, minor=0)

#: O operador que encena o intake. HUMANO porque o intake histórico é humano:
#: alguém baixou um arquivo e afirmou de onde ele veio (PR-02).
OPERADOR: Actor = Actor(id="darlan", kind=ActorKind.HUMAN_OPERATOR)

#: Quem executa resolução e fusão nos benchmarks. `ServiceActor` com
#: identidade explícita (§29): `system`, `root` e `admin` são recusados pelo
#: próprio `Actor`, e é a recusa que impede uma trilha de auditoria em que
#: todo mundo se chama a mesma coisa.
SERVICO: Actor = Actor.service("historical-benchmark-runner")


async def _stream(dados: bytes, bloco: int = 1 << 20) -> AsyncIterator[bytes]:
    for i in range(0, len(dados), bloco):
        yield dados[i : i + bloco]


@final
class Pipeline:
    """Intake, resolução e fusão sobre PostgreSQL e object store reais."""

    def __init__(
        self,
        database: Database,
        object_store: Any,
        *,
        batch_size: int = 1_000,
        candidate_limit: int = 60_000,
        max_file_size_bytes: int = 256 * 1024 * 1024,
        max_rows_per_file: int = 2_000_000,
    ) -> None:
        self.database = database
        self.clock = FrozenClock(AGORA)
        self.store = object_store
        self.archive = RawDatasetArchive(object_store)
        self.datasets = PostgresDatasetRepository(database)
        self.files = PostgresDatasetFileRepository(database)
        self.validations = PostgresDatasetValidationRepository(database)
        self.manifests = PostgresDatasetManifestRepository(database)
        self.audit = PostgresAuditLog(database)
        self.publisher = CollectingEventPublisher()
        self.batch_size = batch_size

        self._register = RegisterDataset(
            datasets=self.datasets,
            clock=self.clock,
            audit=self.audit,
            publisher=self.publisher,
        )
        self._attach = AttachDatasetFile(
            datasets=self.datasets,
            files=self.files,
            archive=self.archive,
            clock=self.clock,
            audit=self.audit,
            publisher=self.publisher,
            max_file_size_bytes=max_file_size_bytes,
        )
        self._validate = ValidateDataset(
            datasets=self.datasets,
            files=self.files,
            validations=self.validations,
            manifests=self.manifests,
            validator=StructuralValidator(
                archive=self.archive,
                clock=self.clock,
                limits=ValidationLimits(
                    max_file_size_bytes=max_file_size_bytes,
                    max_rows_per_file=max_rows_per_file,
                    max_issues=100,
                ),
            ),
            clock=self.clock,
            audit=self.audit,
            publisher=self.publisher,
            uow=PostgresUnitOfWork(database),
        )
        self._stage = StageDataset(
            datasets=self.datasets,
            validations=self.validations,
            clock=self.clock,
            audit=self.audit,
            publisher=self.publisher,
        )

        contêiner = build_resolution_container(
            database=database,
            archive=self.archive,
            datasets=self.datasets,
            clock=self.clock,
            audit=self.audit,
            publisher=self.publisher,
            batch_size=batch_size,
        )
        # O TETO DE CONFRONTOS É PARÂMETRO DO CENÁRIO, não do produto. Ele
        # limita quantos pares (temporada, mandante, visitante) uma carga de
        # lote pede ao banco; com quinze temporadas no registro, o padrão de
        # cinco mil truncaria a lista e partidas deixariam de resolver por
        # falta de candidato — o que mediria o corte, não a resolução.
        self.resolution: ResolutionContainer = dataclasses.replace(
            contêiner,
            run_resolution=dataclasses.replace(
                contêiner.run_resolution, candidate_limit=candidate_limit
            ),
        )

    # ------------------------------------------------------------ intake --

    async def stage(
        self,
        *,
        name: str,
        content: bytes,
        provider: ProviderId,
        filename: str = "fonte.csv",
        source_type: SourceType = SourceType.OPEN_DATA,
        license_class: LicenseClass = LicenseClass.ATTRIBUTION_REQUIRED,
        competitions: frozenset[CompetitionCode] | None = None,
    ) -> Dataset:
        """Registra, anexa, valida e promove para STAGED. O caminho do PR-02.

        NÃO ATALHA NENHUMA ETAPA. Inserir a linha do dataset direto no banco
        seria mais rápido e produziria um `STAGED` que nunca teve manifesto —
        e a resolução recusa dataset sem validação registrada, justamente
        porque a impressão do manifesto é o que fecha a linhagem (ADR-0019).
        """
        dataset, _ = await self._register.execute(
            actor=OPERADOR,
            name=name,
            version=V1,
            source=DatasetSource(
                source_name=str(provider),
                source_type=source_type,
                license_class=license_class,
                retrieved_at=instant(datetime(2026, 8, 1, tzinfo=UTC)),
                provider_id=provider,
            ),
            declared_competitions=competitions or frozenset({CompetitionCode.PREMIER_LEAGUE}),
            declared_seasons=("2021-2022",),
        )
        await self._attach.execute(
            actor=OPERADOR,
            dataset_id=dataset.id,
            filename=filename,
            file_format=DatasetFormat.CSV,
            stream=_stream(content),
        )
        relatorio = await self._validate.execute(actor=OPERADOR, dataset_id=dataset.id)
        if relatorio.has_blocking_issues:
            raise AssertionError(f"o cenário produziu um arquivo inválido: {relatorio.issues[:3]}")
        return await self._stage.execute(
            actor=OPERADOR, dataset_id=dataset.id, reason="cenário de teste"
        )

    async def map_source(
        self,
        dataset: Dataset,
        *,
        provider: ProviderId,
        fields: Sequence[SourceFieldMapping],
        conventions: dict[str, str] | None = None,
        record_kind: RecordKind = RecordKind.MATCH_RECORD,
    ) -> None:
        await self.resolution.register_mapping.execute(
            actor=OPERADOR,
            dataset_id=dataset.id,
            definition=SourceMappingDefinition.draft(
                record_kind=record_kind,
                dataset_id=dataset.id,
                dataset_version=dataset.version,
                provider_id=provider,
                version=1,
                fields=tuple(fields),
                at=self.clock.now(),
                created_by=OPERADOR.id,
                conventions=conventions or {},
            ),
        )

    # -------------------------------------------------- resolução e fusão --

    async def resolve(self, dataset_id: DatasetId, *, actor: Actor = SERVICO) -> ResolutionOutput:
        dataset = await self.datasets.by_id(dataset_id)
        assert dataset is not None
        mapeamento = await self.resolution.source_mappings.active_for(dataset_id)
        assert mapeamento is not None
        lotes = read_batches(
            dataset,
            archive=self.archive,
            reader=self.resolution.reader,
            mapping=mapeamento,
            manifest_fingerprint=await self._impressao(dataset),
        )
        return await self.resolution.run_resolution.execute(
            actor=actor, dataset_id=dataset_id, batches=lotes
        )

    async def resolved_records(self, run_ids: Sequence[str]) -> tuple[ResolvedSourceRecord, ...]:
        """Os registros que a fusão vai ver — só os que a resolução resolveu."""
        resolvidos = await resolved_match_map(self.resolution.decisions, run_ids)
        saida: list[ResolvedSourceRecord] = []
        for run_id in run_ids:
            execucao = await self.resolution.get_resolution_run.execute(run_id)
            dataset = await self.datasets.by_id(execucao.dataset_id)
            assert dataset is not None
            mapeamento = await self.resolution.source_mappings.active_for(dataset.id)
            assert mapeamento is not None
            lotes = read_batches(
                dataset,
                archive=self.archive,
                reader=self.resolution.reader,
                mapping=mapeamento,
                manifest_fingerprint=execucao.manifest_fingerprint,
            )
            async for registro in to_resolved_records(
                lotes,
                resolved=resolvidos,
                provider_source_type=dataset.source.source_type,
                license_class=dataset.source.license_class,
            ):
                saida.append(registro)
        return tuple(saida)

    async def fuse(
        self,
        run_ids: Sequence[str],
        *,
        actor: Actor = SERVICO,
        records: Sequence[ResolvedSourceRecord] | None = None,
    ) -> FusionOutput:
        return await self.resolution.run_fusion.execute(
            actor=actor,
            resolution_run_ids=list(run_ids),
            records=list(records)
            if records is not None
            else list(await self.resolved_records(run_ids)),
        )

    async def _impressao(self, dataset: Dataset) -> Any:
        import hashlib

        from sports_intelligence.domain.datasets.content import ContentHash

        return ContentHash(
            hashlib.sha256(
                f"{dataset.id}|{dataset.version}|{dataset.latest_validation_id}".encode()
            ).hexdigest()
        )
