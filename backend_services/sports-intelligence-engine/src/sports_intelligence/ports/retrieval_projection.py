"""A porta da projeção — carregar o universo EXATO, e nada mais.

NÃO HÁ LISTA CURTA AQUI, e a ausência é a decisão do PR. O `CandidateUniverse`
é uma competição num instante EXATO da grade, e isso o torna pequeno por
construção: quarenta e sete candidatos no corpus real. Devolver o universo
inteiro e medir todos é mais barato que aproximar — foi medido, e está em
`docs/retrieval/ANN_FEASIBILITY_EXPERIMENT_V1.md`.

O QUE A PORTA DEVOLVE JÁ É EXATO. Não há distância aproximada, ordenação
proxy nem orçamento: o que volta são os `float64` do dataset normalizado, e
quem os transforma em vizinhos é o domínio, com as funções dos PRs 06.2 e 06.3.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, final, runtime_checkable

from sports_intelligence.domain.retrieval.projection.contract import (
    HistoricalRetrievalProjectionVersion,
)
from sports_intelligence.domain.retrieval.projection.payload import (
    ExactStatePayload,
    ExactTrajectoryPayload,
)


@final
@dataclass(frozen=True, slots=True)
class CandidateUniverseFilter:
    """As igualdades do universo, como estrutura.

    ELAS SÃO CINCO IGUALDADES E UMA DESIGUALDADE, e nenhuma é opcional: as
    cinco primeiras são a definição de `EXACT_MATCH_TIME_POINT` do PR-06.1, e a
    última é a exclusão da própria partida. Passá-las como estrutura — e não
    como texto de `WHERE` — é o que impede o adapter de esquecer uma, e o que
    permite ao teste de propriedade afirmar que o universo projetado é igual ao
    do oráculo.
    """

    competition: str
    period: str
    minute: int
    stoppage: int
    tie_break: str
    exclude_match_id: str

    def as_diagnostics(self) -> Mapping[str, object]:
        return {
            "competition": self.competition,
            "exclude_match_id": self.exclude_match_id,
            "minute": self.minute,
            "period": self.period,
            "stoppage": self.stoppage,
            "tie_break": self.tie_break,
        }


@final
@dataclass(frozen=True, slots=True)
class ProjectedStateCandidate:
    """Uma linha de estado lida da projeção, pronta para o cálculo EXATO."""

    semantic_key: str
    match_id: str
    competition: str
    season: str
    payload: ExactStatePayload


@final
@dataclass(frozen=True, slots=True)
class ProjectedTrajectoryCandidate:
    """Uma trajetória lida da projeção, pronta para o cálculo EXATO."""

    semantic_key: str
    anchor_key: str
    match_id: str
    competition: str
    season: str
    payload: ExactTrajectoryPayload
    #: Os slots, como a construção os viu. É deles que a trajetória é
    #: reconstruída — sem eles a impressão divergiria da do oráculo.
    slot_lineage: tuple[Any, ...] = ()


@runtime_checkable
class RetrievalProjectionPort(Protocol):
    """A leitura do universo projetado. UMA consulta por query."""

    async def count_universe(
        self,
        *,
        projection_version: HistoricalRetrievalProjectionVersion,
        universe: CandidateUniverseFilter,
    ) -> int: ...

    async def load_state_universe(
        self,
        *,
        projection_version: HistoricalRetrievalProjectionVersion,
        universe: CandidateUniverseFilter,
        axis_keys: Sequence[str],
    ) -> Sequence[ProjectedStateCandidate]:
        """TODO o universo, numa consulta só.

        UMA CONSULTA, E NÃO UMA POR CANDIDATO. O N+1 aqui teria o mesmo efeito
        que teve na leitura do Parquet: transformaria quarenta e sete
        candidatos em quarenta e sete idas ao banco, e o custo de ida e volta
        dominaria justamente o que a projeção existe para eliminar.
        """
        ...

    async def load_trajectory_universe(
        self,
        *,
        projection_version: HistoricalRetrievalProjectionVersion,
        universe: CandidateUniverseFilter,
        axis_keys: Sequence[str],
        horizons: Sequence[int],
    ) -> Sequence[ProjectedTrajectoryCandidate]: ...
