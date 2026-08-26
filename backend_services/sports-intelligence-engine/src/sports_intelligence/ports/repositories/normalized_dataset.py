"""O registro do ajuste e do dataset normalizado.

TRÊS PORTS, E A SEPARAÇÃO SEGUE O CICLO DE VIDA:

    NormalizerArtifactSetRepositoryPort      o AJUSTE — medianas e IQRs
    NormalizedFeatureDatasetRepositoryPort   a IDENTIDADE e as versões
    NormalizedDatasetBuildRepositoryPort     os rastros e os objetos

O PRIMEIRO É O ÚNICO QUE GUARDA NÚMERO. Um conjunto de artefatos é algumas
dezenas de milhares de medianas e IQRs — pequeno o bastante para o PostgreSQL, e
pequeno o bastante para ser consultado por linha na leitura ao vivo, que é
justamente o que o PR-06 vai precisar. As LINHAS normalizadas continuam no
object store (ADR-0037): elas são cento e cinco valores por linha, e replicá-las
no banco criaria duas verdades sobre o mesmo número.

O AJUSTE É PERSISTIDO EM `Decimal`, E NÃO EM `double`. A mediana e o IQR são o
insumo de toda transformação; gravá-los em ponto flutuante faria a escala de uma
competição depender do arredondamento do driver. `numeric` no banco, `Decimal`
na memória, e a conversão para `float64` acontece uma vez só — na SAÍDA, e
declaradamente (ADR-0040).

A IMUTABILIDADE É DO REPOSITÓRIO, E NÃO DA DISCIPLINA. Um conjunto em `READY`
não aceita artefato novo: quem quiser reajustar cria outro conjunto. Sem isso,
uma versão normalizada publicada apontaria para um ajuste que mudou depois
dela — e a impressão gravada na linha deixaria de descrever os números dela.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.dataset.split import SplitCounts
from sports_intelligence.domain.features.normalized.artifacts import (
    CompetitionNormalizerArtifactBundle,
    NormalizerArtifactSet,
)
from sports_intelligence.domain.features.normalized.manifest import (
    NormalizedFeatureDatasetManifest,
    NormalizedObjectRef,
)
from sports_intelligence.domain.features.normalized.versions import (
    NormalizedFeatureDatasetBuildRun,
    NormalizedFeatureRepresentationSpec,
    NormalizedHistoricalFeatureDataset,
    NormalizedHistoricalFeatureDatasetVersion,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion


@runtime_checkable
class NormalizerArtifactSetRepositoryPort(Protocol):
    """O ajuste persistido — o conjunto, os pacotes e os artefatos."""

    async def create_set(
        self,
        *,
        plan_fingerprint: str,
        split_fingerprint: str,
        reference_end_exclusive: Instant,
        reference_fingerprint: str,
        source_version_id: str,
        source_raw_content_fingerprint: str,
        reference_rows: int,
        at: Instant,
        created_by: Actor,
    ) -> NormalizerArtifactSet:
        """Cria o conjunto em `DRAFT`, ainda sem pacote nenhum."""
        ...

    async def save_bundles(
        self,
        set_id: str,
        bundles: Sequence[CompetitionNormalizerArtifactBundle],
    ) -> int:
        """Grava os pacotes e os artefatos. RECUSA um conjunto já publicado.

        A RECUSA É DO REPOSITÓRIO. Um `READY` que aceitasse artefato novo faria
        toda versão normalizada publicada sobre ele passar a apontar para
        números diferentes dos que ela gravou.
        """
        ...

    async def by_id(self, set_id: str) -> NormalizerArtifactSet | None: ...

    async def by_fingerprint(self, fingerprint: str) -> NormalizerArtifactSet | None:
        """«Este ajuste já existe?» — a pergunta que evita reajustar.

        DOIS AJUSTES SOBRE A MESMA REFERÊNCIA SÃO O MESMO AJUSTE, e a impressão
        é o que permite descobrir isso sem recalcular mediana nenhuma.
        """
        ...

    async def transition(
        self,
        set_id: str,
        *,
        target: DatasetVersionStatus,
        at: Instant,
        failure_reason: str | None = None,
    ) -> NormalizerArtifactSet:
        """Move o conjunto, CONFERINDO o grafo."""
        ...

    async def list_sets(
        self,
        *,
        status: DatasetVersionStatus | None = None,
        source_version_id: str | None = None,
        limit: int = 50,
    ) -> Sequence[NormalizerArtifactSet]: ...

    async def bundle_of(
        self, set_id: str, *, competition: str
    ) -> CompetitionNormalizerArtifactBundle | None:
        """UM pacote, sem carregar o conjunto inteiro.

        ELE EXISTE PARA A LEITURA AO VIVO. Normalizar uma partida da Premier
        League não pode exigir trazer as medianas de todas as ligas do
        conjunto — e é este método que o PR-06 vai chamar.
        """
        ...


@runtime_checkable
class NormalizedFeatureDatasetRepositoryPort(Protocol):
    """A identidade e as versões da representação normalizada."""

    async def create_dataset(
        self,
        *,
        name: str,
        source_dataset_id: str,
        at: Instant,
        created_by: Actor,
        description: str | None = None,
    ) -> NormalizedHistoricalFeatureDataset: ...

    async def dataset_by_name(self, name: str) -> NormalizedHistoricalFeatureDataset | None: ...

    async def dataset_by_id(self, dataset_id: str) -> NormalizedHistoricalFeatureDataset | None: ...

    async def create_version(
        self,
        *,
        dataset_id: str,
        version: DatasetVersion,
        source_version_id: str,
        source_version: DatasetVersion,
        source_raw_content_fingerprint: ContentHash,
        source_row_count: int,
        representation: NormalizedFeatureRepresentationSpec,
        at: Instant,
        created_by: Actor,
    ) -> NormalizedHistoricalFeatureDatasetVersion:
        """Cria a versão em `DRAFT`."""
        ...

    async def version_by_id(
        self, version_id: str
    ) -> NormalizedHistoricalFeatureDatasetVersion | None: ...

    async def version_of(
        self, dataset_id: str, version: DatasetVersion
    ) -> NormalizedHistoricalFeatureDatasetVersion | None: ...

    async def transition(
        self,
        version_id: str,
        *,
        target: DatasetVersionStatus,
        at: Instant,
        normalized_content_fingerprint: ContentHash | None = None,
        normalized_reference_content_fingerprint: ContentHash | None = None,
        normalized_evaluation_content_fingerprint: ContentHash | None = None,
        manifest_id: str | None = None,
        match_count: int | None = None,
        row_count: int | None = None,
        counts: SplitCounts | None = None,
        failure_reason: str | None = None,
        superseded_by: str | None = None,
    ) -> NormalizedHistoricalFeatureDatasetVersion:
        """Move a versão, CONFERINDO o grafo."""
        ...

    async def list_versions(
        self,
        dataset_id: str,
        *,
        status: DatasetVersionStatus | None = None,
        limit: int = 50,
    ) -> Sequence[NormalizedHistoricalFeatureDatasetVersion]: ...

    async def latest_ready(
        self, dataset_id: str
    ) -> NormalizedHistoricalFeatureDatasetVersion | None: ...

    async def versions_from_artifact_set(
        self, artifact_set_id: str, *, limit: int = 50
    ) -> Sequence[NormalizedHistoricalFeatureDatasetVersion]:
        """«Que datasets saíram deste ajuste?».

        ELA EXISTE PORQUE A PERGUNTA É FEITA. Descobrir que uma competição foi
        ajustada sobre uma referência incompleta obriga a achar tudo que foi
        normalizado com aqueles números.
        """
        ...


@runtime_checkable
class NormalizedDatasetBuildRepositoryPort(Protocol):
    """Os rastros de execução, os objetos e o manifesto."""

    async def start_run(
        self, *, version_id: str, at: Instant, started_by: Actor
    ) -> NormalizedFeatureDatasetBuildRun: ...

    async def finish_run(
        self,
        run_id: str,
        *,
        status: DatasetVersionStatus,
        at: Instant,
        rows_read: int = 0,
        rows_written: int = 0,
        objects_written: int = 0,
        bytes_written: int = 0,
        artifact_unavailable_cells: int = 0,
        failure_reason: str | None = None,
    ) -> NormalizedFeatureDatasetBuildRun: ...

    async def runs_of(
        self, version_id: str, *, limit: int = 20
    ) -> Sequence[NormalizedFeatureDatasetBuildRun]: ...

    async def record_objects(self, version_id: str, objects: Sequence[NormalizedObjectRef]) -> int:
        """Registra os objetos gravados. Idempotente por chave de objeto."""
        ...

    async def objects_of(self, version_id: str) -> Sequence[NormalizedObjectRef]: ...

    async def save_manifest(
        self,
        manifest: NormalizedFeatureDatasetManifest,
        *,
        manifest_key: str,
        manifest_sha256: str,
    ) -> NormalizedFeatureDatasetManifest: ...

    async def manifest_by_version(
        self, version_id: str
    ) -> NormalizedFeatureDatasetManifest | None: ...
