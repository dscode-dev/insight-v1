"""As quatro camadas de arquivo, e por que são quatro e não uma.

    RawArchive            o que o provedor mandou, byte a byte
    CanonicalArchive      o mesmo fato traduzido para o nosso vocabulário
    StateArchive          o que se sabia da partida em cada instante
    IntelligenceArchive   o que o motor concluiu a partir de cada estado

CADA UMA EXISTE PARA SOBREVIVER A UM TIPO DE ERRO DIFERENTE, e é isso que
justifica o custo de guardar quatro vezes:

  o bruto sobrevive a um erro NOSSO de normalização — se o mapeamento estava
  errado, é dele que tudo é reconstruído, e sem ele o erro é permanente;

  o canônico sobrevive a uma mudança de fonte — trocar de provedor não deve
  reconstruir features de anos;

  o estado sobrevive a uma engine nova — aplicar a v4 ao passado exige o
  estado, não os eventos crus;

  a inteligência sobrevive a si mesma: é o registro do que foi dito, e é
  contra ele que se compara o que a versão seguinte diz.

O BRUTO É IMUTÁVEL POR CONTRATO. Nenhum destes ports tem `update` ou `delete`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from sports_intelligence.domain.events.idempotency import ImportId, SourceEventId
from sports_intelligence.domain.intelligence.snapshots import (
    IntelligenceSnapshotMetadata,
    StateSnapshotMetadata,
)
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.provenance import DataProvenance


@runtime_checkable
class RawArchivePort(Protocol):
    """O que o provedor mandou, exatamente como mandou.

    A ÚNICA CAMADA QUE NÃO PODE SER RECONSTRUÍDA. Todas as outras derivam
    desta; esta deriva do provedor, que pode mudar a API, apagar o histórico
    ou encerrar o contrato. Guardá-la verbatim é o que torna todo o resto
    reconstruível.
    """

    async def store(
        self,
        *,
        source_event_id: SourceEventId,
        payload: bytes,
        provenance: DataProvenance,
        import_id: ImportId,
    ) -> bool:
        """Grava o bruto. Devolve False se já estava lá.

        FALSE E NÃO ERRO: reprocessar é normal — stream reentregando, worker
        reiniciando, lote reenviado — e tratar isso como falha transforma a
        operação normal em alarme.
        """
        ...

    async def fetch(self, source_event_id: SourceEventId) -> bytes | None: ...


@runtime_checkable
class CanonicalArchivePort(Protocol):
    """O fato traduzido para o vocabulário do domínio.

    Aqui as entidades já são nossas: `TeamId` e não "Arsenal FC". A tradução
    aconteceu, e com ela a resolução de identidade — que pode ter falhado, e é
    por isso que a procedência continua junto.
    """

    async def store(
        self,
        *,
        match_id: MatchId,
        records: Sequence[Mapping[str, Any]],
        provenance: DataProvenance,
        import_id: ImportId,
    ) -> int:
        """Grava os registros canônicos. Devolve quantos entraram de fato.

        O NÚMERO IMPORTA: "gravado com sucesso" sem contagem é uma afirmação
        sem medida, e é assim que um lote que entrou pela metade passa por
        completo.
        """
        ...


@runtime_checkable
class StateArchivePort(Protocol):
    """O que se sabia da partida em cada instante.

    A camada que torna reprocessamento possível: uma engine nova aplicada ao
    passado precisa do estado, não da sequência de eventos crus.
    """

    async def store(self, metadata: StateSnapshotMetadata, features: Mapping[str, Any]) -> None:
        """Append-only. Um estado corrigido é um `state_version` maior, e o
        anterior permanece — ele é a evidência do que se sabia antes."""
        ...

    async def latest(self, match_id: MatchId) -> StateSnapshotMetadata | None: ...

    async def timeline(self, match_id: MatchId) -> Sequence[StateSnapshotMetadata]:
        """Todos os estados, em ordem de versão. É o que permite responder
        "o que o motor sabia no minuto 63" sem recalcular nada."""
        ...


@runtime_checkable
class IntelligenceArchivePort(Protocol):
    """O que o motor concluiu, com as versões que produziram a conclusão."""

    async def store(
        self, metadata: IntelligenceSnapshotMetadata, payload: Mapping[str, Any]
    ) -> None: ...

    async def latest(self, match_id: MatchId) -> IntelligenceSnapshotMetadata | None:
        """A conclusão mais recente. É a fonte do caminho de leitura
        materializado (ADR-0010) — não um recálculo."""
        ...
