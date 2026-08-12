"""Os envelopes dos snapshots. O conteúdo matemático vem nos PRs seguintes.

DOIS SNAPSHOTS, E A DIFERENÇA ENTRE ELES É O CAMINHO DE LEITURA INTEIRO:

    StateSnapshot          o que se sabia da partida naquele instante
    IntelligenceSnapshot   o que o motor concluiu a partir daquele estado

O primeiro é entrada, o segundo é saída. Separá-los é o que permite
reprocessar: guardando o estado, uma engine nova pode ser aplicada ao passado
sem reconstruir a partida a partir de eventos crus.

IMUTÁVEIS, E ISSO NÃO É ESTILO. Um snapshot é o registro do que se sabia num
instante. Alterá-lo apaga a única evidência de que a conclusão daquele momento
fazia sentido com a informação daquele momento — e sem ela nenhuma auditoria
de "por que o motor disse aquilo" é possível. Correção se faz com snapshot
NOVO, com `state_version` maior.

`state_version` É O QUE ORDENA. Dois snapshots do mesmo instante existem: um
provedor pode corrigir um evento. O carimbo de tempo empata, a versão não.

TODA CONCLUSÃO CARREGA AS VERSÕES QUE A PRODUZIRAM. Sem `engine_version` e
`feature_space_version` na saída, comparar a conclusão de hoje com a de ontem
mede a mudança do código junto com a mudança dos dados, e não há como separar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from sports_intelligence.domain.shared.identity import MatchId, SnapshotId
from sports_intelligence.domain.shared.provenance import SourceType
from sports_intelligence.domain.shared.quality import DataQuality
from sports_intelligence.domain.shared.temporal import Instant, MatchClock
from sports_intelligence.domain.shared.versioning import EngineVersion, FeatureSpaceVersion


@final
@dataclass(frozen=True, slots=True)
class StateSnapshotMetadata:
    """O cabeçalho de um estado. As features vêm no PR que as definir."""

    snapshot_id: SnapshotId
    match_id: MatchId
    #: Monotônica por partida. É ela que ordena, não o relógio.
    state_version: int
    occurred_at: Instant
    #: O minuto do jogo. `None` fora dos períodos com bola rolando.
    clock: MatchClock | None
    feature_space_version: FeatureSpaceVersion
    #: A qualidade do que ALIMENTOU este estado. Um snapshot construído sobre
    #: dado ruim não fica bom por ter sido construído corretamente.
    source_quality: DataQuality
    origin: SourceType

    def __post_init__(self) -> None:
        if self.state_version < 0:
            raise ValueError(f"state_version negativa: {self.state_version}")

    def supersedes(self, other: StateSnapshotMetadata) -> bool:
        """Se este substitui aquele — mesma partida, versão maior."""
        if self.match_id != other.match_id:
            raise ValueError(
                "comparação entre snapshots de partidas diferentes: "
                f"{self.match_id} e {other.match_id}"
            )
        return self.state_version > other.state_version


@final
@dataclass(frozen=True, slots=True)
class IntelligenceSnapshotMetadata:
    """O cabeçalho de uma conclusão, com tudo que a produziu.

    `state_version` AQUI É A DO ESTADO DE ENTRADA, não uma numeração própria.
    É o que amarra a conclusão ao estado exato que a gerou, e sem essa amarra
    não há como reproduzir: dois estados do mesmo instante existem, e a
    conclusão veio de um deles.
    """

    snapshot_id: SnapshotId
    match_id: MatchId
    state_version: int
    generated_at: Instant
    engine_version: EngineVersion
    feature_space_version: FeatureSpaceVersion

    def __post_init__(self) -> None:
        if self.state_version < 0:
            raise ValueError(f"state_version negativa: {self.state_version}")

    def assert_comparable(self, other: IntelligenceSnapshotMetadata) -> None:
        """Recusa comparar conclusões que não são comparáveis.

        Usado em regressão: um baseline gerado por outra engine ou outro
        espaço de features produz um diff que descreve a mudança de código, e
        lê-lo como mudança de comportamento é a leitura errada.
        """
        self.engine_version.assert_comparable(other.engine_version)
        self.feature_space_version.assert_comparable(other.feature_space_version)
