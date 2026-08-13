"""Promoção de dataset construído — que não é o registro de intake.

DOIS "DATASETS" DIFERENTES CONVIVEM NESTA BASE, e confundi-los custaria caro:

    DATASET DE INTAKE (PR-02, `dataset_registry`)
        os bytes que chegaram de fora. Evidência externa, com fonte, licença
        e hash. Vive em `domain/datasets`.

    DATASET CONSTRUÍDO (este arquivo, ainda sem implementação)
        um conjunto que o motor PRODUZIU — o índice histórico, a matriz de
        features de uma versão do espaço. Deriva do primeiro, depois de
        resolução, fusão e engenharia de features, e é ele que o caminho de
        leitura materializado consulta (ADR-0010).

O port abaixo é do SEGUNDO. Ele se chamava `DatasetRepositoryPort` até o
PR-02, e foi renomeado porque o intake trouxe um repositório com aquele nome
e responsabilidade completamente outra. Dois protocolos homônimos em pacotes
vizinhos é o tipo de coisa que ninguém percebe até importar o errado.

NADA DO PR-02 CHEGA AQUI. Um dataset em `STAGED` é evidência estruturalmente
apta a ENTRAR em resolução — não uma versão promovível. A distância entre os
dois é o PR-03 inteiro mais a barreira do ADR-0007.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.domain.shared.versioning import DatasetVersion


@runtime_checkable
class DatasetPromotionPort(Protocol):
    """Qual versão de um dataset construído está em uso."""

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
