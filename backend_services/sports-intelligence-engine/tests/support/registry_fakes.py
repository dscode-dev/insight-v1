"""Duplos em memória do registro — com as MESMAS restrições dos reais.

A ARMADILHA QUE ESTES DUPLOS EVITAM. Um duplo mais permissivo que o real
deixa passar exatamente a classe de erro que o real bloquearia em produção: o
teste fica verde, o código sobe, e a constraint do PostgreSQL rejeita o que
ninguém previu. Então aqui:

    `insert_if_absent`   devolve o existente e `False`, como o `ON CONFLICT`
    `register_intent`    é idempotente por (dataset, sha256), como o UNIQUE
    `transition`         é condicional ao estado anterior, como o UPDATE ... WHERE

São duplos, não mocks: eles têm comportamento e são verificados pelo estado
final, não por chamadas registradas. Um teste que afirma "chamou `transition`
uma vez" continua passando quando `transition` para de funcionar.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from types import TracebackType
from typing import Self, final

from sports_intelligence.domain.datasets.files import DatasetFile, FileStagingState
from sports_intelligence.domain.datasets.lifecycle import DatasetLifecycle
from sports_intelligence.domain.datasets.manifest import DatasetManifest
from sports_intelligence.domain.datasets.models import (
    Dataset,
    DatasetFilter,
    DatasetSummary,
    Page,
)
from sports_intelligence.domain.datasets.validation import DatasetValidationReport
from sports_intelligence.domain.shared.audit import AuditEntry
from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion


@final
class FakeDatasetRepository:
    def __init__(self) -> None:
        self.datasets: dict[DatasetId, Dataset] = {}
        self.transitions: list[tuple[str, str, str, str]] = []

    async def insert_if_absent(self, dataset: Dataset) -> tuple[Dataset, bool]:
        existente = self.datasets.get(dataset.id)
        if existente is not None:
            return existente, False
        self.datasets[dataset.id] = dataset
        return dataset, True

    async def by_id(self, dataset_id: DatasetId, *, with_files: bool = True) -> Dataset | None:
        dataset = self.datasets.get(dataset_id)
        if dataset is None:
            return None
        return dataset if with_files else dataset.with_files(())

    async def by_name_version(self, name: str, version: DatasetVersion) -> Dataset | None:
        return self.datasets.get(DatasetId.derive(name.strip().lower(), str(version)))

    async def list(
        self, *, filters: DatasetFilter, page: Page
    ) -> tuple[Sequence[DatasetSummary], int]:
        todos = [
            d
            for d in self.datasets.values()
            if (filters.lifecycle is None or d.lifecycle is filters.lifecycle)
            and (filters.competition is None or filters.competition in d.declared_competitions)
        ]
        resumos = [
            DatasetSummary(
                id=d.id,
                name=d.name,
                version=d.version,
                lifecycle=d.lifecycle,
                source_name=d.source.source_name,
                source_type=d.source.source_type.value,
                license_class=d.source.license_class.value,
                declared_competitions=d.declared_competitions,
                file_count=len(d.stored_files),
                total_bytes=d.total_bytes,
                created_at=d.created_at,
            )
            for d in todos
        ]
        return resumos[page.offset : page.offset + page.limit], len(resumos)

    async def transition(
        self,
        dataset_id: DatasetId,
        *,
        expected: DatasetLifecycle,
        target: DatasetLifecycle,
        at: Instant,
        reason: str,
        actor_id: str,
    ) -> bool:
        """Condicional ao estado anterior — como o `UPDATE ... WHERE` real.

        Um duplo que sempre aceitasse esconderia a corrida que a transição
        condicional existe para resolver, e o teste de concorrência passaria
        sem exercitar nada.
        """
        dataset = self.datasets.get(dataset_id)
        if dataset is None or dataset.lifecycle is not expected:
            return False
        self.datasets[dataset_id] = replace(dataset, lifecycle=target)
        self.transitions.append((expected.value, target.value, reason, at.isoformat()))
        return True

    async def transitions_of(self, dataset_id: DatasetId) -> Sequence[tuple[str, str, str, str]]:
        return list(self.transitions)

    def force_state(self, dataset_id: DatasetId, estado: DatasetLifecycle) -> None:
        """Põe o dataset num estado sem passar pelo grafo. SÓ para preparar
        cenário — nenhum caminho de produção faz isso."""
        self.datasets[dataset_id] = replace(self.datasets[dataset_id], lifecycle=estado)


@final
class FakeDatasetFileRepository:
    def __init__(self, datasets: FakeDatasetRepository) -> None:
        self._datasets = datasets
        self.files: dict[str, DatasetFile] = {}

    def _sincronizar(self, dataset_id: DatasetId) -> None:
        dataset = self._datasets.datasets.get(dataset_id)
        if dataset is None:
            return
        do_dataset = tuple(
            f for f in self.files.values() if f.dataset_id == dataset_id
        )
        self._datasets.datasets[dataset_id] = dataset.with_files(do_dataset)

    async def register_intent(self, file: DatasetFile) -> DatasetFile:
        chave = f"{file.dataset_id}:{file.content_hash.value}"
        existente = self.files.get(chave)
        if existente is not None:
            return existente
        self.files[chave] = file
        self._sincronizar(file.dataset_id)
        return file

    async def confirm_stored(self, file_id: str) -> bool:
        for chave, arquivo in self.files.items():
            if str(arquivo.id) != file_id:
                continue
            if arquivo.staging_state is FileStagingState.STORED:
                return False
            self.files[chave] = arquivo.confirm_stored()
            self._sincronizar(arquivo.dataset_id)
            return True
        return False

    async def mark_failed(self, file_id: str, *, reason: str) -> None:
        for chave, arquivo in self.files.items():
            if str(arquivo.id) == file_id:
                self.files[chave] = arquivo.mark_failed()
                self._sincronizar(arquivo.dataset_id)
                return

    async def by_dataset(self, dataset_id: DatasetId) -> Sequence[DatasetFile]:
        return [f for f in self.files.values() if f.dataset_id == dataset_id]

    async def by_content(self, dataset_id: DatasetId, sha256: str) -> DatasetFile | None:
        return self.files.get(f"{dataset_id}:{sha256}")

    async def record_inspection(
        self, file_id: str, *, row_count: int, column_count: int
    ) -> None:
        for chave, arquivo in self.files.items():
            if str(arquivo.id) == file_id:
                self.files[chave] = arquivo.with_inspection(
                    row_count=row_count, column_count=column_count
                )
                self._sincronizar(arquivo.dataset_id)
                return

    async def pending_older_than(self, moment: Instant) -> Sequence[DatasetFile]:
        return [
            f
            for f in self.files.values()
            if f.staging_state is FileStagingState.PENDING and f.uploaded_at < moment
        ]


@final
class FakeValidationRepository:
    def __init__(self) -> None:
        self.reports: list[DatasetValidationReport] = []

    async def save_report(self, report: DatasetValidationReport) -> None:
        self.reports.append(report)

    async def latest_for(self, dataset_id: DatasetId) -> DatasetValidationReport | None:
        do_dataset = [r for r in self.reports if r.dataset_id == dataset_id]
        return do_dataset[-1] if do_dataset else None

    async def by_id(self, report_id: str) -> DatasetValidationReport | None:
        return next((r for r in self.reports if r.id == report_id), None)

    async def history_for(
        self, dataset_id: DatasetId, *, limit: int = 10
    ) -> Sequence[DatasetValidationReport]:
        return [r for r in self.reports if r.dataset_id == dataset_id][-limit:]


@final
class FakeManifestRepository:
    def __init__(self) -> None:
        self.manifests: list[DatasetManifest] = []

    async def save(self, manifest: DatasetManifest) -> None:
        if any(m.fingerprint == manifest.fingerprint for m in self.manifests):
            return
        self.manifests.append(manifest)

    async def latest_for(self, dataset_id: DatasetId) -> DatasetManifest | None:
        do_dataset = [m for m in self.manifests if m.dataset_id == dataset_id]
        return do_dataset[-1] if do_dataset else None

    async def by_fingerprint(self, fingerprint: str) -> DatasetManifest | None:
        return next(
            (m for m in self.manifests if m.fingerprint.value == fingerprint), None
        )


@final
class FakeAuditLog:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)

    async def recent_for_dataset(
        self, dataset_id: DatasetId, *, limit: int = 50
    ) -> Sequence[AuditEntry]:
        return [e for e in self.entries if e.dataset_id == dataset_id][-limit:]

    def actions(self) -> list[str]:
        return [e.action.value for e in self.entries]


@final
class FakeUnitOfWork:
    """Um escopo que não faz nada — e conta que foi usado.

    NÃO SIMULA ROLLBACK, e é honesto quanto a isso: atomicidade sobre
    estruturas em memória seria uma encenação. O que este duplo garante é que
    o caso de uso ABRE o escopo; que o escopo de fato commita é o que os
    testes de integração provam, contra um PostgreSQL de verdade.
    """

    def __init__(self) -> None:
        self.entered = 0
        self.rolled_back = 0

    async def __aenter__(self) -> Self:
        self.entered += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def rollback(self) -> None:
        self.rolled_back += 1
