"""Quão bom é o dado — em quatro eixos que não se somam sozinhos.

POR QUE QUATRO E NÃO UM. Um score único responde "confio?" e não responde
"o que faço a respeito?", que é a pergunta operacional. Os quatro eixos pedem
ações diferentes:

    completeness        faltam campos           → buscar outra fonte
    consistency         os campos se contradizem → revisar a fonte
    freshness           o dado envelheceu        → esperar/atualizar
    identity_confidence não sei de quem é        → resolver identidade

A FÓRMULA DE AGREGAÇÃO NÃO ESTÁ AQUI, e é deliberado: qualquer peso escolhido
agora seria um palpite fixado antes de existir dado para calibrá-lo. O que
existe é o contrato — os quatro eixos, a faixa [0,1], e a exigência de que
qualquer agregação futura seja explícita e versionada.

MÍNIMO E NÃO MÉDIA, no `overall` provisório. Média deixa um eixo em 0,1 ser
mascarado por três em 0,9, e um dado de identidade duvidosa não fica bom por
estar completo. O elo mais fraco é o que governa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Self, final


class QualityIssue(StrEnum):
    """O que especificamente está errado. Nomes, não um score."""

    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    CONTRADICTORY_SOURCES = "CONTRADICTORY_SOURCES"
    OUT_OF_RANGE_VALUE = "OUT_OF_RANGE_VALUE"
    STALE_OBSERVATION = "STALE_OBSERVATION"
    AMBIGUOUS_ENTITY = "AMBIGUOUS_ENTITY"
    UNRESOLVED_ENTITY = "UNRESOLVED_ENTITY"
    TIMESTAMP_INCONSISTENCY = "TIMESTAMP_INCONSISTENCY"
    DUPLICATE_RECORD = "DUPLICATE_RECORD"


def _unit(name: str, value: float) -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} deve estar em [0,1], recebeu {value!r}")
    return float(value)


@final
@dataclass(frozen=True, slots=True)
class DataQuality:
    """Os quatro eixos, mais o que especificamente falhou."""

    completeness: float
    consistency: float
    freshness: float
    identity_confidence: float
    issues: frozenset[QualityIssue] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        for nome in ("completeness", "consistency", "freshness", "identity_confidence"):
            _unit(nome, getattr(self, nome))

    @property
    def overall(self) -> float:
        """O elo mais fraco.

        PROVISÓRIO E DECLARADO COMO TAL. Quando houver dado para calibrar uma
        agregação de verdade, ela entra como `QualityModelVersion` própria e
        este mínimo sai. Enquanto isso, o mínimo é a escolha conservadora: ele
        nunca faz um dado ruim parecer bom.
        """
        return min(
            self.completeness, self.consistency, self.freshness, self.identity_confidence
        )

    @property
    def is_usable(self) -> bool:
        """Se este dado pode alimentar cálculo.

        O limiar mora aqui e não espalhado em `if score > 0.5` por toda parte:
        um número mágico repetido em cinco lugares é cinco políticas que
        divergem na primeira vez que alguém ajusta uma.
        """
        return self.overall >= USABILITY_THRESHOLD and not self.issues & BLOCKING_ISSUES

    @classmethod
    def perfect(cls) -> Self:
        """Tudo em 1,0. Só para dado nascido internamente e já validado —
        usá-lo em dado de provedor é afirmar o que não foi medido."""
        return cls(
            completeness=1.0, consistency=1.0, freshness=1.0, identity_confidence=1.0
        )

    def with_issue(self, issue: QualityIssue) -> Self:
        return type(self)(
            completeness=self.completeness,
            consistency=self.consistency,
            freshness=self.freshness,
            identity_confidence=self.identity_confidence,
            issues=self.issues | {issue},
        )


#: Abaixo disto o dado não entra em cálculo. Um só lugar, por isso acima.
USABILITY_THRESHOLD: float = 0.5

#: Problemas que reprovam independentemente do score. Identidade não resolvida
#: não é "qualidade baixa" — é não saber de quem é o dado, e nenhum score alto
#: nos outros eixos compensa isso.
BLOCKING_ISSUES: frozenset[QualityIssue] = frozenset(
    {
        QualityIssue.UNRESOLVED_ENTITY,
        QualityIssue.DUPLICATE_RECORD,
    }
)
