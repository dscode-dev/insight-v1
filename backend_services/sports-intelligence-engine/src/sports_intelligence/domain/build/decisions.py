"""O que a política de build decidiu — por partida e por família.

EXCLUSÃO NÃO É DESAPARECIMENTO (§20). Uma família descartada por licença
precisa deixar rastro com o motivo e a licença que o causou; sem isso, a
diferença entre «a fonte não trouxe odds» e «tínhamos odds e não podíamos
publicá-las» some — e as duas exigem ações opostas de quem opera o corpus.

Por isso `FamilyDecision` carrega motivo obrigatório sempre que o desfecho
não é `INCLUDED`, e a licença sempre que o motivo é licença. O tipo recusa
uma exclusão sem explicação.

O DESFECHO DA PARTIDA NÃO É BOOLEANO, pelo mesmo motivo de tudo neste motor:
`REVIEW_REQUIRED` é o meio-termo entre construir e descartar, e ele precisa
existir para que uma partida com problema sério e não bloqueante fique FORA
do build automático sem sumir da fila (§85).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.quality.coverage import FAMILY_ORDER, CoverageFamily
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.resolution.versions import PolicyVersion
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.provenance import LicenseClass


class CanonicalFactType(StrEnum):
    """Que tipo de fato canônico um registro de construção descreve.

    SEPARADO DA FAMÍLIA DE COBERTURA de propósito. `MATCH` é uma família de
    dado; `Match` e `MatchResult` são dois FATOS distintos dentro dela — e a
    distinção é a decisão central do PR-01, que este enum não pode apagar
    (§26, §31, §32).
    """

    MATCH = "MATCH"
    MATCH_RESULT = "MATCH_RESULT"
    LINEUP = "LINEUP"
    MATCH_EVENT = "MATCH_EVENT"
    ODDS_OBSERVATION = "ODDS_OBSERVATION"


class FamilyOutcome(StrEnum):
    """O que aconteceu com uma família de dado neste build."""

    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    #: Havia dado e ele não é decidível sozinho. Fica fora do automático e
    #: nomeado — que é a diferença entre «descartamos» e «alguém precisa ver».
    REVIEW_REQUIRED = "REVIEW_REQUIRED"

    @property
    def materializes(self) -> bool:
        return self is FamilyOutcome.INCLUDED


class FamilyExclusionReason(StrEnum):
    """Por que uma família ficou de fora. Catálogo fechado, como os problemas.

    TEXTO LIVRE AQUI SERIA O MESMO ERRO DO §12: dez formas de escrever
    «licença» na mesma coluna, e a consulta que pergunta «quanto do corpus
    perdemos por licença» encontrando um terço.
    """

    #: A política deste build não tem direito de publicar esta família.
    LICENSE_POLICY = "LICENSE_POLICY"
    #: A fonte não trouxe. NÃO é defeito — é a cobertura dela (§44).
    NOT_AVAILABLE = "NOT_AVAILABLE"
    #: A família existe no domínio e o contrato fundido desta fase não a
    #: carrega. Declarado, e não silencioso (§28, §92).
    OUT_OF_BUILD_SCOPE = "OUT_OF_BUILD_SCOPE"
    #: Uma identidade que esta família exige não foi resolvida (§27, §40).
    UNRESOLVED_IDENTITY = "UNRESOLVED_IDENTITY"
    #: Fontes divergiram e a fusão não resolveu (§46).
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"
    #: A avaliação de qualidade mandou para revisão (§11, §85).
    ASSESSMENT_REVIEW = "ASSESSMENT_REVIEW"
    #: A avaliação de qualidade reprovou a partida inteira.
    ASSESSMENT_INELIGIBLE = "ASSESSMENT_INELIGIBLE"
    #: A família estava apta e a PARTIDA não entrou. Distinto de todos os
    #: acima: não há nada errado com esta família, e a razão de ela não ter
    #: sido materializada está em outra linha da mesma decisão.
    MATCH_NOT_BUILT = "MATCH_NOT_BUILT"


@final
@dataclass(frozen=True, slots=True)
class FamilyDecision:
    """O destino de UMA família neste build, com o porquê.

    A LICENÇA VIAJA JUNTO quando ela é a causa, e é o que torna o §19
    auditável: «ODDS excluída» não responde nada; «ODDS excluída por
    LICENSE_POLICY, RESEARCH_ONLY, num build COMMERCIAL» responde tudo.
    """

    family: CoverageFamily
    outcome: FamilyOutcome
    reason: FamilyExclusionReason | None = None
    #: A licença que causou a exclusão, quando o motivo é licença.
    license_class: LicenseClass | None = None

    def __post_init__(self) -> None:
        if self.outcome is FamilyOutcome.INCLUDED and self.reason is not None:
            raise ValidationError(
                f"{self.family} incluída com motivo {self.reason} — um motivo aqui "
                "seria lido como se a família tivesse ficado de fora"
            )
        if self.outcome is not FamilyOutcome.INCLUDED and self.reason is None:
            raise ValidationError(
                f"{self.family} em {self.outcome} sem motivo: uma família que some "
                "sem explicação é indistinguível de uma que nunca existiu (§20)"
            )
        if (
            self.reason is FamilyExclusionReason.LICENSE_POLICY
            and self.license_class is None
        ):
            raise ValidationError(
                f"{self.family} excluída por licença e sem dizer QUAL — a exclusão "
                "por licença é a que mais precisa de resposta numa auditoria"
            )
        if (
            self.license_class is not None
            and self.reason is not FamilyExclusionReason.LICENSE_POLICY
        ):
            raise ValidationError(
                f"{self.family} carrega licença com motivo {self.reason}: a licença "
                "aqui afirmaria uma causa que não foi a causa"
            )

    @classmethod
    def included(cls, family: CoverageFamily) -> Self:
        return cls(family=family, outcome=FamilyOutcome.INCLUDED)

    @classmethod
    def excluded(
        cls,
        family: CoverageFamily,
        reason: FamilyExclusionReason,
        *,
        license_class: LicenseClass | None = None,
    ) -> Self:
        return cls(
            family=family,
            outcome=FamilyOutcome.EXCLUDED,
            reason=reason,
            license_class=license_class,
        )

    @classmethod
    def needs_review(cls, family: CoverageFamily, reason: FamilyExclusionReason) -> Self:
        return cls(
            family=family, outcome=FamilyOutcome.REVIEW_REQUIRED, reason=reason
        )

    def as_canonical(self) -> dict[str, str | None]:
        return {
            "family": self.family.value,
            "license_class": self.license_class.value if self.license_class else None,
            "outcome": self.outcome.value,
            "reason": self.reason.value if self.reason else None,
        }

    def __str__(self) -> str:
        if self.outcome is FamilyOutcome.INCLUDED:
            return f"{self.family} incluída"
        licenca = f" ({self.license_class})" if self.license_class else ""
        return f"{self.family} {self.outcome} por {self.reason}{licenca}"


class BuildOutcome(StrEnum):
    """O destino da PARTIDA neste build."""

    BUILD = "BUILD"
    SKIP = "SKIP"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"

    @property
    def materializes(self) -> bool:
        """Só `BUILD` produz fato canônico. `REVIEW_REQUIRED` fica fora do
        automático até alguém olhar — que é o §85 inteiro."""
        return self is BuildOutcome.BUILD


@final
@dataclass(frozen=True, slots=True)
class BuildDecision:
    """A decisão de build de uma partida. Produzida SÓ pela política.

    ELA É O ÚNICO CONTRATO ENTRE QUALIDADE E CONSTRUÇÃO (§5). O construtor
    recebe isto e não recebe a política: assim não há caminho de código em que
    ele reavalie elegibilidade por conta própria, que é a duplicação de regra
    que este PR existe para não cometer.
    """

    match_id: MatchId
    outcome: BuildOutcome
    scope: UsageScope
    build_policy_version: PolicyVersion
    families: tuple[FamilyDecision, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        nomes = [f.family for f in self.families]
        if len(set(nomes)) != len(nomes):
            repetidas = sorted({n.value for n in nomes if nomes.count(n) > 1})
            raise ValidationError(
                f"família decidida duas vezes na mesma partida: {repetidas}"
            )
        if self.outcome is not BuildOutcome.BUILD and any(
            f.outcome.materializes for f in self.families
        ):
            incluidas = sorted(
                f.family.value for f in self.families if f.outcome.materializes
            )
            raise ValidationError(
                f"partida em {self.outcome} com família(s) incluída(s): {incluidas}. "
                "Uma partida que não entra no corpus não pode ter família materializada "
                "— seria um fato canônico sem partida a que pertencer"
            )
        if self.outcome is not BuildOutcome.BUILD and not (self.reason or "").strip():
            raise ValidationError(
                f"partida em {self.outcome} sem motivo: «por que esta partida não "
                "entrou» precisa ter resposta sem depurar (§50)"
            )

    @classmethod
    def of(
        cls,
        *,
        match_id: MatchId,
        outcome: BuildOutcome,
        scope: UsageScope,
        build_policy_version: PolicyVersion,
        families: tuple[FamilyDecision, ...] = (),
        reason: str | None = None,
    ) -> Self:
        """Constrói com as famílias em ORDEM CANÔNICA.

        A ordem entra na impressão determinística do build (§54), e a de
        chamada é a de iteração de um conjunto — que não é ordem nenhuma.
        """
        por_familia = {f.family: f for f in families}
        return cls(
            match_id=match_id,
            outcome=outcome,
            scope=scope,
            build_policy_version=build_policy_version,
            families=tuple(por_familia[f] for f in FAMILY_ORDER if f in por_familia),
            reason=reason,
        )

    def decision_for(self, family: CoverageFamily) -> FamilyDecision | None:
        return next((f for f in self.families if f.family is family), None)

    def includes(self, family: CoverageFamily) -> bool:
        """Se esta família deve ser materializada. Falso quando não decidida.

        NÃO DECIDIDA É NÃO INCLUÍDA, e o default seguro é deliberado: uma
        família que a política esqueceu de mencionar não pode entrar no corpus
        por omissão.
        """
        decisao = self.decision_for(family)
        return decisao is not None and decisao.outcome.materializes

    @property
    def included_families(self) -> tuple[CoverageFamily, ...]:
        return tuple(f.family for f in self.families if f.outcome.materializes)

    @property
    def excluded_families(self) -> tuple[CoverageFamily, ...]:
        return tuple(f.family for f in self.families if not f.outcome.materializes)

    @property
    def excluded_by_license(self) -> tuple[CoverageFamily, ...]:
        """As famílias que a LICENÇA tirou — a resposta do §19 e do §103."""
        return tuple(
            f.family
            for f in self.families
            if f.reason is FamilyExclusionReason.LICENSE_POLICY
        )

    def as_canonical(self) -> dict[str, object]:
        return {
            "build_policy_version": str(self.build_policy_version),
            "families": [f.as_canonical() for f in self.families],
            "match_id": str(self.match_id),
            "outcome": self.outcome.value,
            "reason": self.reason,
            "scope": self.scope.value,
        }

    def __str__(self) -> str:
        return f"{self.match_id} · {self.outcome}" + (
            f" ({self.reason})" if self.reason else ""
        )


#: As famílias que a V1 do contrato fundido sabe materializar. `EVENT`,
#: `SPATIAL` e `TRACKING` ficam de fora porque NÃO HÁ papel semântico que as
#: carregue — nem no mapeamento de fonte, nem na saída da fusão (§28, §92).
#:
#: DECLARADO AQUI E NÃO INVENTADO LÁ. A alternativa seria um construtor de
#: eventos que nunca recebe evento nenhum, e um relatório de cobertura em que
#: `EVENT = 0%` pareceria falha da fonte em vez de limite do nosso contrato.
BUILDABLE_FAMILIES: Final[frozenset[CoverageFamily]] = frozenset(
    {CoverageFamily.MATCH, CoverageFamily.LINEUP, CoverageFamily.ODDS}
)
