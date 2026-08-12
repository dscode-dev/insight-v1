"""Datasets: conjuntos construídos, versionados e reconstruíveis."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.domain.shared.versioning import DatasetVersion


@runtime_checkable
class DatasetRepositoryPort(Protocol):
    async def get_active_version(self, dataset_id: DatasetId) -> DatasetVersion | None:
        """A versão em uso, ou None se nenhuma foi promovida.

        `None` é um estado normal: um dataset construído e ainda não promovido
        existe e não deve ser lido. Devolver a última construída como se fosse
        ativa é como uma versão não aprovada entra em produção.
        """
        ...

    async def promote(self, dataset_id: DatasetId, version: DatasetVersion) -> None:
        """Torna uma versão a ativa. Operação administrativa, do Control Plane."""
        ...
