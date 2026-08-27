"""Um vizinho histórico — e tudo que ele deliberadamente NÃO carrega.

O QUE ELE TEM: posição no ranking, identidade do candidato, instante, digesto
da linha, a dissimilaridade, e as impressões que dizem sob qual régua ela foi
medida.

O QUE ELE NÃO TEM, e cada ausência é uma decisão do PR-06.1:

    resultado final       quem ganhou aquele jogo
    gol seguinte          o que aconteceu no minuto seguinte
    rótulo                vitória/empate/derrota, faixa de placar
    evolução futura       a trajetória depois do corte
    peso                  `w = e^(-λd)` é do PR-06.5
    agregação             média ponderada dos vizinhos é do PR-06.5
    confiança             é do PR-06.7

    NÃO É QUE ELES AINDA NÃO FORAM IMPLEMENTADOS. É que um vizinho que
    carregasse o resultado faria a recuperação e a inteligência compartilharem
    um objeto — e o dia em que alguém filtrasse candidatos por rótulo, o
    vazamento estaria dentro do contrato, não fora dele.

A ORDEM É `(dissimilaridade, chave canônica)`, sempre. O desempate por chave
não é cosmético: sem ele, dois candidatos à mesma distância trocariam de
posição entre execuções conforme a ordem de leitura do bucket, e o resultado
deixaria de ter impressão estável.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.distance import distance_text
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.shared.errors import ValidationError


@final
@dataclass(frozen=True, slots=True)
class HistoricalNeighbor:
    """Um candidato no top-K, com a régua que o mediu ao lado.

    AS DUAS IMPRESSÕES VIAJAM COM ELE — a do perfil resolvido e a da definição
    de distância. Um número solto não diz nada: `0,84` sobre catorze eixos e
    `0,84` sobre vinte e nove são grandezas diferentes, e as duas parecem a
    mesma coisa numa tabela.
    """

    rank: int
    key: HistoricalFeatureSnapshotKey
    match_id: str
    competition: str
    season: str
    position: GridTimePoint
    row_digest: str
    #: A DISSIMILARIDADE, e não «a distância»: ela é L2 AO QUADRADO, e o nome
    #: do campo carrega isso para que ninguém a compare com um limiar
    #: euclidiano.
    squared_distance: float
    resolved_profile_fingerprint: str
    distance_definition_fingerprint: str

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValidationError(f"vizinho com posição {self.rank}: o ranking começa em 1")
        if self.squared_distance < 0:
            raise ValidationError(
                f"dissimilaridade negativa: {self.squared_distance!r}. Uma soma de "
                "quadrados não pode ser negativa, e isto é defeito de cálculo",
                context={"key": self.key.text},
            )

    @property
    def canonical_key(self) -> str:
        """A chave de desempate. Ver `result.py` para a ordem completa."""
        return self.key.text

    def as_canonical(self) -> dict[str, object]:
        return {
            "competition": self.competition,
            "distance_definition_fingerprint": self.distance_definition_fingerprint,
            "key": self.key.text,
            "match_id": self.match_id,
            "position": self.position.as_canonical(),
            "rank": self.rank,
            "resolved_profile_fingerprint": self.resolved_profile_fingerprint,
            "row_digest": self.row_digest,
            "season": self.season,
            "squared_distance": distance_text(self.squared_distance),
        }

    def __str__(self) -> str:
        return f"#{self.rank} {self.key.text} d²={distance_text(self.squared_distance)}"
