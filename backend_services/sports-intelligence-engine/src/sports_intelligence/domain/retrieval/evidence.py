"""A prova mecânica de um vizinho — o que foi medido, o que faltou, e a conta.

O CRITÉRIO É ESTE (§195): a partir da evidência de um vizinho, tem de ser
possível RECONSTRUIR o número que o classificou, sem consultar mais nada.

    D = (ObservedSquaredSum + MissingPenaltySum) / m

Se algum vizinho puder ocupar uma posição sem que essa reconstrução seja
possível, o ranking tem uma parte que ninguém consegue explicar — e um ranking
parcialmente inexplicável é indistinguível de um ranking com defeito.

ISTO NÃO É EXPLICABILIDADE (§61). Não há frase, não há «este vizinho é parecido
porque a pressão estava alta», não há narrativa e não há linguagem natural. Há
máscaras, contagens e somas. A explicabilidade é do PR-06.7, e ela vai ser
construída SOBRE isto — o que é diferente de ser isto.

O QUE A EVIDÊNCIA NÃO CARREGA, e cada ausência é a mesma decisão do PR-06.1:

    vencedor              quem ganhou o jogo do vizinho
    placar final          idem
    gol seguinte          o que veio depois do corte
    trajetória futura     idem
    rótulo                vitória/empate/derrota
    probabilidade         qualquer número que pareça uma previsão
    confiança             `coverage` e `PenaltyShare` são INSUMO dela, e a
                          conversão é do PR-06.7

AS MÁSCARAS SÃO TEXTO POSICIONAL — `"11010"` —, e não conjuntos de nomes. Três
motivos, e o terceiro é o que decide:

    posição      a posição `i` da máscara é o eixo `i` do perfil, que é o eixo
                 `i` da soma
    tamanho      um perfil de cem eixos são cem caracteres, e não cem cadeias
    impressão    um `set[str]` serializado depende da ordem de iteração; um
                 texto posicional não depende de nada
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.availability import mask_text
from sports_intelligence.domain.retrieval.availability_distance import DistanceBreakdown
from sports_intelligence.domain.retrieval.coverage import CoverageAssessment
from sports_intelligence.domain.retrieval.distance import distance_text
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

EVIDENCE_FINGERPRINT_ALGORITHM: Final[str] = "neighbor-evidence-sha256-v1"


@final
@dataclass(frozen=True, slots=True)
class DistanceContribution:
    """Quanto UM eixo compartilhado contribuiu, e de quais dois números.

    ELA É MECÂNICA, e é o nível mais fino que este PR entrega. Não diz se o
    eixo «importa»; diz que `q = 0,4`, `c = 1,1` e que isso somou `0,49`.
    """

    feature_key: str
    query_value: float
    candidate_value: float
    squared_contribution: float

    def __post_init__(self) -> None:
        if self.squared_contribution < 0:
            raise ValidationError(
                f"contribuição negativa no eixo {self.feature_key!r}: {self.squared_contribution!r}"
            )

    @property
    def delta(self) -> float:
        return self.query_value - self.candidate_value

    def as_canonical(self) -> dict[str, object]:
        return {
            "candidate_value": distance_text(self.candidate_value),
            "feature_key": self.feature_key,
            "query_value": distance_text(self.query_value),
            "squared_contribution": distance_text(self.squared_contribution),
        }

    def __str__(self) -> str:
        return (
            f"{self.feature_key}: {distance_text(self.query_value)} vs "
            f"{distance_text(self.candidate_value)} -> "
            f"{distance_text(self.squared_contribution)}"
        )


@final
@dataclass(frozen=True, slots=True)
class NeighborEvidence:
    """Tudo que sustenta a posição de um vizinho, e nada além.

    ELA CARREGA AS TRÊS IMPRESSÕES — perfil resolvido, definição de distância e
    política de cobertura. Sem elas, `D = 0,4` é um número sem grandeza: sobre
    quantos eixos, com que piso, sob qual penalidade.
    """

    candidate_key: HistoricalFeatureSnapshotKey
    candidate_row_digest: str
    query_key: HistoricalFeatureSnapshotKey
    query_row_digest: str
    resolved_profile_fingerprint: str
    distance_definition_fingerprint: str
    coverage_policy_fingerprint: str
    #: As três máscaras, posicionais sobre o perfil ordenado.
    query_mask: str
    candidate_mask: str
    shared_mask: str
    coverage: CoverageAssessment
    breakdown: DistanceBreakdown
    shared_features: tuple[str, ...] = ()
    unshared_features: tuple[str, ...] = ()
    #: As contribuições por eixo compartilhado. Elas são OPCIONAIS no contrato
    #: e presentes na prática: o retriever só as monta para os vizinhos que
    #: sobreviveram ao top-K, porque montá-las para o universo inteiro faria a
    #: memória seguir o universo — que é exatamente o que §66 proíbe.
    contributions: tuple[DistanceContribution, ...] = ()

    def __post_init__(self) -> None:
        tamanhos = {len(self.query_mask), len(self.candidate_mask), len(self.shared_mask)}
        if tamanhos != {self.coverage.profile_axis_count}:
            raise ValidationError(
                f"máscaras de tamanhos {sorted(tamanhos)} contra um perfil de "
                f"{self.coverage.profile_axis_count} eixos: elas são posicionais "
                "sobre o perfil, e um tamanho diferente descreve outro espaço"
            )
        if self.breakdown.profile_axis_count != self.coverage.profile_axis_count:
            raise ValidationError("a conta e a cobertura discordam sobre o tamanho do perfil")
        if self.breakdown.shared_count != self.coverage.shared_count:
            raise ValidationError(
                f"a conta usou {self.breakdown.shared_count} eixos e a cobertura "
                f"declara {self.coverage.shared_count}: a penalidade e o piso "
                "estariam falando de máscaras diferentes"
            )
        if len(self.shared_features) != self.coverage.shared_count:
            raise ValidationError(
                f"{len(self.shared_features)} eixos compartilhados nomeados e "
                f"{self.coverage.shared_count} contados"
            )
        if self.contributions and len(self.contributions) != self.coverage.shared_count:
            raise ValidationError(
                f"{len(self.contributions)} contribuições para "
                f"{self.coverage.shared_count} eixos compartilhados: uma evidência "
                "com contribuições parciais não reconstrói a soma"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def dissimilarity(self) -> float:
        return self.breakdown.value

    @property
    def observed_squared_sum(self) -> float:
        return self.breakdown.observed_squared_sum

    @property
    def missing_penalty_sum(self) -> float:
        return self.breakdown.missing_penalty_sum

    @property
    def observed_mse(self) -> float | None:
        return self.breakdown.observed_mse

    @property
    def penalty_share(self) -> float | None:
        return self.breakdown.penalty_share

    @property
    def shared_count(self) -> int:
        return self.coverage.shared_count

    @property
    def is_reconstructible(self) -> bool:
        """Se as contribuições reconstroem a soma observada (§195).

        ELA COMPARA `fsum` COM `fsum`, e não com tolerância. As duas somas
        percorrem os mesmos termos na mesma ordem, então a igualdade é exata —
        e uma tolerância aqui esconderia justamente o defeito que ela procura:
        uma contribuição que não é a que entrou na conta.
        """
        if not self.contributions:
            return False
        import math

        soma = math.fsum(c.squared_contribution for c in self.contributions)
        return soma == self.observed_squared_sum

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        """A identidade da evidência — quem, sob que régua, com que conta.

        AS CONTRIBUIÇÕES FICAM DE FORA. Elas são derivadas exatas dos valores
        das duas linhas sob a máscara, e as duas linhas já entram por digesto:
        incluí-las duplicaria a informação e faria a impressão mudar conforme o
        retriever tenha ou não decidido montá-las.

        AS FRAÇÕES DE COBERTURA TAMBÉM FICAM DE FORA — `coverage.as_canonical`
        carrega só contagens, pelo mesmo motivo.
        """
        return {
            "algorithm": EVIDENCE_FINGERPRINT_ALGORITHM,
            "candidate_key": self.candidate_key.text,
            "candidate_mask": self.candidate_mask,
            "candidate_row_digest": self.candidate_row_digest,
            "coverage": self.coverage.as_canonical(),
            "coverage_policy_fingerprint": self.coverage_policy_fingerprint,
            "dissimilarity": distance_text(self.dissimilarity),
            "distance_definition_fingerprint": self.distance_definition_fingerprint,
            "missing_penalty_sum": distance_text(self.missing_penalty_sum),
            "observed_squared_sum": distance_text(self.observed_squared_sum),
            "query_key": self.query_key.text,
            "query_mask": self.query_mask,
            "query_row_digest": self.query_row_digest,
            "resolved_profile_fingerprint": self.resolved_profile_fingerprint,
            "shared_mask": self.shared_mask,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "dissimilarity": self.dissimilarity,
            "missing_penalty_sum": self.missing_penalty_sum,
            "observed_mse": self.observed_mse,
            "observed_squared_sum": self.observed_squared_sum,
            "penalty_share": self.penalty_share,
            "shared_count": self.shared_count,
            "shared_profile_coverage": self.coverage.shared_profile_coverage,
            "unshared_count": self.coverage.unshared_count,
        }

    def __str__(self) -> str:
        return (
            f"{self.candidate_key.text}: D={distance_text(self.dissimilarity)} "
            f"s={self.shared_count}/{self.coverage.profile_axis_count}"
        )


def build_evidence(
    *,
    feature_keys: Sequence[str],
    query_key: HistoricalFeatureSnapshotKey,
    query_row_digest: str,
    query_values: Sequence[float | None],
    query_mask: Sequence[bool],
    candidate_key: HistoricalFeatureSnapshotKey,
    candidate_row_digest: str,
    candidate_values: Sequence[float | None],
    candidate_mask: Sequence[bool],
    shared: Sequence[bool],
    coverage: CoverageAssessment,
    breakdown: DistanceBreakdown,
    resolved_profile_fingerprint: str,
    distance_definition_fingerprint: str,
    coverage_policy_fingerprint: str,
    with_contributions: bool = True,
) -> NeighborEvidence:
    """Monta a evidência a partir das duas linhas e da máscara.

    `with_contributions` EXISTE PELA MEMÓRIA, e não pela conveniência. Montar
    as contribuições de todo candidato do universo faria a alocação seguir o
    universo; montá-las só para quem entrou no top-K a mantém em `O(K · m)`.
    """
    contribuicoes: list[DistanceContribution] = []
    compartilhados: list[str] = []
    ausentes: list[str] = []
    for indice, chave in enumerate(feature_keys):
        if not shared[indice]:
            ausentes.append(chave)
            continue
        compartilhados.append(chave)
        if not with_contributions:
            continue
        q = query_values[indice]
        c = candidate_values[indice]
        if q is None or c is None:  # pragma: no cover — a máscara já garantiu
            raise ValidationError(f"eixo {chave!r} compartilhado e sem valor dos dois lados")
        delta = q - c
        contribuicoes.append(
            DistanceContribution(
                feature_key=chave,
                query_value=q,
                candidate_value=c,
                squared_contribution=delta * delta,
            )
        )
    return NeighborEvidence(
        candidate_key=candidate_key,
        candidate_row_digest=candidate_row_digest,
        query_key=query_key,
        query_row_digest=query_row_digest,
        resolved_profile_fingerprint=resolved_profile_fingerprint,
        distance_definition_fingerprint=distance_definition_fingerprint,
        coverage_policy_fingerprint=coverage_policy_fingerprint,
        query_mask=mask_text(query_mask),
        candidate_mask=mask_text(candidate_mask),
        shared_mask=mask_text(shared),
        coverage=coverage,
        breakdown=breakdown,
        shared_features=tuple(compartilhados),
        unshared_features=tuple(ausentes),
        contributions=tuple(contribuicoes),
    )


def evidence_summary(evidence: NeighborEvidence) -> Sequence[str]:
    """As linhas do resumo legível — para a CLI e para o relatório."""
    parcela = evidence.penalty_share
    mse = evidence.observed_mse
    return [
        f"vizinho         {evidence.candidate_key.text}",
        f"dissimilaridade {distance_text(evidence.dissimilarity)}",
        f"  observado     {distance_text(evidence.observed_squared_sum)}",
        f"  incerteza     {distance_text(evidence.missing_penalty_sum)}",
        "  MSE observado " + ("-" if mse is None else distance_text(mse)),
        "  fração incerta " + ("-" if parcela is None else format(parcela, ".1%")),
        f"compartilhados  {evidence.shared_count}"
        f"/{evidence.coverage.profile_axis_count}"
        f" ({evidence.coverage.shared_profile_coverage:.1%})",
        f"máscara query   {evidence.query_mask}",
        f"máscara cand.   {evidence.candidate_mask}",
        f"máscara comum   {evidence.shared_mask}",
        f"impressão       {evidence.fingerprint[:16]}",
    ]
