"""Elegibilidade de uso — que NÃO é qualidade (§30).

A DISTINÇÃO QUE ESTE MÓDULO EXISTE PARA IMPOR. Uma fonte pode ser
tecnicamente impecável — identidades provadas, linhagem completa, zero
conflitos — e ainda assim ser `RESEARCH_ONLY`. Nada nela está errado; ela
simplesmente não pode alimentar um produto comercial.

Misturar as duas coisas erra nos dois sentidos, e os dois são caros:

    licença tratada como qualidade    uma fonte perfeita vira «ruim», e
                                      alguém vai «corrigir» isso
    qualidade tratada como licença    um corpus comercial recebe dado que
                                      ninguém tinha direito de usar

Por isso a elegibilidade é um eixo próprio, com política própria, e o
resultado é um par: `research` e `commercial` decididos separadamente.

A LICENÇA VEM DO CONJUNTO DAS CONTRIBUIÇÕES, não da fonte que venceu mais
campos (§35). Um candidato construído com A (domínio público), B (atribuição)
e C (pesquisa) foi produzido usando as três — e usar a mais permissiva porque
ela contribuiu mais seria contornar a restrição pelo caminho de trás.

MAS A CONTAMINAÇÃO NÃO É IRREVERSÍVEL (§36). Se a fonte restrita contribuiu
apenas com odds, e o build comercial exclui odds, o núcleo da partida não foi
produzido com ela. É por isso que a decisão recebe as licenças POR FAMÍLIA e
não uma licença só: excluir a família restrita é uma saída legítima, e sem a
granularidade ela seria impossível de expressar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.provenance import LicenseClass


class UsageScope(StrEnum):
    """Para que o corpus pode ser usado. Dois escopos, decididos à parte."""

    RESEARCH = "RESEARCH"
    COMMERCIAL = "COMMERCIAL"


class UsageEligibility(StrEnum):
    """O veredito por escopo.

    TRÊS E NÃO UM BOOLEANO, pelo mesmo motivo de tudo neste motor: «não sei»
    é uma resposta diferente de «não pode», e tratá-las igual esconde o caso
    que precisa de gente — que é justamente o `UNKNOWN` do §34.
    """

    ELIGIBLE = "ELIGIBLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INELIGIBLE = "INELIGIBLE"


#: O que cada licença permite, por escopo. TABELA E NÃO `if`s espalhados: uma
#: regra de licença escrita em três lugares diverge no primeiro ajuste, e a
#: divergência aqui significa usar dado sem direito.
#:
#: `UNKNOWN` É `REVIEW_REQUIRED` NO COMERCIAL E NÃO `INELIGIBLE` (§34):
#: bloquear de vez faria toda fonte sem licença declarada sumir do corpus sem
#: ninguém olhar; permitir seria supor permissividade. Revisão é o único
#: desfecho honesto — e ele custa uma decisão humana, que é o preço certo.
_PERMISSOES: Final[dict[LicenseClass, dict[UsageScope, UsageEligibility]]] = {
    LicenseClass.PUBLIC_DOMAIN: {
        UsageScope.RESEARCH: UsageEligibility.ELIGIBLE,
        UsageScope.COMMERCIAL: UsageEligibility.ELIGIBLE,
    },
    LicenseClass.COMMERCIAL_ALLOWED: {
        UsageScope.RESEARCH: UsageEligibility.ELIGIBLE,
        UsageScope.COMMERCIAL: UsageEligibility.ELIGIBLE,
    },
    LicenseClass.ATTRIBUTION_REQUIRED: {
        # ELEGÍVEL, E A ATRIBUIÇÃO É OBRIGAÇÃO DE QUEM PUBLICA. O motor
        # registra a exigência no manifesto; cumpri-la é do produto. Tratá-la
        # como bloqueio faria o corpus perder as melhores fontes públicas de
        # futebol, todas sob atribuição.
        UsageScope.RESEARCH: UsageEligibility.ELIGIBLE,
        UsageScope.COMMERCIAL: UsageEligibility.ELIGIBLE,
    },
    LicenseClass.RESEARCH_ONLY: {
        UsageScope.RESEARCH: UsageEligibility.ELIGIBLE,
        UsageScope.COMMERCIAL: UsageEligibility.INELIGIBLE,
    },
    LicenseClass.UNKNOWN: {
        UsageScope.RESEARCH: UsageEligibility.REVIEW_REQUIRED,
        UsageScope.COMMERCIAL: UsageEligibility.REVIEW_REQUIRED,
    },
}

#: A ordem de severidade dos vereditos. O pior governa o conjunto.
_SEVERIDADE: Final[dict[UsageEligibility, int]] = {
    UsageEligibility.ELIGIBLE: 0,
    UsageEligibility.REVIEW_REQUIRED: 1,
    UsageEligibility.INELIGIBLE: 2,
}


def eligibility_of(license_class: LicenseClass, scope: UsageScope) -> UsageEligibility:
    """O veredito de UMA licença num escopo."""
    return _PERMISSOES[license_class][scope]


def worst(vereditos: tuple[UsageEligibility, ...]) -> UsageEligibility:
    """O pior veredito do conjunto. Sem contribuição nenhuma → revisão.

    VAZIO NÃO É `ELIGIBLE`. Um candidato sem nenhuma licença registrada não é
    permissivo — é um candidato de cuja origem não se sabe nada, e isso é
    exatamente o caso do `UNKNOWN`.
    """
    if not vereditos:
        return UsageEligibility.REVIEW_REQUIRED
    return max(vereditos, key=lambda v: _SEVERIDADE[v])


@final
@dataclass(frozen=True, slots=True)
class LicenseFootprint:
    """Quais licenças alimentaram quais famílias de dado deste candidato.

    É A GRANULARIDADE QUE TORNA A EXCLUSÃO POSSÍVEL (§36). Com uma licença só
    por candidato, `RESEARCH_ONLY` em qualquer campo condenaria o registro
    inteiro; com o mapa por família, dá para perguntar «e se as odds saírem?»
    — que é a pergunta que o build comercial faz.
    """

    by_family: dict[CoverageFamily, frozenset[LicenseClass]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        for familia, licencas in self.by_family.items():
            if not licencas:
                raise ValidationError(
                    f"{familia} registrada sem nenhuma licença — uma família que "
                    "recebeu contribuição sabe de quem ela veio, e uma que não "
                    "recebeu não deveria estar no mapa"
                )

    @property
    def all_licenses(self) -> frozenset[LicenseClass]:
        return frozenset(
            licenca for licencas in self.by_family.values() for licenca in licencas
        )

    def verdict(
        self, scope: UsageScope, *, excluding: frozenset[CoverageFamily] = frozenset()
    ) -> UsageEligibility:
        """O veredito do candidato, opcionalmente sem algumas famílias.

        `excluding` É O MECANISMO DO §36, e ele é EXPLÍCITO de propósito: a
        exclusão precisa vir de uma política declarada, nunca de o motor
        decidir sozinho descartar dado restrito para conseguir publicar.
        """
        consideradas = tuple(
            licenca
            for familia, licencas in self.by_family.items()
            if familia not in excluding
            for licenca in licencas
        )
        return worst(tuple(eligibility_of(licenca, scope) for licenca in consideradas))

    def families_blocking(self, scope: UsageScope) -> tuple[CoverageFamily, ...]:
        """As famílias cuja licença impede o escopo — as candidatas a exclusão.

        Quem decide excluí-las é a política de build. Este método só diz
        QUAIS são, para que a decisão seja informada em vez de tentativa.
        """
        return tuple(
            sorted(
                (
                    familia
                    for familia, licencas in self.by_family.items()
                    if worst(tuple(eligibility_of(lic, scope) for lic in licencas))
                    is UsageEligibility.INELIGIBLE
                ),
                key=lambda f: f.value,
            )
        )

    @property
    def requires_attribution(self) -> bool:
        """Se alguma contribuição exige atribuição ao publicar."""
        return any(lic.requires_attribution for lic in self.all_licenses)

    def merged_with(self, other: LicenseFootprint) -> LicenseFootprint:
        juntas: dict[CoverageFamily, frozenset[LicenseClass]] = dict(self.by_family)
        for familia, licencas in other.by_family.items():
            juntas[familia] = juntas.get(familia, frozenset()) | licencas
        return LicenseFootprint(by_family=juntas)

    def as_canonical(self) -> dict[str, list[str]]:
        return {
            familia.value: sorted(lic.value for lic in licencas)
            for familia, licencas in sorted(
                self.by_family.items(), key=lambda p: p[0].value
            )
        }

    def __str__(self) -> str:
        return ", ".join(
            f"{f.value}={sorted(lic.value for lic in ls)}"
            for f, ls in sorted(self.by_family.items(), key=lambda p: p[0].value)
        ) or "sem licença registrada"


@final
@dataclass(frozen=True, slots=True)
class UsageVerdict:
    """O par de vereditos de um candidato, com o que sustenta cada um.

    OS DOIS ESCOPOS JUNTOS porque a pergunta operacional é sempre «entra em
    qual corpus?», e responder um de cada vez faria o chamador recompor o par
    — e recompor é onde se erra.
    """

    research: UsageEligibility
    commercial: UsageEligibility
    footprint: LicenseFootprint
    #: As famílias que precisariam sair para o comercial passar. Vazio quando
    #: ele já passa, ou quando excluí-las não resolveria.
    commercial_blockers: tuple[CoverageFamily, ...] = ()

    @classmethod
    def of(
        cls,
        footprint: LicenseFootprint,
        *,
        commercial_exclusions: frozenset[CoverageFamily] = frozenset(),
    ) -> Self:
        return cls(
            research=footprint.verdict(UsageScope.RESEARCH),
            commercial=footprint.verdict(
                UsageScope.COMMERCIAL, excluding=commercial_exclusions
            ),
            footprint=footprint,
            commercial_blockers=footprint.families_blocking(UsageScope.COMMERCIAL),
        )

    def allows(self, scope: UsageScope) -> bool:
        veredito = self.research if scope is UsageScope.RESEARCH else self.commercial
        return veredito is UsageEligibility.ELIGIBLE

    def as_canonical(self) -> dict[str, object]:
        return {
            "commercial": self.commercial.value,
            "commercial_blockers": [f.value for f in self.commercial_blockers],
            "footprint": self.footprint.as_canonical(),
            "requires_attribution": self.footprint.requires_attribution,
            "research": self.research.value,
        }

    def __str__(self) -> str:
        return f"pesquisa {self.research} · comercial {self.commercial}"
