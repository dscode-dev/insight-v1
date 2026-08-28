"""Quem pode ser candidato histórico — declarado, fechado e impresso.

A EQUAÇÃO INTEIRA, e ela cabe em quatro linhas:

    Candidates(q) = { c ∈ REFERENCE :
                        Competition(c) = Competition(q)
                      ∧ TimePoint(c)   = TimePoint(q)
                      ∧ Match(c)      ≠ Match(q) }

CADA UMA DAS QUATRO CONDIÇÕES IMPEDE UM VAZAMENTO DIFERENTE, e nenhuma delas é
conveniência:

    c ∈ REFERENCE      o PR-05.5.2 provou `ArtifactSet = f(REFERENCE)`. Um
                       candidato de AVALIAÇÃO seria comparado sob uma escala
                       que ele ajudou a definir — e o número sairia plausível
    mesma competição   ligas jogam futebol diferente. A escala já é por
                       competição (ADR-0035); cruzá-las compararia números que
                       foram normalizados por medianas distintas
    mesmo instante     sem ele, `minute` é um eixo do espaço e a diferença de
                       relógio vira a maior parcela da distância
    partida diferente  a atomicidade da divisão normalmente já garante isso.
                       «Normalmente» não é garantia, e o invariante é explícito

O QUE ESTA POLÍTICA NÃO PODE FAZER, e a ausência é verificada por guarda:

    amostrar           nada de reservoir, semente, «as primeiras dez mil
                       linhas», recorte por temporada. EXATO significa que
                       todo candidato semanticamente elegível foi examinado
    filtrar por time   estado esportivo se compara pelo estado, e não pela
                       identidade de quem o produziu
    filtrar por placar vencedor, gol seguinte, classificação, resultado final.
                       Nada disso pode decidir QUEM é candidato — seria
                       escolher os vizinhos pela resposta
    cair para outra liga uma competição com poucos candidatos devolve poucos
                       candidatos. Ausência é informação, e completar o top-K
                       com outra liga produz um K cheio e falso
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.retrieval.timepoint import TimeAlignmentPolicy
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

#: O algoritmo da impressão da política.
CANDIDATE_POLICY_FINGERPRINT_ALGORITHM: Final[str] = "candidate-universe-policy-sha256-v1"

#: O nome da política de produção da V1.
SAME_COMPETITION_REFERENCE_EXACT_TIMEPOINT_V1: Final[str] = (
    "SAME_COMPETITION_REFERENCE_EXACT_TIMEPOINT_V1"
)


@final
class CompetitionScope(StrEnum):
    """O alcance competitivo do universo. Catálogo FECHADO.

    `CROSS_COMPETITION` ESTÁ AQUI PARA SER RECUSADO, e não para ser usado — a
    mesma decisão do `NormalizationScope.GLOBAL` no PR-05.1. Nomeá-lo é o que
    permite recusá-lo com mensagem, em vez de não ter como expressá-lo.
    """

    SAME_COMPETITION = "SAME_COMPETITION"
    CROSS_COMPETITION = "CROSS_COMPETITION"


@final
class SameMatchPolicy(StrEnum):
    """O que fazer com um candidato da própria partida da query."""

    EXCLUDE = "EXCLUDE"


@final
class SourceVersionPolicy(StrEnum):
    """De qual versão normalizada os candidatos podem vir.

    UMA SÓ, E A MESMA DA QUERY. Duas versões podem ter planos, conjuntos de
    artefatos ou codificações diferentes; comparar números entre elas é
    comparar centímetros com polegadas (ADR-0040).
    """

    SAME_NORMALIZED_DATASET_VERSION = "SAME_NORMALIZED_DATASET_VERSION"


@final
class CandidateSampling(StrEnum):
    """Como o universo é amostrado. `NONE` é o único membro, e é o ponto.

    O CATÁLOGO EXISTE COM UM MEMBRO SÓ porque a amostragem é a forma mais
    natural de um oráculo exato deixar de ser exato — e um campo ausente não
    poderia ser conferido por guarda nem entrar na impressão.
    """

    NONE = "NONE"


@final
class IneligibilityReason(StrEnum):
    """Por que um candidato do universo não recebeu distância. FECHADO.

    A SEPARAÇÃO ENTRE «FORA DO UNIVERSO» E «DENTRO E NÃO COMPARÁVEL» é o que
    torna a atrição mensurável (§73). Um candidato de outra competição nunca
    foi candidato; um da competição certa sem um eixo do perfil É candidato, e
    a contagem dele é evidência para o PR-06.2.
    """

    #: Faltou pelo menos um eixo do perfil resolvido — na query ou nele.
    #: Este é o motivo do CASO COMPLETO (PR-06.1).
    INCOMPLETE_PROFILE = "INCOMPLETE_PROFILE"
    #: A interseção com a query não alcança o piso de evidência (PR-06.2).
    #: Ele é o irmão afrouxado de `INCOMPLETE_PROFILE`: o candidato tem eixos
    #: em comum, e não TANTOS quanto a política exige para que a comparação
    #: signifique alguma coisa.
    INSUFFICIENT_SHARED_COVERAGE = "INSUFFICIENT_SHARED_COVERAGE"
    #: O PR-06.3 ACRESCENTOU TRÊS, e eles são de TRAJETÓRIA. Um par pode ter
    #: eixos de sobra e movimento de menos, e as três causas são diferentes:
    #: a interseção não alcança o piso EFETIVO de células `max(8, ceil(3n/5))`;
    INSUFFICIENT_SHARED_TRAJECTORY_CELLS = "INSUFFICIENT_SHARED_TRAJECTORY_CELLS"
    #: o par não alcança dois horizontes — o começo do período, e não a feature;
    INSUFFICIENT_SHARED_HORIZONS = "INSUFFICIENT_SHARED_HORIZONS"
    #: os horizontes existem, e nenhum tem eixos bastante para ser evidencial.
    INSUFFICIENT_PER_HORIZON_COVERAGE = "INSUFFICIENT_PER_HORIZON_COVERAGE"
    #: Mesma partida da query. Fail-closed, ainda que a divisão já o impeça.
    SAME_MATCH = "SAME_MATCH"
    #: A linha declara uma representação diferente da da query.
    REPRESENTATION_MISMATCH = "REPRESENTATION_MISMATCH"

    @property
    def is_structural(self) -> bool:
        """Se ela indica defeito, e não ausência de dado.

        OS CINCO MOTIVOS DE COBERTURA SÃO NORMAIS — eles medem ausência de
        dado, e são o produto científico da atrição. Os três de trajetória
        entram nessa lista pelo mesmo argumento que o irmão de estado: um
        candidato no começo do período não é um defeito de dataset, é um
        candidato com pouca história. As outras duas são estruturais: elas não
        deveriam acontecer num dataset íntegro, e contá-las junto esconderia
        isso.
        """
        return self not in (
            IneligibilityReason.INCOMPLETE_PROFILE,
            IneligibilityReason.INSUFFICIENT_SHARED_COVERAGE,
            IneligibilityReason.INSUFFICIENT_SHARED_TRAJECTORY_CELLS,
            IneligibilityReason.INSUFFICIENT_SHARED_HORIZONS,
            IneligibilityReason.INSUFFICIENT_PER_HORIZON_COVERAGE,
        )


@final
@dataclass(frozen=True, slots=True)
class CandidateUniversePolicy:
    """As regras que decidem quem é candidato. Imutável e impressa.

    ELA NÃO CONHECE A QUERY. A política é a REGRA; o universo que ela produz
    para uma query específica é o `CandidateUniverseDescriptor`. Misturar os
    dois faria a impressão da regra mudar a cada consulta.
    """

    name: str = SAME_COMPETITION_REFERENCE_EXACT_TIMEPOINT_V1
    version: int = 1
    query_split: DatasetSplit = DatasetSplit.EVALUATION
    candidate_split: DatasetSplit = DatasetSplit.REFERENCE
    competition_scope: CompetitionScope = CompetitionScope.SAME_COMPETITION
    time_alignment: TimeAlignmentPolicy = TimeAlignmentPolicy.EXACT_MATCH_TIME_POINT
    same_match_policy: SameMatchPolicy = SameMatchPolicy.EXCLUDE
    source_version_policy: SourceVersionPolicy = SourceVersionPolicy.SAME_NORMALIZED_DATASET_VERSION
    candidate_sampling: CandidateSampling = CandidateSampling.NONE
    #: `None` É O VALOR, e não «ilimitado por engano»: um teto de candidatos
    #: truncaria o universo antes das distâncias, e o resultado deixaria de ser
    #: o top-K verdadeiro sem que nada no objeto denunciasse.
    candidate_cap: None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("política de universo sem nome")
        if self.version < 1:
            raise ValidationError(f"versão de política inválida: {self.version}")
        if self.query_split is self.candidate_split:
            raise ValidationError(
                f"query e candidatos na mesma metade ({self.query_split.value}): a "
                "divisão existe para avaliar sobre partidas que não calibraram a "
                "escala, e uma política que as junta a torna decorativa",
                context={"split": self.query_split.value},
            )
        if self.candidate_split is not DatasetSplit.REFERENCE:
            raise ValidationError(
                f"candidatos vindos de {self.candidate_split.value}: o PR-05.5.2 "
                "provou que o conjunto de artefatos é função da REFERÊNCIA, e um "
                "candidato de avaliação seria comparado sob uma escala que ele "
                "ajudou a definir (ADR-0039)",
                context={"candidate_split": self.candidate_split.value},
            )
        if self.competition_scope is CompetitionScope.CROSS_COMPETITION:
            raise ValidationError(
                "universo com escopo CROSS_COMPETITION: a escala é ajustada POR "
                "competição (ADR-0035), e cruzar ligas compara números normalizados "
                "por medianas diferentes — o resultado é plausível e não significa "
                "nada",
                context={"scope": self.competition_scope.value},
            )
        if self.candidate_sampling is not CandidateSampling.NONE:
            raise ValidationError(
                f"universo com amostragem {self.candidate_sampling.value}: EXATO "
                "significa que todo candidato elegível foi examinado, e uma amostra "
                "produz um top-K que ninguém consegue reproduzir"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def excludes_same_match(self) -> bool:
        return self.same_match_policy is SameMatchPolicy.EXCLUDE

    @property
    def identity(self) -> str:
        return f"{self.name}@{self.version}"

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        """A forma que a impressão cobre — as regras, e nenhuma execução."""
        return {
            "algorithm": CANDIDATE_POLICY_FINGERPRINT_ALGORITHM,
            "candidate_cap": self.candidate_cap,
            "candidate_sampling": self.candidate_sampling.value,
            "candidate_split": self.candidate_split.value,
            "competition_scope": self.competition_scope.value,
            "name": self.name,
            "query_split": self.query_split.value,
            "same_match_policy": self.same_match_policy.value,
            "source_version_policy": self.source_version_policy.value,
            "time_alignment": self.time_alignment.value,
            "version": self.version,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        return f"{self.identity} [{self.fingerprint[:12]}]"


#: A política de produção da V1.
DEFAULT_CANDIDATE_POLICY: Final[CandidateUniversePolicy] = CandidateUniversePolicy()
