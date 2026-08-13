"""Os casos de uso do registro de intake.

OITO CASOS DE USO E NENHUM `DatasetService`. Um serviço com oito métodos
parece organização e é acoplamento: quem precisa de `stage` recebe também
`upload`, `validate` e `list`, e o teste de qualquer um precisa construir as
dependências de todos. Aqui cada caso de uso declara exatamente o que usa, e
a lista de campos de cada um é a documentação real de suas dependências.

ELES COORDENAM E NÃO REVALIDAM. Nenhum reconfere o que o domínio já garante —
uma segunda checagem de `REGISTERED → STAGED` aqui criaria uma regra paralela
que diverge da primeira no dia em que uma das duas mudar. O que eles fazem é
o que o domínio não pode: falar com o relógio, com os repositórios, com o
arquivo bruto e com o barramento, na ordem certa.

A ORDEM CERTA É O ASSUNTO DE `AttachDatasetFile`, e ela é a razão de este
módulo existir. Ver o ADR-0017.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import final

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.files import DatasetFile, FileStagingState
from sports_intelligence.domain.datasets.formats import DatasetFormat
from sports_intelligence.domain.datasets.lifecycle import (
    DatasetLifecycle,
    assert_can_stage,
)
from sports_intelligence.domain.datasets.manifest import DatasetManifest
from sports_intelligence.domain.datasets.models import (
    Dataset,
    DatasetFilter,
    DatasetSummary,
    Page,
)
from sports_intelligence.domain.datasets.schema import DatasetSchemaContract
from sports_intelligence.domain.datasets.source import DatasetSource
from sports_intelligence.domain.datasets.validation import DatasetValidationReport
from sports_intelligence.domain.events.envelope import EventEnvelope
from sports_intelligence.domain.events.envelope_types import (
    DATASET_FILE_STORED,
    DATASET_REGISTERED,
    DATASET_STAGED,
    DATASET_VALIDATION_COMPLETED,
    DOMAIN_SCHEMA,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.audit import AuditAction, AuditEntry
from sports_intelligence.domain.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.domain.shared.temporal import Instant, instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.ingestion.historical.upload import StreamingReceiver
from sports_intelligence.ingestion.validation.structural import StructuralValidator
from sports_intelligence.ports.audit import AuditPort
from sports_intelligence.ports.clock import ClockPort
from sports_intelligence.ports.event_bus import EventPublisherPort
from sports_intelligence.ports.raw_dataset_archive import RawDatasetArchivePort
from sports_intelligence.ports.repositories.dataset_registry import (
    DatasetFileRepositoryPort,
    DatasetManifestRepositoryPort,
    DatasetRepositoryPort,
    DatasetValidationRepositoryPort,
)
from sports_intelligence.ports.unit_of_work import UnitOfWorkPort


@final
@dataclass(frozen=True, slots=True)
class AttachmentResult:
    """O que o anexo de um arquivo produziu.

    `was_duplicate` NÃO É ERRO. Reenviar os mesmos bytes é operação normal —
    retry de rede, operador em dúvida, script rodado duas vezes — e devolver
    conflito faria o cliente tratar convergência como falha. O campo diz o
    que aconteceu para que a interface possa dizê-lo também.
    """

    file: DatasetFile
    was_duplicate: bool
    bytes_written: int


@final
@dataclass(frozen=True, slots=True)
class RegisterDataset:
    """Cria o dataset em `REGISTERED`. Idempotente por (nome, versão)."""

    datasets: DatasetRepositoryPort
    clock: ClockPort
    audit: AuditPort
    publisher: EventPublisherPort

    async def execute(
        self,
        *,
        actor: Actor,
        name: str,
        version: DatasetVersion,
        source: DatasetSource,
        declared_competitions: frozenset[CompetitionCode],
        declared_seasons: tuple[str, ...] = (),
        description: str | None = None,
        correlation_id: str | None = None,
    ) -> tuple[Dataset, bool]:
        """Devolve (dataset, foi_criado_agora).

        O SEGUNDO ELEMENTO É O QUE TORNA A IDEMPOTÊNCIA VISÍVEL. Sem ele,
        quem chama não distingue "criei" de "já existia", e a API responderia
        201 para os dois — dizendo que criou algo que não criou.

        QUANDO JÁ EXISTE COM OUTRA FONTE, RECUSA. Sobrescrever silenciosamente
        a ficha de origem de um dataset registrado por outra pessoa apagaria
        a licença sob a qual os bytes foram aceitos — e a licença é o que
        decide o que se pode fazer com eles.
        """
        agora = self.clock.now()
        # A ficha de origem é convertida em procedência JÁ AQUI, antes de
        # qualquer escrita, porque é esta conversão que confere o carimbo de
        # coleta contra o relógio — uma data de coleta no futuro é fuso
        # declarado errado, e é muito mais barato recusá-la antes de o
        # dataset existir do que explicá-la depois.
        source.to_provenance(ingested_at=agora)

        proposto = Dataset.register(
            name=name,
            version=version,
            source=source,
            declared_competitions=declared_competitions,
            declared_seasons=declared_seasons,
            created_at=agora,
            created_by=actor.id,
            description=description,
        )
        persistido, criado = await self.datasets.insert_if_absent(proposto)

        if not criado and persistido.source != source:
            raise ConflictError(
                f"o dataset {name}@{version} já existe com outra fonte "
                f"({persistido.source.source_name!r}, licença "
                f"{persistido.source.license_class}). Registre outra versão em vez de "
                "reescrever a ficha de origem — ela é o que autoriza o uso dos bytes.",
                context={"dataset_id": str(persistido.id)},
            )
        if not criado:
            return persistido, False

        await self.audit.record(
            AuditEntry.of(
                AuditAction.DATASET_REGISTERED,
                actor=actor,
                at=agora,
                dataset_id=persistido.id,
                correlation_id=correlation_id,
                name=persistido.name,
                version=str(persistido.version),
                license=persistido.source.license_class.value,
            )
        )
        await self.publisher.publish(
            EventEnvelope.create(
                event_type=DATASET_REGISTERED,
                schema_version=DOMAIN_SCHEMA,
                occurred_at=agora,
                produced_at=agora,
                payload={
                    "dataset_id": str(persistido.id),
                    "name": persistido.name,
                    "version": str(persistido.version),
                    "source_type": persistido.source.source_type.value,
                    "license_class": persistido.source.license_class.value,
                },
            )
        )
        return persistido, True


@final
@dataclass(frozen=True, slots=True)
class AttachDatasetFile:
    """Recebe um arquivo: intenção, gravação, confirmação. Nesta ordem.

    A ORDEM É A ÚNICA COISA QUE IMPORTA AQUI, e ela existe porque o object
    store e o PostgreSQL não commitam juntos:

        1. lê o stream, calcula SHA-256 e tamanho     (memória constante)
        2. INSERE a linha em PENDING                  (transacional)
        3. grava os bytes no arquivo bruto            (não transacional)
        4. CONFIRMA a linha para STORED               (transacional)

    Falhar entre 2 e 3 deixa uma linha `PENDING` sem bytes: o dataset não sai
    de `UPLOADING`, a validação recusa começar, e o reenvio dos mesmos bytes
    retoma do passo 3. Falhar entre 3 e 4 deixa bytes com a linha ainda
    `PENDING`: o reenvio encontra o objeto já lá, não regrava, e confirma.

    A ORDEM INVERSA — gravar antes de registrar — pareceria mais simples e
    produziria bytes órfãos que nenhuma consulta enxerga, porque não há linha
    apontando para eles. O órfão que este desenho produz é o outro: uma linha
    visível, marcada, e que a reconciliação encontra.
    """

    datasets: DatasetRepositoryPort
    files: DatasetFileRepositoryPort
    archive: RawDatasetArchivePort
    clock: ClockPort
    audit: AuditPort
    publisher: EventPublisherPort
    max_file_size_bytes: int
    spool_threshold_bytes: int = 8 * 1024 * 1024

    async def execute(
        self,
        *,
        actor: Actor,
        dataset_id: DatasetId,
        filename: str,
        file_format: DatasetFormat,
        stream: AsyncIterator[bytes],
        correlation_id: str | None = None,
    ) -> AttachmentResult:
        dataset = await self.datasets.by_id(dataset_id)
        if dataset is None:
            raise NotFoundError(f"dataset {dataset_id} não registrado")
        dataset.assert_accepts_files()

        async with StreamingReceiver(
            max_bytes=self.max_file_size_bytes,
            spool_threshold=self.spool_threshold_bytes,
        ) as receptor:
            recebido = await receptor.consume(stream)

            if recebido.is_empty:
                # RECUSADO NA ENTRADA e não como issue de validação. Um
                # arquivo de zero bytes não é evidência de nada, e gravá-lo
                # gastaria uma chave do arquivo bruto para guardar nada.
                raise ValidationError(
                    f"{filename!r} tem zero bytes — não há o que arquivar",
                    context={"filename": filename},
                )
            if recebido.compression is not None:
                # Recusado ANTES de gravar: um arquivo compactado que entra no
                # arquivo bruto é uma bomba de descompressão esperando a
                # validação abri-la.
                raise ValidationError(
                    f"{filename!r} é {recebido.compression} e a V1 não aceita arquivo "
                    "compactado. Descompacte na origem e reenvie.",
                    context={"compression": recebido.compression},
                )

            existente = await self.files.by_content(dataset_id, recebido.content_hash.value)
            agora = self.clock.now()

            registro = existente or DatasetFile.intent(
                dataset_id=dataset.id,
                version=dataset.version,
                original_filename=filename,
                file_format=file_format,
                content_hash=recebido.content_hash,
                size_bytes=recebido.size_bytes,
                uploaded_at=agora,
                uploaded_by=actor.id,
                provenance=dataset.source.to_provenance(ingested_at=agora),
            )
            if existente is not None and existente.staging_state.counts_as_present:
                # Os mesmos bytes, já gravados e confirmados. Nada a fazer, e
                # dizer isso é melhor que refazer.
                return AttachmentResult(file=existente, was_duplicate=True, bytes_written=0)
            if existente is not None and existente.format is not file_format:
                raise ConflictError(
                    f"estes bytes já foram anunciados como {existente.format} e agora "
                    f"como {file_format} — o conteúdo é o mesmo, a declaração não",
                    context={"sha256": recebido.content_hash.value},
                )

            # ---- fase 1: a intenção, transacional
            if existente is None:
                registro = await self.files.register_intent(registro)
            if dataset.lifecycle is not DatasetLifecycle.UPLOADING:
                # Abre a janela. Se outro upload concorrente já a abriu, esta
                # transição perde a corrida e devolve `False` — que é o
                # resultado certo, não um erro: a janela está aberta, que era
                # o objetivo.
                await self.datasets.transition(
                    dataset.id,
                    expected=dataset.lifecycle,
                    target=DatasetLifecycle.UPLOADING,
                    at=agora,
                    reason=f"upload de {registro.safe_filename}",
                    actor_id=actor.id,
                )

            # ---- fase 2: os bytes, não transacional
            try:
                gravado = await self.archive.store(registro, receptor.chunks())
            except Exception:
                # A LINHA FICA, MARCADA. Apagá-la esconderia que alguém tentou
                # enviar este arquivo, e é justamente esse rastro que permite
                # descobrir depois por que o dataset está incompleto.
                await self.files.mark_failed(str(registro.id), reason="falha ao gravar")
                await self.audit.record(
                    AuditEntry.of(
                        AuditAction.DATASET_FILE_UPLOAD_FAILED,
                        actor=actor,
                        at=self.clock.now(),
                        dataset_id=dataset.id,
                        file_id=str(registro.id),
                        correlation_id=correlation_id,
                        sha256=registro.content_hash.value,
                    )
                )
                raise

        # ---- fase 3: a confirmação, transacional
        await self.files.confirm_stored(str(registro.id))
        confirmado = registro.confirm_stored()

        await self._fechar_janela_de_upload(dataset.id, actor=actor)
        await self.audit.record(
            AuditEntry.of(
                AuditAction.DATASET_FILE_STORED,
                actor=actor,
                at=self.clock.now(),
                dataset_id=dataset.id,
                file_id=str(confirmado.id),
                correlation_id=correlation_id,
                sha256=confirmado.content_hash.value,
                size_bytes=confirmado.size_bytes,
                already_present=gravado.already_present,
            )
        )
        await self.publisher.publish(
            EventEnvelope.create(
                event_type=DATASET_FILE_STORED,
                schema_version=DOMAIN_SCHEMA,
                occurred_at=confirmado.uploaded_at,
                produced_at=self.clock.now(),
                payload={
                    "dataset_id": str(dataset.id),
                    "file_id": str(confirmado.id),
                    "sha256": confirmado.content_hash.value,
                    "size_bytes": confirmado.size_bytes,
                    "format": confirmado.format.value,
                },
            )
        )
        return AttachmentResult(
            file=confirmado,
            was_duplicate=existente is not None,
            bytes_written=0 if gravado.already_present else confirmado.size_bytes,
        )

    async def _fechar_janela_de_upload(self, dataset_id: DatasetId, *, actor: Actor) -> None:
        """Sobe para `UPLOADED` quando não sobrou nenhuma promessa em aberto.

        A CONDIÇÃO É "NENHUM PENDING", não "acabou de gravar um". Com vários
        uploads em paralelo, cada um que termina precisa perguntar pelo
        conjunto — senão o primeiro a terminar fecharia a janela enquanto os
        outros ainda estão gravando.
        """
        atual = await self.datasets.by_id(dataset_id)
        if atual is None or atual.has_pending_uploads:
            return
        if atual.lifecycle is not DatasetLifecycle.UPLOADING:
            return
        await self.datasets.transition(
            dataset_id,
            expected=DatasetLifecycle.UPLOADING,
            target=DatasetLifecycle.UPLOADED,
            at=self.clock.now(),
            reason="todos os arquivos anunciados foram gravados e conferidos",
            actor_id=actor.id,
        )


@final
@dataclass(frozen=True, slots=True)
class ValidateDataset:
    """Roda a validação estrutural e persiste o relatório.

    SÍNCRONA NESTA V1, E DECLARADA COMO ESCOLHA. Um worker com fila resolveria
    o arquivo grande e traria enfileiramento, retry, visibilidade de execução
    e um processo a mais para operar — antes de existir um arquivo grande o
    bastante para justificá-lo. O contrato aqui já suporta a mudança: o estado
    `VALIDATING` é persistido, o relatório tem id próprio, e trocar a execução
    por um worker é trocar quem chama `execute`, não a forma de nada.

    A TRANSIÇÃO PARA `VALIDATING` É O LOCK. Ela é condicional ao estado
    anterior no banco, então duas validações simultâneas disputam um `UPDATE`
    e uma perde — em Python as duas leriam `UPLOADED` e as duas seguiriam.
    """

    datasets: DatasetRepositoryPort
    files: DatasetFileRepositoryPort
    validations: DatasetValidationRepositoryPort
    manifests: DatasetManifestRepositoryPort
    validator: StructuralValidator
    clock: ClockPort
    audit: AuditPort
    publisher: EventPublisherPort
    uow: UnitOfWorkPort

    async def execute(
        self,
        *,
        actor: Actor,
        dataset_id: DatasetId,
        contract: DatasetSchemaContract | None = None,
        correlation_id: str | None = None,
    ) -> DatasetValidationReport:
        dataset = await self.datasets.by_id(dataset_id)
        if dataset is None:
            raise NotFoundError(f"dataset {dataset_id} não registrado")
        dataset.assert_ready_for_validation()

        origem = dataset.lifecycle
        tomou = await self.datasets.transition(
            dataset_id,
            expected=origem,
            target=DatasetLifecycle.VALIDATING,
            at=self.clock.now(),
            reason="validação estrutural iniciada",
            actor_id=actor.id,
        )
        if not tomou:
            raise ConflictError(
                "outra validação deste dataset já está em andamento",
                context={"dataset_id": str(dataset_id)},
            )
        await self.audit.record(
            AuditEntry.of(
                AuditAction.DATASET_VALIDATION_STARTED,
                actor=actor,
                at=self.clock.now(),
                dataset_id=dataset_id,
                correlation_id=correlation_id,
            )
        )

        try:
            relatorio = await self.validator.validate(dataset, contract=contract)
        except Exception as erro:
            # FALHA NOSSA, E ELA TEM ESTADO PRÓPRIO. `FAILED` e não `INVALID`:
            # o arquivo pode estar perfeito, e mandar o operador procurar
            # defeito nele seria mandá-lo para o lugar errado.
            await self.datasets.transition(
                dataset_id,
                expected=DatasetLifecycle.VALIDATING,
                target=DatasetLifecycle.FAILED,
                at=self.clock.now(),
                reason=f"a validação não chegou ao fim: {type(erro).__name__}",
                actor_id=actor.id,
            )
            raise

        destino = (
            DatasetLifecycle.INVALID
            if relatorio.has_blocking_issues
            else DatasetLifecycle.VALIDATED
        )
        async with self.uow:
            # O RELATÓRIO E O ESTADO COMMITAM JUNTOS. Separados, um dataset
            # pode ficar `VALIDATED` sem relatório — e a próxima leitura
            # procuraria o motivo do estado e não encontraria nada.
            await self.validations.save_report(relatorio)
            for observacao in relatorio.schema_observations:
                await self.files.record_inspection(
                    observacao.file_id,
                    row_count=observacao.row_count,
                    column_count=observacao.column_count,
                )
            await self.datasets.transition(
                dataset_id,
                expected=DatasetLifecycle.VALIDATING,
                target=destino,
                at=self.clock.now(),
                reason=f"validação concluída: {relatorio.status}",
                actor_id=actor.id,
            )

        if destino is DatasetLifecycle.VALIDATED:
            await self._emitir_manifesto(dataset_id, relatorio)

        await self.audit.record(
            AuditEntry.of(
                AuditAction.DATASET_VALIDATION_COMPLETED,
                actor=actor,
                at=self.clock.now(),
                dataset_id=dataset_id,
                correlation_id=correlation_id,
                validation_id=relatorio.id,
                status=relatorio.status.value,
                issue_count=relatorio.issue_count,
            )
        )
        await self.publisher.publish(
            EventEnvelope.create(
                event_type=DATASET_VALIDATION_COMPLETED,
                schema_version=DOMAIN_SCHEMA,
                occurred_at=relatorio.generated_at,
                produced_at=self.clock.now(),
                payload={
                    "dataset_id": str(dataset_id),
                    "validation_id": relatorio.id,
                    "status": relatorio.status.value,
                    "files_checked": relatorio.files_checked,
                    "rows_observed": relatorio.rows_observed,
                    "issue_count": relatorio.issue_count,
                    "blocking": relatorio.has_blocking_issues,
                },
            )
        )
        return relatorio

    async def _emitir_manifesto(
        self, dataset_id: DatasetId, relatorio: DatasetValidationReport
    ) -> None:
        """Congela o conjunto validado.

        RELÊ O DATASET DO BANCO em vez de reusar o que estava em memória: a
        inspeção acabou de gravar contagem de linhas e de colunas em cada
        arquivo, e um manifesto montado sobre a versão anterior sairia sem
        elas — descrevendo um conjunto que ninguém mediu.
        """
        atual = await self.datasets.by_id(dataset_id)
        if atual is None:
            return
        manifesto = DatasetManifest.build(
            dataset=atual, report=relatorio, created_at=self.clock.now()
        )
        await self.manifests.save(manifesto)


@final
@dataclass(frozen=True, slots=True)
class StageDataset:
    """Promove para `STAGED` — o limite mais importante deste PR.

    `STAGED` significa: o bruto foi recebido, preservado e é estruturalmente
    apto a ENTRAR em resolução de identidade e fusão. NÃO significa que o dado
    pode alimentar o índice histórico; entre um e outro estão o PR-03 inteiro
    e a barreira do ADR-0007.

    DUAS GUARDAS, E NENHUMA BASTA SOZINHA: o estado precisa ser `VALIDATED`, e
    o relatório precisa estar sem impeditivos. Um dataset pode estar
    `VALIDATED` por um relatório antigo, e um relatório limpo não diz nada
    sobre um dataset que nem subiu.
    """

    datasets: DatasetRepositoryPort
    validations: DatasetValidationRepositoryPort
    clock: ClockPort
    audit: AuditPort
    publisher: EventPublisherPort

    async def execute(
        self,
        *,
        actor: Actor,
        dataset_id: DatasetId,
        reason: str,
        correlation_id: str | None = None,
    ) -> Dataset:
        if not reason.strip():
            raise ValidationError(
                "promover um dataset é decisão humana e exige motivo — "
                "sem ele a trilha registra que alguém promoveu e não por quê"
            )
        dataset = await self.datasets.by_id(dataset_id)
        if dataset is None:
            raise NotFoundError(f"dataset {dataset_id} não registrado")

        relatorio = await self.validations.latest_for(dataset_id)
        if relatorio is None:
            raise ConflictError(
                "não há relatório de validação para este dataset — "
                "STAGED afirmaria que ele é estruturalmente apto sem ninguém ter lido"
            )
        if relatorio.dataset_version != dataset.version:
            raise ConflictError(
                f"o relatório mais recente é da versão {relatorio.dataset_version} e o "
                f"dataset está em {dataset.version}: revalide antes de promover"
            )
        assert_can_stage(
            dataset.lifecycle, has_blocking_issues=relatorio.has_blocking_issues
        )

        agora = self.clock.now()
        tomou = await self.datasets.transition(
            dataset_id,
            expected=DatasetLifecycle.VALIDATED,
            target=DatasetLifecycle.STAGED,
            at=agora,
            reason=reason,
            actor_id=actor.id,
        )
        if not tomou:
            raise ConflictError(
                "o estado do dataset mudou durante a promoção — releia e tente de novo"
            )

        await self.audit.record(
            AuditEntry.of(
                AuditAction.DATASET_STAGED,
                actor=actor,
                at=agora,
                dataset_id=dataset_id,
                correlation_id=correlation_id,
                reason=reason,
                validation_id=relatorio.id,
                files=len(dataset.stored_files),
            )
        )
        await self.publisher.publish(
            EventEnvelope.create(
                event_type=DATASET_STAGED,
                schema_version=DOMAIN_SCHEMA,
                occurred_at=agora,
                produced_at=agora,
                payload={
                    "dataset_id": str(dataset_id),
                    "version": str(dataset.version),
                    "validation_id": relatorio.id,
                    "files": len(dataset.stored_files),
                    # DITO EXPLICITAMENTE NO EVENTO, para que nenhum consumidor
                    # futuro precise inferir: staged não é ativo no histórico.
                    "intelligence_ready": False,
                },
            )
        )
        return dataset.with_lifecycle(
            DatasetLifecycle.STAGED, at=agora, reason=reason
        )


@final
@dataclass(frozen=True, slots=True)
class GetDataset:
    datasets: DatasetRepositoryPort

    async def execute(self, dataset_id: DatasetId) -> Dataset:
        dataset = await self.datasets.by_id(dataset_id)
        if dataset is None:
            raise NotFoundError(f"dataset {dataset_id} não registrado")
        return dataset


@final
@dataclass(frozen=True, slots=True)
class ListDatasets:
    datasets: DatasetRepositoryPort

    async def execute(
        self, *, filters: DatasetFilter, page: Page
    ) -> tuple[Sequence[DatasetSummary], int]:
        return await self.datasets.list(filters=filters, page=page)


@final
@dataclass(frozen=True, slots=True)
class GetDatasetValidation:
    """O relatório mais recente, ou um específico por id."""

    datasets: DatasetRepositoryPort
    validations: DatasetValidationRepositoryPort

    async def execute(
        self, dataset_id: DatasetId, *, report_id: str | None = None
    ) -> DatasetValidationReport:
        if await self.datasets.by_id(dataset_id, with_files=False) is None:
            raise NotFoundError(f"dataset {dataset_id} não registrado")
        relatorio = (
            await self.validations.by_id(report_id)
            if report_id
            else await self.validations.latest_for(dataset_id)
        )
        if relatorio is None:
            raise NotFoundError(
                f"não há relatório de validação para o dataset {dataset_id}"
            )
        if relatorio.dataset_id != dataset_id:
            raise NotFoundError(f"o relatório {report_id} não é deste dataset")
        return relatorio


@final
@dataclass(frozen=True, slots=True)
class GetDatasetManifest:
    """O manifesto congelado — a prova de qual entrada foi validada."""

    manifests: DatasetManifestRepositoryPort

    async def execute(self, dataset_id: DatasetId) -> DatasetManifest:
        manifesto = await self.manifests.latest_for(dataset_id)
        if manifesto is None:
            raise NotFoundError(
                f"não há manifesto para o dataset {dataset_id} — "
                "ele é emitido quando a validação passa sem impeditivos"
            )
        return manifesto


@final
@dataclass(frozen=True, slots=True)
class ReconcilePendingUploads:
    """Fecha a janela do ADR-0017: intenções sem bytes, e vice-versa.

    ELA NÃO APAGA NADA. Para cada `PENDING` antigo, pergunta ao arquivo bruto
    se os bytes chegaram: se chegaram, confirma — era uma falha entre as fases
    2 e 3, e a informação estava certa nos dois lados; se não chegaram, marca
    `FAILED` — o upload morreu no meio, e o operador precisa reenviar.

    Bytes órfãos (objeto sem linha) NÃO são tocados por esta rotina. Eles são
    inofensivos — nenhuma consulta os alcança —, e apagar objeto do arquivo
    bruto é a única operação que este PR não oferece por caminho de código.
    A limpeza deles é administrativa, deliberada, e feita por quem responde
    por ela.
    """

    files: DatasetFileRepositoryPort
    archive: RawDatasetArchivePort
    clock: ClockPort

    async def execute(self, *, older_than_seconds: int = 3600) -> tuple[int, int]:
        """Devolve (confirmados, marcados como falha)."""
        limite: Instant = instant(self.clock.now() - timedelta(seconds=older_than_seconds))
        confirmados = 0
        falhados = 0
        for arquivo in await self.files.pending_older_than(limite):
            if arquivo.staging_state is not FileStagingState.PENDING:
                continue
            if await self.archive.verify(arquivo):
                await self.files.confirm_stored(str(arquivo.id))
                confirmados += 1
            else:
                await self.files.mark_failed(
                    str(arquivo.id), reason="upload não concluído dentro da janela"
                )
                falhados += 1
        return confirmados, falhados
