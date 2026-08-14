"""A raiz de composição: o ÚNICO lugar onde adapters encontram ports.

POR QUE UM ARQUIVO PRÓPRIO, e não dentro de `control_api/deps.py` como
começou. Porque a CLI precisa exatamente do mesmo grafo — os mesmos
repositórios, o mesmo arquivo bruto, o mesmo validador — e importá-lo de
dentro do pacote da API faria a CLI depender da API para existir. Pior: as
migrations, que não são de nenhum dos dois planos, não teriam onde morar sem
que alguém importasse `adapters` de dentro de um comando.

O TESTE DE ARQUITETURA COBRA ISSO. `apps/` inteiro é proibido de importar
`adapters`, com duas exceções declaradas: este arquivo e `_shared.py`. Um
terceiro nome nessa lista é sinal de que a composição vazou — e o sintoma
prático de vazamento é um processo que instancia o próprio pool, criando uma
conexão por requisição.

O QUE ELE NÃO FAZ: não decide política, não valida nada, não conhece HTTP.
Ele lê configuração e monta objetos.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import final

from apps.build_composition import (
    BuildContainer,
    build_build_container,
    candidate_batches,
    evidence_batches,
    rebuild_fusion_output,
)
from apps.resolution_composition import (
    ResolutionContainer,
    build_resolution_container,
    read_batches,
    resolved_match_map,
    to_resolved_records,
)
from sports_intelligence.adapters.event_bus import LoggingEventPublisher
from sports_intelligence.adapters.postgres import migrations
from sports_intelligence.adapters.postgres.audit import PostgresAuditLog
from sports_intelligence.adapters.postgres.database import Database, PostgresUnitOfWork
from sports_intelligence.adapters.postgres.dataset_registry import (
    PostgresDatasetFileRepository,
    PostgresDatasetManifestRepository,
    PostgresDatasetRepository,
    PostgresDatasetValidationRepository,
)
from sports_intelligence.adapters.s3.filesystem import FilesystemObjectStore
from sports_intelligence.adapters.s3.object_store import S3ObjectStore
from sports_intelligence.application.use_cases.canonical_build import BuildOutput
from sports_intelligence.application.use_cases.datasets import (
    AttachDatasetFile,
    GetDataset,
    GetDatasetManifest,
    GetDatasetValidation,
    ListDatasets,
    ReconcilePendingUploads,
    RegisterDataset,
    StageDataset,
    ValidateDataset,
)
from sports_intelligence.application.use_cases.fusion import FusionOutput
from sports_intelligence.application.use_cases.quality import QualityOutput
from sports_intelligence.application.use_cases.resolution import ResolutionOutput
from sports_intelligence.config.settings import (
    AppSettings,
    IntakeSettings,
    ObjectStoreBackend,
    ObjectStoreSettings,
    PostgresSettings,
    assert_object_store_is_durable,
)
from sports_intelligence.domain.build.policy import CanonicalBuildPolicy
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.fusion.models import ResolvedSourceRecord
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ConflictError
from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.ingestion.historical.raw_archive import RawDatasetArchive
from sports_intelligence.ingestion.validation.structural import (
    StructuralValidator,
    ValidationLimits,
)
from sports_intelligence.ports.clock import SystemClock
from sports_intelligence.ports.object_store import ObjectStorePort
from sports_intelligence.ports.raw_dataset_archive import RawDatasetArchivePort


@final
@dataclass(frozen=True, slots=True)
class Container:
    """Tudo que o Control Plane precisa, montado uma vez por processo.

    UM CONTÊINER E NÃO `Depends` POR PEÇA. Com `Depends` em cada repositório,
    a montagem fica espalhada por dez funções e o pool acaba sendo criado por
    requisição — que é o defeito clássico, e ele aparece como esgotamento de
    conexões sob carga, nunca como erro de configuração.
    """

    settings: AppSettings
    intake: IntakeSettings
    database: Database
    object_store: ObjectStorePort
    #: O repositório de datasets, exposto porque a BORDA do PR-04.2 relê as
    #: fontes de uma execução para remontar os candidatos fundidos — e ela
    #: precisa do dataset, não do caso de uso que o busca.
    datasets: PostgresDatasetRepository
    register: RegisterDataset
    attach: AttachDatasetFile
    validate: ValidateDataset
    stage: StageDataset
    get: GetDataset
    listing: ListDatasets
    validation: GetDatasetValidation
    manifest: GetDatasetManifest
    reconcile: ReconcilePendingUploads
    #: O grafo do PR-03, num campo próprio. As rotas dizem
    #: `contêiner.resolution.run_fusion` — explícito e verificável pelo
    #: checador de tipos, ao contrário de um `__getattr__` que delega e
    #: devolve `object`.
    resolution: ResolutionContainer
    #: O grafo do PR-04.2, no mesmo desenho: um campo próprio, verificável
    #: pelo checador de tipos. Ele NÃO tem rota nem comando ainda — a API e a
    #: CLI do PR-04 são a fase seguinte (§72, §73) — e existe para que os
    #: casos de uso sejam composicionalmente alcançáveis (§74).
    build: BuildContainer
    archive: RawDatasetArchivePort
    clock: SystemClock

    async def run_resolution_for_dataset(
        self, *, actor: Actor, dataset_id: DatasetId, correlation_id: str | None = None
    ) -> ResolutionOutput:
        """Lê o dataset e executa a resolução.

        A LEITURA MORA AQUI, na borda, e não dentro do caso de uso: ela
        envolve object store, arquivo temporário e formato. Com ela lá
        dentro, `RunIdentityResolution` precisaria conhecer o object store
        para poder resolver identidade — e deixaria de ser testável sem
        infraestrutura.
        """
        dataset = await self.get.execute(dataset_id)
        mapeamento = await self.resolution.source_mappings.active_for(dataset_id)
        if mapeamento is None:
            raise ConflictError(
                "o dataset não tem mapeamento de fonte ativo — sem ele não há como "
                "saber qual coluna carrega o quê"
            )
        impressao = ContentHash(
            hashlib.sha256(
                f"{dataset.id}|{dataset.version}|{dataset.latest_validation_id}".encode()
            ).hexdigest()
        )
        lotes = read_batches(
            dataset,
            archive=self.archive,
            reader=self.resolution.reader,
            mapping=mapeamento,
            manifest_fingerprint=impressao,
        )
        return await self.resolution.run_resolution.execute(
            actor=actor,
            dataset_id=dataset_id,
            batches=lotes,
            correlation_id=correlation_id,
        )

    async def run_fusion_for_runs(
        self,
        *,
        actor: Actor,
        resolution_run_ids: Sequence[str],
        correlation_id: str | None = None,
    ) -> FusionOutput:
        """Relê as fontes das execuções e funde o que resolveu.

        SÓ O QUE RESOLVEU. `resolved_match_map` traz as decisões `RESOLVED`;
        um registro cuja partida ficou `AMBIGUOUS` simplesmente não aparece,
        e a fusão nunca chega a vê-lo (ADR-0022).
        """
        resolvidos = await resolved_match_map(
            self.resolution.decisions, resolution_run_ids
        )
        registros: list[ResolvedSourceRecord] = []
        for run_id in resolution_run_ids:
            execucao = await self.resolution.get_resolution_run.execute(run_id)
            dataset = await self.get.execute(execucao.dataset_id)
            mapeamento = await self.resolution.source_mappings.active_for(dataset.id)
            if mapeamento is None:
                continue
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
                registros.append(registro)
        return await self.resolution.run_fusion.execute(
            actor=actor,
            resolution_run_ids=resolution_run_ids,
            records=registros,
            correlation_id=correlation_id,
        )

    async def run_quality_for_fusion(
        self,
        *,
        actor: Actor,
        fusion_run_ids: Sequence[str],
        resolution_run_ids: Sequence[str],
        correlation_id: str | None = None,
    ) -> QualityOutput:
        """Remonta a saída fundida e avalia a qualidade dela.

        A REMONTAGEM MORA NA BORDA, como toda leitura de fonte desta base. O
        caso de uso recebe lotes de evidência e nada mais — é o que o mantém
        testável sem object store.
        """
        grupos, candidatos = await rebuild_fusion_output(
            resolution=self.resolution,
            datasets=self.datasets,
            archive=self.archive,
            resolution_run_ids=resolution_run_ids,
        )
        return await self.build.run_quality.execute(
            actor=actor,
            fusion_run_ids=fusion_run_ids,
            batches=evidence_batches(
                resolution=self.resolution,
                groups=grupos,
                candidates=candidatos,
                resolution_run_ids=resolution_run_ids,
            ),
            correlation_id=correlation_id,
        )

    async def run_canonical_build_for_quality(
        self,
        *,
        actor: Actor,
        quality_run_id: str,
        resolution_run_ids: Sequence[str],
        policy: CanonicalBuildPolicy | None = None,
        correlation_id: str | None = None,
    ) -> BuildOutput:
        """Constrói os fatos canônicos autorizados por uma avaliação.

        A POLÍTICA É PARÂMETRO, e é o §18: a mesma avaliação sob a política de
        pesquisa e sob a comercial produz corpus diferentes, e os dois
        coexistem. Sem ela na assinatura, um dos dois seria inalcançável.
        """
        _, candidatos = await rebuild_fusion_output(
            resolution=self.resolution,
            datasets=self.datasets,
            archive=self.archive,
            resolution_run_ids=resolution_run_ids,
        )
        caso = (
            self.build.run_research_build
            if policy is None
            else self.build.build_for(policy)
        )
        return await caso.execute(
            actor=actor,
            quality_run_id=quality_run_id,
            batches=candidate_batches(candidates=candidatos),
            correlation_id=correlation_id,
        )


def build_container(settings: AppSettings | None = None) -> Container:
    """Constrói o grafo. Chamado no startup do processo, nunca por requisição."""
    app_settings = settings or AppSettings.from_env()
    intake = IntakeSettings.from_env()
    store_settings = ObjectStoreSettings.from_env()
    # A GUARDA DE DURABILIDADE ACONTECE NO BOOT: um arquivo bruto em pasta
    # local dentro de um contêiner some no próximo deploy, e o que sumiria é
    # a única camada que não se reconstrói (ADR-0004, ADR-0014).
    assert_object_store_is_durable(store_settings, app_settings.environment)

    database = Database(PostgresSettings.from_env())
    store: ObjectStorePort = (
        FilesystemObjectStore(store_settings.root_path or "./.raw-archive")
        if store_settings.backend is ObjectStoreBackend.FILESYSTEM
        else S3ObjectStore(store_settings)
    )
    archive = RawDatasetArchive(store)

    clock = SystemClock()
    publisher = LoggingEventPublisher()
    audit = PostgresAuditLog(database)
    datasets = PostgresDatasetRepository(database)
    files = PostgresDatasetFileRepository(database)
    validations = PostgresDatasetValidationRepository(database)
    manifests = PostgresDatasetManifestRepository(database)

    validator = StructuralValidator(
        archive=archive,
        clock=clock,
        limits=ValidationLimits(
            max_file_size_bytes=intake.max_file_size_bytes,
            max_rows_per_file=intake.max_rows_per_file,
            max_issues=intake.max_validation_issues,
        ),
    )

    resolucao = build_resolution_container(
        database=database,
        archive=archive,
        datasets=datasets,
        clock=clock,
        audit=audit,
        publisher=publisher,
        batch_size=intake.resolution_batch_size,
    )

    return Container(
        settings=app_settings,
        intake=intake,
        database=database,
        object_store=store,
        datasets=datasets,
        register=RegisterDataset(
            datasets=datasets, clock=clock, audit=audit, publisher=publisher
        ),
        attach=AttachDatasetFile(
            datasets=datasets,
            files=files,
            archive=archive,
            clock=clock,
            audit=audit,
            publisher=publisher,
            max_file_size_bytes=intake.max_file_size_bytes,
            spool_threshold_bytes=intake.upload_spool_threshold_bytes,
        ),
        validate=ValidateDataset(
            datasets=datasets,
            files=files,
            validations=validations,
            manifests=manifests,
            validator=validator,
            clock=clock,
            audit=audit,
            publisher=publisher,
            uow=PostgresUnitOfWork(database),
        ),
        stage=StageDataset(
            datasets=datasets,
            validations=validations,
            clock=clock,
            audit=audit,
            publisher=publisher,
        ),
        get=GetDataset(datasets=datasets),
        listing=ListDatasets(datasets=datasets),
        validation=GetDatasetValidation(datasets=datasets, validations=validations),
        manifest=GetDatasetManifest(manifests=manifests),
        reconcile=ReconcilePendingUploads(files=files, archive=archive, clock=clock),
        resolution=resolucao,
        build=build_build_container(
            database=database, resolution=resolucao, clock=clock, audit=audit
        ),
        archive=archive,
        clock=clock,
    )


def build_database() -> Database:
    """Só o banco, para quem não precisa do resto.

    As migrations são o caso: elas rodam antes de existir schema para os
    repositórios lerem, e montar o grafo inteiro para aplicá-las exigiria um
    object store configurado que elas não usam.
    """
    return Database(PostgresSettings.from_env())


async def apply_migrations(database: Database) -> tuple[str, ...]:
    """Aplica o que falta. Devolve as versões aplicadas agora."""
    return await migrations.migrate(database)


async def migration_status(database: Database) -> tuple[migrations.MigrationStatus, ...]:
    """O que está aplicado, o que falta, e o que mudou depois de aplicado."""
    return await migrations.status(database)


def migrations_dir() -> Path:
    return migrations.MIGRATIONS_DIR
