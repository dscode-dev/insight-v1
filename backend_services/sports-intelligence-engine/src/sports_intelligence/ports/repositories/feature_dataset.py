"""O registro do dataset de features — identidade, versões, execuções, objetos.

O QUE ELE GUARDA, E O QUE ELE NÃO GUARDA. Ele guarda a IDENTIDADE do dataset,
as versões com as políticas sob as quais foram construídas, os rastros de
execução e os PONTEIROS para os objetos materializados. Ele não guarda linha de
feature nenhuma — cento e cinco valores por linha e noventa e uma linhas por
partida moram no Parquet, e replicá-los aqui criaria duas verdades sobre o mesmo
número.

A TRANSIÇÃO É UM MÉTODO, E NÃO UM `UPDATE`. Quem expõe «grave este status»
permite `DRAFT → READY`; quem expõe «mova para VALIDATING» faz o grafo ser
consultado do lado de cá E do lado de lá.

`objects` SÃO REGISTRADOS NO BANCO ainda que o conteúdo esteja no bucket. É
essa lista que permite reconciliar manifesto com registro — e descobrir o
objeto órfão que uma construção interrompida deixou para trás.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.dataset.manifest import (
    FeatureObjectRef,
    HistoricalFeatureDatasetManifest,
)
from sports_intelligence.domain.features.dataset.split import SplitCounts
from sports_intelligence.domain.features.dataset.versions import (
    FeatureDatasetBuildRun,
    FeatureDatasetSpec,
    HistoricalFeatureDataset,
    HistoricalFeatureDatasetVersion,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion


@runtime_checkable
class HistoricalFeatureDatasetRepositoryPort(Protocol):
    """Identidade e versões do dataset de features."""

    async def create_dataset(
        self,
        *,
        name: str,
        at: Instant,
        created_by: Actor,
        description: str | None = None,
    ) -> HistoricalFeatureDataset: ...

    async def dataset_by_name(self, name: str) -> HistoricalFeatureDataset | None: ...

    async def dataset_by_id(self, dataset_id: str) -> HistoricalFeatureDataset | None: ...

    async def create_version(
        self,
        *,
        dataset_id: str,
        version: DatasetVersion,
        source_version_id: str,
        source_version: DatasetVersion,
        source_corpus_fingerprint: ContentHash,
        spec: FeatureDatasetSpec,
        at: Instant,
        created_by: Actor,
    ) -> HistoricalFeatureDatasetVersion:
        """Cria a versão em `DRAFT`.

        DUAS VERSÕES COM O MESMO NÚMERO NÃO EXISTEM, e a garantia é do banco:
        um índice único é o que impede que duas construções simultâneas
        publiquem duas 1.0 diferentes.
        """
        ...

    async def version_by_id(self, version_id: str) -> HistoricalFeatureDatasetVersion | None: ...

    async def version_of(
        self, dataset_id: str, version: DatasetVersion
    ) -> HistoricalFeatureDatasetVersion | None: ...

    async def transition(
        self,
        version_id: str,
        *,
        target: DatasetVersionStatus,
        at: Instant,
        raw_content_fingerprint: ContentHash | None = None,
        manifest_id: str | None = None,
        match_count: int | None = None,
        row_count: int | None = None,
        counts: SplitCounts | None = None,
        failure_reason: str | None = None,
        superseded_by: str | None = None,
    ) -> HistoricalFeatureDatasetVersion:
        """Move a versão, CONFERINDO o grafo. Nunca grava status arbitrário."""
        ...

    async def list_versions(
        self,
        dataset_id: str,
        *,
        status: DatasetVersionStatus | None = None,
        limit: int = 50,
    ) -> Sequence[HistoricalFeatureDatasetVersion]: ...

    async def latest_ready(self, dataset_id: str) -> HistoricalFeatureDatasetVersion | None:
        """A versão publicada mais recente — a que a produção deve consultar."""
        ...

    async def versions_from_corpus(
        self, source_version_id: str, *, limit: int = 50
    ) -> Sequence[HistoricalFeatureDatasetVersion]:
        """A travessia para frente: «que datasets saíram desta versão do corpus?».

        ELA EXISTE PORQUE A PERGUNTA É FEITA. Descobrir que uma versão do corpus
        tinha um defeito obriga a achar tudo que foi construído sobre ela, e sem
        este índice a resposta é uma varredura.
        """
        ...


@runtime_checkable
class FeatureDatasetBuildRepositoryPort(Protocol):
    """Os rastros de execução e os objetos materializados."""

    async def start_run(
        self, *, version_id: str, at: Instant, started_by: Actor
    ) -> FeatureDatasetBuildRun: ...

    async def finish_run(
        self,
        run_id: str,
        *,
        status: DatasetVersionStatus,
        at: Instant,
        matches_processed: int = 0,
        rows_written: int = 0,
        objects_written: int = 0,
        bytes_written: int = 0,
        failure_reason: str | None = None,
    ) -> FeatureDatasetBuildRun: ...

    async def runs_of(
        self, version_id: str, *, limit: int = 20
    ) -> Sequence[FeatureDatasetBuildRun]: ...

    async def record_objects(self, version_id: str, objects: Sequence[FeatureObjectRef]) -> int:
        """Registra os objetos gravados. Idempotente por chave de objeto.

        A IDEMPOTÊNCIA É NECESSÁRIA porque a construção pode ser repetida depois
        de uma falha parcial: reescrever o mesmo `part-00003.parquet` com o mesmo
        conteúdo é o caminho normal do retry, e ele não pode duplicar a contagem
        do manifesto.
        """
        ...

    async def objects_of(self, version_id: str) -> Sequence[FeatureObjectRef]: ...


@runtime_checkable
class FeatureDatasetManifestRepositoryPort(Protocol):
    """O manifesto persistido, com as duas impressões separadas."""

    async def save(
        self,
        manifest: HistoricalFeatureDatasetManifest,
        *,
        manifest_key: str,
        manifest_sha256: str,
    ) -> HistoricalFeatureDatasetManifest: ...

    async def by_version(self, version_id: str) -> HistoricalFeatureDatasetManifest | None: ...

    async def by_fingerprint(
        self, fingerprint: ContentHash, *, limit: int = 20
    ) -> Sequence[HistoricalFeatureDatasetManifest]:
        """«Que datasets têm este conteúdo?» — a pergunta do §96.

        DUAS CONSTRUÇÕES INDEPENDENTES DO MESMO CONTEÚDO produzem a mesma
        impressão, e descobrir isso é o que permite não reconstruir.
        """
        ...
