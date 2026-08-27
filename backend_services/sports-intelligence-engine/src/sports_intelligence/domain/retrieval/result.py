"""O resultado exato — o ranking, e a contabilidade que o justifica.

ELE CARREGA A ATRIÇÃO INTEIRA, e não só os vizinhos. Um top-10 sozinho não
permite dizer se ele saiu de dez mil candidatos ou de onze — e essa diferença
muda completamente o que o número significa.

    universe_count        quantos candidatos a política admitiu
    comparable_count      quantos tinham TODOS os eixos do perfil
    ineligible_count      a diferença, aberta por motivo
    returned_k            `min(requested_k, comparable_count)`

A ATRIÇÃO É O PRODUTO CIENTÍFICO DESTE PR, tanto quanto o ranking. Se 90 % dos
candidatos caem por `INCOMPLETE_PROFILE`, isso não é um defeito a consertar
aqui: é a medição que justifica o PR-06.2 existir. Escondê-la atrás de um
top-K cheio seria transformar evidência em silêncio.

`exhaustive = True` É UMA AFIRMAÇÃO, e ela é conferida. Ela significa que todo
candidato comparável recebeu distância antes de o top-K ser escolhido — sem
poda por distância, sem parada antecipada, sem amostragem. O campo existe
porque um dia haverá um resultado aproximado ao lado deste, e os dois precisam
ser distinguíveis por tipo e não por convenção de nome.

A IMPRESSÃO DO RESULTADO COBRE A PERGUNTA E A RESPOSTA. A pergunta é a linha da
query, o universo, o perfil, a distância e o `K`; a resposta é a lista ordenada
de `(posição, chave, digesto, distância canônica)`. Duas execuções com a mesma
pergunta produzem a mesma impressão — e é isso que torna «o ANN acertou?» uma
comparação, e não uma opinião.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.distance import distance_text
from sports_intelligence.domain.retrieval.neighbor import HistoricalNeighbor
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

RESULT_FINGERPRINT_ALGORITHM: Final[str] = "exact-retrieval-result-sha256-v1"


@final
@dataclass(frozen=True, slots=True)
class ExactRetrievalResult:
    """O top-K exato de uma query, com a contabilidade do universo."""

    query_key: HistoricalFeatureSnapshotKey
    query_row_digest: str
    competition: str
    candidate_policy_fingerprint: str
    candidate_universe_fingerprint: str
    retrieval_profile_fingerprint: str
    resolved_profile_fingerprint: str
    distance_definition_fingerprint: str
    axis_count: int
    requested_k: int
    universe_count: int = 0
    comparable_count: int = 0
    neighbors: tuple[HistoricalNeighbor, ...] = ()
    ineligible: Mapping[str, int] = field(default_factory=dict)
    #: SEMPRE `True` NESTE PR, e o campo existe assim mesmo: ele é o que
    #: distinguirá este resultado de um aproximado quando houver um.
    exhaustive: bool = True

    def __post_init__(self) -> None:
        if self.returned_k != len(self.neighbors):
            raise ValidationError(
                f"resultado declarando {self.returned_k} vizinhos e carregando "
                f"{len(self.neighbors)}"
            )
        if len(self.neighbors) > self.requested_k:
            raise ValidationError(
                f"{len(self.neighbors)} vizinhos para um pedido de "
                f"{self.requested_k}: o top-K não pode devolver mais do que se pediu"
            )
        if self.comparable_count > self.universe_count:
            raise ValidationError(
                f"{self.comparable_count} comparáveis de um universo de "
                f"{self.universe_count}: o subconjunto é maior que o conjunto"
            )
        esperados = tuple(range(1, len(self.neighbors) + 1))
        if tuple(v.rank for v in self.neighbors) != esperados:
            raise ValidationError(
                "posições do ranking fora de sequência: elas são 1..N, e um buraco "
                "faria o consumidor achar que um vizinho foi omitido"
            )
        anterior: tuple[float, str] | None = None
        for vizinho in self.neighbors:
            atual = (vizinho.squared_distance, vizinho.canonical_key)
            if anterior is not None and atual < anterior:
                raise ValidationError(
                    f"vizinho {vizinho.key} fora da ordem canônica: o ranking é por "
                    "(dissimilaridade, chave), e uma inversão faria duas execuções "
                    "produzirem rankings diferentes sobre os mesmos números",
                    context={"key": vizinho.key.text},
                )
            anterior = atual
        if not self.exhaustive:
            raise ValidationError(
                "resultado do PR-06.1 declarado não exaustivo: este é o ORÁCULO, e um "
                "resultado parcial aqui não teria contra o que ser comparado"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def returned_k(self) -> int:
        return len(self.neighbors)

    @property
    def ineligible_count(self) -> int:
        return self.universe_count - self.comparable_count

    @property
    def is_empty(self) -> bool:
        """Se nenhum vizinho foi devolvido.

        ISSO É UM RESULTADO VÁLIDO, e não uma falha. Uma competição com poucos
        candidatos naquele instante devolve poucos — ou nenhum —, e completar o
        top-K com outra liga produziria um `K` cheio e falso.
        """
        return not self.neighbors

    @property
    def comparable_ratio(self) -> float:
        """`comparable / universe`. Diagnóstico, e nunca insumo de pontuação."""
        return 0.0 if not self.universe_count else self.comparable_count / self.universe_count

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "axis_count": self.axis_count,
            "comparable_count": self.comparable_count,
            "comparable_ratio": self.comparable_ratio,
            "ineligible_count": self.ineligible_count,
            "requested_k": self.requested_k,
            "returned_k": self.returned_k,
            "universe_count": self.universe_count,
            **{f"ineligible_{k}": v for k, v in sorted(self.ineligible.items())},
        }

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        """A pergunta e a resposta — sem contagens de atrição.

        AS CONTAGENS FICAM DE FORA DA IMPRESSÃO, e a decisão é a mesma dos
        outros contratos desta base: elas são diagnóstico. Duas execuções que
        cheguem ao mesmo ranking pelos mesmos candidatos são o mesmo resultado,
        e a atrição já está determinada pelo universo e pelo perfil — que
        entram por impressão.
        """
        return {
            "algorithm": RESULT_FINGERPRINT_ALGORITHM,
            "candidate_policy_fingerprint": self.candidate_policy_fingerprint,
            "candidate_universe_fingerprint": self.candidate_universe_fingerprint,
            "distance_definition_fingerprint": self.distance_definition_fingerprint,
            "neighbors": [
                {
                    "key": v.key.text,
                    "rank": v.rank,
                    "row_digest": v.row_digest,
                    "squared_distance": distance_text(v.squared_distance),
                }
                for v in self.neighbors
            ],
            "query_row_digest": self.query_row_digest,
            "requested_k": self.requested_k,
            "resolved_profile_fingerprint": self.resolved_profile_fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def top(self, k: int) -> tuple[HistoricalNeighbor, ...]:
        """O prefixo de tamanho `k`.

        ELE EXISTE PARA A PROPRIEDADE DO PREFIXO (§70): `top(10)` de um
        resultado com `K=50` tem de ser exatamente o resultado de `K=10` sobre
        o mesmo universo. Sem esse método, cada teste faria o próprio fatiamento
        e a propriedade viraria uma convenção.
        """
        if k < 1:
            raise ValidationError(f"prefixo de tamanho {k}")
        return self.neighbors[:k]

    def __str__(self) -> str:
        return (
            f"{self.query_key.text}: {self.returned_k}/{self.requested_k} vizinhos de "
            f"{self.comparable_count}/{self.universe_count} candidatos "
            f"[{self.fingerprint[:12]}]"
        )


def result_summary(result: ExactRetrievalResult) -> Sequence[str]:
    """As linhas do resumo legível — para a CLI e para o relatório."""
    linhas = [
        f"query      {result.query_key.text}",
        f"competição {result.competition}",
        f"universo   {result.universe_count}",
        f"comparáveis {result.comparable_count} ({result.comparable_ratio:.1%} do universo)",
        f"K          {result.returned_k}/{result.requested_k}",
        f"eixos      {result.axis_count}",
    ]
    linhas.extend(
        f"  inelegível {motivo}: {contagem}"
        for motivo, contagem in sorted(result.ineligible.items())
    )
    linhas.extend(str(vizinho) for vizinho in result.neighbors)
    linhas.append(f"impressão  {result.fingerprint[:16]}")
    return linhas
