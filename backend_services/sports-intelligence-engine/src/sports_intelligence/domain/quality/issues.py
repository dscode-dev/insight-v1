"""O que especificamente está errado — em códigos, nunca em texto livre.

POR QUE CÓDIGO E NÃO MENSAGEM (§21). Uma string livre é legível uma vez e
inútil depois: não dá para contar, não dá para agrupar por tipo, não dá para
uma política dizer «este é bloqueante» sem casar substring. O catálogo fechado
transforma «o dado está ruim» em «trinta e sete registros com
`LOW_IDENTITY_CONFIDENCE`», que é a diferença entre uma reclamação e uma
tarefa.

A SEVERIDADE NÃO MORA AQUI (§22). O mesmo código é bloqueante num corpus
comercial e informativo num corpus de pesquisa — e se cada validador
carimbasse a própria severidade, mudar essa decisão exigiria caçá-la por todo
o código. O validador diz O QUE ACHOU; a política diz QUANTO ISSO PESA.

Por isso `QualityIssue` carrega código, dimensão afetada e contexto — e
`Severity` só aparece quando a política já entrou na conversa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.quality.dimensions import QualityDimension
from sports_intelligence.domain.shared.errors import ValidationError

#: Teto do contexto de um problema. Um `dict` sem limite vindo de dado de fora
#: vira vetor de memória — a mesma guarda do relatório de validação do PR-02.
MAX_CONTEXT_KEYS: Final[int] = 12
MAX_CONTEXT_VALUE_LENGTH: Final[int] = 200


class IssueCode(StrEnum):
    """O catálogo fechado. Acrescentar um item é uma decisão, não um `f-string`."""

    # ---- integridade: as referências apontam para coisas que existem
    MISSING_REQUIRED_IDENTITY = "MISSING_REQUIRED_IDENTITY"
    DANGLING_CANONICAL_REFERENCE = "DANGLING_CANONICAL_REFERENCE"
    BROKEN_LINEAGE = "BROKEN_LINEAGE"
    MANIFEST_FINGERPRINT_MISMATCH = "MANIFEST_FINGERPRINT_MISMATCH"

    # ---- consistência: os fatos não se contradizem
    SAME_TEAM_BOTH_SIDES = "SAME_TEAM_BOTH_SIDES"
    INVALID_SEASON_REFERENCE = "INVALID_SEASON_REFERENCE"
    COMPETITION_SEASON_MISMATCH = "COMPETITION_SEASON_MISMATCH"
    NEGATIVE_OBSERVED_VALUE = "NEGATIVE_OBSERVED_VALUE"
    LINEUP_TEAM_MISMATCH = "LINEUP_TEAM_MISMATCH"

    # ---- completude do núcleo
    INCOMPLETE_CORE_MATCH = "INCOMPLETE_CORE_MATCH"
    MISSING_RESULT = "MISSING_RESULT"

    # ---- identidade
    LOW_IDENTITY_CONFIDENCE = "LOW_IDENTITY_CONFIDENCE"
    UNRESOLVED_IDENTITY = "UNRESOLVED_IDENTITY"

    # ---- tempo
    TEMPORAL_INCONSISTENCY = "TEMPORAL_INCONSISTENCY"
    KICKOFF_OUTSIDE_SEASON_WINDOW = "KICKOFF_OUTSIDE_SEASON_WINDOW"
    EVENT_OUT_OF_ORDER = "EVENT_OUT_OF_ORDER"
    TENURE_NOT_VALID_AT_DATE = "TENURE_NOT_VALID_AT_DATE"

    # ---- fusão herdada
    UNRESOLVED_FUSION_CONFLICT = "UNRESOLVED_FUSION_CONFLICT"

    # ---- licença. ESTÁ AQUI E NÃO É QUALIDADE — ver `licensing.py`. O código
    # existe para que o problema apareça no mesmo relatório do operador; a
    # DIMENSÃO afetada é `None`, e é assim que o tipo diz que não é qualidade.
    LICENSE_RESTRICTED = "LICENSE_RESTRICTED"
    LICENSE_UNKNOWN = "LICENSE_UNKNOWN"


#: Que eixo de qualidade cada código afeta. `None` significa «não é qualidade»
#: — hoje só as licenças, e é justamente a distinção do §30 escrita no tipo.
DIMENSION_OF: Final[dict[IssueCode, QualityDimension | None]] = {
    IssueCode.MISSING_REQUIRED_IDENTITY: QualityDimension.INTEGRITY,
    IssueCode.DANGLING_CANONICAL_REFERENCE: QualityDimension.INTEGRITY,
    IssueCode.BROKEN_LINEAGE: QualityDimension.PROVENANCE_QUALITY,
    IssueCode.MANIFEST_FINGERPRINT_MISMATCH: QualityDimension.PROVENANCE_QUALITY,
    IssueCode.SAME_TEAM_BOTH_SIDES: QualityDimension.CONSISTENCY,
    IssueCode.INVALID_SEASON_REFERENCE: QualityDimension.CONSISTENCY,
    IssueCode.COMPETITION_SEASON_MISMATCH: QualityDimension.CONSISTENCY,
    IssueCode.NEGATIVE_OBSERVED_VALUE: QualityDimension.CONSISTENCY,
    IssueCode.LINEUP_TEAM_MISMATCH: QualityDimension.CONSISTENCY,
    IssueCode.INCOMPLETE_CORE_MATCH: QualityDimension.COMPLETENESS,
    IssueCode.MISSING_RESULT: QualityDimension.COMPLETENESS,
    IssueCode.LOW_IDENTITY_CONFIDENCE: QualityDimension.IDENTITY_CONFIDENCE,
    IssueCode.UNRESOLVED_IDENTITY: QualityDimension.IDENTITY_CONFIDENCE,
    IssueCode.TEMPORAL_INCONSISTENCY: QualityDimension.TEMPORAL_INTEGRITY,
    IssueCode.KICKOFF_OUTSIDE_SEASON_WINDOW: QualityDimension.TEMPORAL_INTEGRITY,
    IssueCode.EVENT_OUT_OF_ORDER: QualityDimension.TEMPORAL_INTEGRITY,
    IssueCode.TENURE_NOT_VALID_AT_DATE: QualityDimension.TEMPORAL_INTEGRITY,
    IssueCode.UNRESOLVED_FUSION_CONFLICT: QualityDimension.CONSISTENCY,
    IssueCode.LICENSE_RESTRICTED: None,
    IssueCode.LICENSE_UNKNOWN: None,
}


class Severity(IntEnum):
    """Quanto o problema pesa. ATRIBUÍDA PELA POLÍTICA, nunca pelo validador.

    `IntEnum` PARA QUE `max()` FUNCIONE. A severidade de um conjunto é a do
    pior item, e uma comparação explícita em cada ponto de uso divergiria.

    SÓ `BLOCKING` IMPEDE. `ERROR` é grave e não impede sozinho: um corpus que
    parasse no primeiro erro nunca seria construído, e a decisão de quanto
    erro é tolerável é da política — que é onde ela pode ser lida.
    """

    INFO = 10
    WARNING = 20
    ERROR = 30
    BLOCKING = 40

    @property
    def blocks(self) -> bool:
        return self is Severity.BLOCKING


@final
@dataclass(frozen=True, slots=True)
class QualityIssue:
    """Um problema encontrado, com onde e com o quê — sem severidade.

    A AUSÊNCIA DE `severity` AQUI É O PONTO (§22). Um validador que
    carimbasse severidade estaria tomando uma decisão de política dentro de um
    laço de verificação, e mudá-la exigiria reencontrá-la.
    """

    code: IssueCode
    #: O que exatamente falhou — `record_ref`, id da entidade, nome do campo.
    subject: str
    context: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValidationError(
                f"{self.code} sem sujeito: um problema que não diz sobre o que é não permite agir"
            )
        if len(self.context) > MAX_CONTEXT_KEYS:
            raise ValidationError(
                f"{self.code}: contexto com {len(self.context)} chaves, acima de {MAX_CONTEXT_KEYS}"
            )
        for chave, valor in self.context.items():
            if len(valor) > MAX_CONTEXT_VALUE_LENGTH:
                raise ValidationError(
                    f"{self.code}: contexto {chave!r} com {len(valor)} caracteres"
                )

    @property
    def dimension(self) -> QualityDimension | None:
        """O eixo afetado, ou `None` quando o problema não é de qualidade."""
        return DIMENSION_OF[self.code]

    @property
    def is_quality(self) -> bool:
        return self.dimension is not None

    @classmethod
    def of(cls, code: IssueCode, subject: str, **context: str) -> Self:
        return cls(code=code, subject=subject, context=dict(context))

    def as_canonical(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "context": dict(sorted(self.context.items())),
            "dimension": self.dimension.value if self.dimension else None,
            "subject": self.subject,
        }

    def __str__(self) -> str:
        return f"{self.code} em {self.subject}"


def sorted_issues(issues: tuple[QualityIssue, ...]) -> tuple[QualityIssue, ...]:
    """Ordem estável, porque a lista entra na impressão do manifesto (§102).

    Por código e depois por sujeito: dois problemas do mesmo tipo em registros
    diferentes precisam sair sempre na mesma ordem, senão duas execuções
    idênticas produziriam impressões diferentes.
    """
    return tuple(sorted(issues, key=lambda i: (i.code.value, i.subject)))
