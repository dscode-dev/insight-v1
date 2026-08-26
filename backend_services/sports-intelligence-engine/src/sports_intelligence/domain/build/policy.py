"""A política de construção canônica — versionada, e o ÚNICO lugar que decide.

O QUE ELA DECIDE, e nenhum construtor decide:

    quais avaliações entram                  §17
    quais famílias são obrigatórias          uma delas fora → a partida não entra
    quais são opcionais                      podem faltar sem derrubar o núcleo
    quais podem ser descartadas por licença  a saída do §19
    o que fazer com `REVIEW_REQUIRED`        §11, §85
    o que fazer com conflito opcional        §46
    para que escopo se constrói              pesquisa ou comércio

POR QUE ELA NÃO REAVALIA QUALIDADE (§5). O veredito já foi produzido pela
`HistoricalQualityPolicy`, com evidência, versão e execução gravadas.
Recalculá-lo aqui criaria uma segunda opinião sobre a mesma pergunta — e duas
implementações da mesma regra divergem no primeiro ajuste, com a divergência
aparecendo como um fato canônico construído sob critério que ninguém declarou.

Então esta política LÊ `MatchQualityRecord` e escreve `BuildDecision`. Ela
nunca olha um `QualityVector`, nunca compara um piso, nunca pesa um problema.

A MESMA AVALIAÇÃO SOB DUAS POLÍTICAS PRODUZ CORPUS DIFERENTES (§18, §86), e
isso é o esperado: pesquisa inclui odds `RESEARCH_ONLY`, comércio as exclui.
A identidade da partida é a mesma nos dois.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.build.decisions import (
    BUILDABLE_FAMILIES,
    BuildDecision,
    BuildOutcome,
    CanonicalFactType,
    FamilyDecision,
    FamilyExclusionReason,
)
from sports_intelligence.domain.quality.assessment import BuildEligibility
from sports_intelligence.domain.quality.coverage import (
    FAMILY_ORDER,
    CoverageFamily,
    CoverageState,
)
from sports_intelligence.domain.quality.issues import IssueCode
from sports_intelligence.domain.quality.licensing import (
    LicenseFootprint,
    UsageEligibility,
    UsageScope,
)
from sports_intelligence.domain.quality.policy import DEFAULT_QUALITY_POLICY
from sports_intelligence.domain.quality.runs import MatchQualityRecord
from sports_intelligence.domain.resolution.versions import PolicyVersion
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.provenance import LicenseClass

#: A versão que este PR entrega. Sobe quando qualquer regra abaixo muda — e
#: subir é o que permite duas execuções sobre a MESMA avaliação coexistirem
#: com resultados diferentes e explicáveis (§18, §52).
CURRENT_BUILD_POLICY_VERSION: Final[PolicyVersion] = PolicyVersion(major=1, minor=0)

#: O ator de serviço da construção. Nomeado pelo que ele É (§75).
CANONICAL_BUILDER: Final[str] = "historical-canonical-builder"

#: A ordem de restrição das licenças, da mais restritiva para a mais livre.
#: Serve para RELATAR qual licença causou a exclusão quando uma família teve
#: contribuição de várias — e a mais restritiva é a que de fato causou.
_RESTRICAO: Final[tuple[LicenseClass, ...]] = (
    LicenseClass.UNKNOWN,
    LicenseClass.RESEARCH_ONLY,
    LicenseClass.ATTRIBUTION_REQUIRED,
    LicenseClass.COMMERCIAL_ALLOWED,
    LicenseClass.PUBLIC_DOMAIN,
)


class ReviewHandling(StrEnum):
    """O que fazer com uma partida que a qualidade mandou revisar (§11)."""

    #: Não constrói nada. O default, e é o §85: `REVIEW_REQUIRED` fica fora do
    #: build automático até uma decisão humana.
    NEVER_BUILD = "NEVER_BUILD"
    #: Constrói só o núcleo obrigatório e deixa as opcionais de fora. Para
    #: corpus de pesquisa onde o núcleo é útil e o resto pode esperar.
    BUILD_CORE_ONLY = "BUILD_CORE_ONLY"


class OptionalConflictHandling(StrEnum):
    """O que fazer com conflito não resolvido em família OPCIONAL (§46)."""

    #: A família fica de fora, com motivo. A partida continua entrando.
    EXCLUDE_FAMILY = "EXCLUDE_FAMILY"
    #: A família vai para revisão. A partida continua entrando.
    REVIEW_FAMILY = "REVIEW_FAMILY"


@final
@dataclass(frozen=True, slots=True)
class CanonicalBuildPolicy:
    """As regras de UM build canônico. Imutável e versionada."""

    version: PolicyVersion
    scope: UsageScope

    #: Sem UMA delas, a partida NÃO entra. É o núcleo do corpus.
    required_families: frozenset[CoverageFamily] = field(default_factory=frozenset)
    #: Podem faltar sem derrubar nada. É o §14 e o §39 escritos na política:
    #: uma escalação ausente reduz o que se pode fazer com a partida e não a
    #: torna falsa.
    optional_families: frozenset[CoverageFamily] = field(default_factory=frozenset)
    #: As que este build tem PERMISSÃO de descartar para contornar licença
    #: restritiva (§20). Vazio significa «nenhuma»: descartar dado restrito
    #: para conseguir publicar é uma permissão declarada, nunca um recurso que
    #: o motor usa por conta própria.
    license_droppable_families: frozenset[CoverageFamily] = field(default_factory=frozenset)

    on_review_required: ReviewHandling = ReviewHandling.NEVER_BUILD
    on_optional_conflict: OptionalConflictHandling = OptionalConflictHandling.EXCLUDE_FAMILY

    #: Se uma partida pode entrar no corpus SEM resultado (§33). `False` para
    #: um corpus de resultados; `True` para um de calendário e contexto.
    require_result: bool = True

    def __post_init__(self) -> None:
        if not self.required_families:
            raise ValidationError(
                "política de build sem família obrigatória: ela construiria uma "
                "partida sem nenhum dado, e um registro vazio no corpus é pior que "
                "um registro ausente"
            )
        sobrepostas = self.required_families & self.optional_families
        if sobrepostas:
            raise ValidationError(
                f"famílias declaradas obrigatórias E opcionais: "
                f"{sorted(f.value for f in sobrepostas)} — a política não decidiria "
                "o que fazer quando elas faltassem"
            )
        nao_construiveis = (self.required_families | self.optional_families) - BUILDABLE_FAMILIES
        if nao_construiveis:
            raise ValidationError(
                f"a política exige famílias que o contrato fundido desta fase não "
                f"carrega: {sorted(f.value for f in nao_construiveis)}. Aceitá-las "
                "produziria um corpus em que a ausência delas parece falha da fonte "
                "em vez de limite do nosso contrato (§28, §92)",
                context={"buildable": sorted(f.value for f in BUILDABLE_FAMILIES)},
            )
        obrigatoria_descartavel = self.required_families & self.license_droppable_families
        if obrigatoria_descartavel:
            raise ValidationError(
                f"família obrigatória marcada como descartável por licença: "
                f"{sorted(f.value for f in obrigatoria_descartavel)}. Descartá-la "
                "deixaria a partida sem o que a torna uma partida"
            )

    # ------------------------------------------------------------ decisão --

    def decide(self, record: MatchQualityRecord) -> BuildDecision:
        """A decisão de build de uma partida. TODA a regra mora aqui.

        A ORDEM DAS GUARDAS É A ORDEM DA GRAVIDADE, como na avaliação: a
        primeira que dispara vira `reason`, então a causa raiz precisa vir
        antes do sintoma.
        """
        avaliacao = record.assessment

        if avaliacao.eligibility is BuildEligibility.INELIGIBLE:
            return self._recusa(
                record,
                outcome=BuildOutcome.SKIP,
                reason_family=FamilyExclusionReason.ASSESSMENT_INELIGIBLE,
                reason=f"qualidade INELIGIBLE: {avaliacao.reason or 'sem detalhe'}",
            )

        if avaliacao.eligibility is BuildEligibility.REVIEW_REQUIRED:
            if self.on_review_required is ReviewHandling.NEVER_BUILD:
                return self._recusa(
                    record,
                    outcome=BuildOutcome.REVIEW_REQUIRED,
                    reason_family=FamilyExclusionReason.ASSESSMENT_REVIEW,
                    reason=(f"qualidade REVIEW_REQUIRED: {avaliacao.reason or 'sem detalhe'}"),
                )
            return self._decidir_familias(record, apenas_obrigatorias=True)

        return self._decidir_familias(record, apenas_obrigatorias=False)

    def _recusa(
        self,
        record: MatchQualityRecord,
        *,
        outcome: BuildOutcome,
        reason_family: FamilyExclusionReason,
        reason: str,
    ) -> BuildDecision:
        """A partida inteira fica de fora — e cada família diz por quê.

        AS FAMÍLIAS APARECEM MESMO ASSIM, e não é redundância: sem elas, uma
        partida recusada teria zero linhas de decisão, e a pergunta «o que
        aconteceu com as odds desta partida» não teria resposta nenhuma.
        """
        destino = (
            FamilyDecision.needs_review
            if outcome is BuildOutcome.REVIEW_REQUIRED
            else FamilyDecision.excluded
        )
        return BuildDecision.of(
            match_id=record.match_id,
            outcome=outcome,
            scope=self.scope,
            build_policy_version=self.version,
            families=tuple(
                destino(familia, reason_family) for familia in self._familias_consideradas(record)
            ),
            reason=reason,
        )

    def _decidir_familias(
        self, record: MatchQualityRecord, *, apenas_obrigatorias: bool
    ) -> BuildDecision:
        decisoes: list[FamilyDecision] = []
        bloqueio: str | None = None

        for familia in self._familias_consideradas(record):
            obrigatoria = familia in self.required_families
            considerada = obrigatoria or (
                familia in self.optional_families and not apenas_obrigatorias
            )

            if not considerada:
                decisoes.append(
                    FamilyDecision.excluded(
                        familia,
                        FamilyExclusionReason.ASSESSMENT_REVIEW
                        if apenas_obrigatorias and familia in self.optional_families
                        else FamilyExclusionReason.OUT_OF_BUILD_SCOPE,
                    )
                )
                continue

            decisao, motivo_de_bloqueio = self._decidir_uma(
                record, familia, obrigatoria=obrigatoria
            )
            decisoes.append(decisao)
            if motivo_de_bloqueio is not None and bloqueio is None:
                bloqueio = motivo_de_bloqueio

        if bloqueio is None and self.require_result and _sem_resultado(record):
            bloqueio = (
                "esta política exige resultado e a partida não tem placar — "
                "construir sem ele produziria um corpus de resultados com buracos "
                "que ninguém distingue de empates sem gol (§44)"
            )

        if bloqueio is not None:
            # AS DECISÕES INDIVIDUAIS SOBREVIVEM AO BLOQUEIO, e as que iam
            # entrar viram `MATCH_NOT_BUILT`. Trocar todas por um motivo único
            # apagaria a informação mais útil da linha — qual família de fato
            # falhou e por quê — justamente no caso em que alguém vai procurar.
            return BuildDecision.of(
                match_id=record.match_id,
                outcome=BuildOutcome.SKIP,
                scope=self.scope,
                build_policy_version=self.version,
                families=tuple(
                    FamilyDecision.excluded(d.family, FamilyExclusionReason.MATCH_NOT_BUILT)
                    if d.outcome.materializes
                    else d
                    for d in decisoes
                ),
                reason=bloqueio,
            )

        return BuildDecision.of(
            match_id=record.match_id,
            outcome=BuildOutcome.BUILD,
            scope=self.scope,
            build_policy_version=self.version,
            families=tuple(decisoes),
        )

    def _decidir_uma(
        self, record: MatchQualityRecord, familia: CoverageFamily, *, obrigatoria: bool
    ) -> tuple[FamilyDecision, str | None]:
        """O destino de UMA família, e o motivo de bloqueio se ela for
        obrigatória e não puder entrar.

        A ORDEM DAS PERGUNTAS IMPORTA. Disponibilidade primeiro: perguntar da
        licença de uma família que a fonte não trouxe produziria «excluída por
        licença» sobre dado que nunca existiu — e alguém iria procurar um
        contrato para resolver um problema que não é de contrato.
        """
        if not _disponivel(record, familia):
            return (
                FamilyDecision.excluded(familia, FamilyExclusionReason.NOT_AVAILABLE),
                f"{familia} é obrigatória e a fonte não a trouxe" if obrigatoria else None,
            )

        veredito, licenca = self._licenca_de(record.assessment.usage.footprint, familia)
        if veredito is not UsageEligibility.ELIGIBLE:
            if familia in self.license_droppable_families:
                return (
                    FamilyDecision.excluded(
                        familia,
                        FamilyExclusionReason.LICENSE_POLICY,
                        license_class=licenca,
                    ),
                    None,
                )
            return (
                FamilyDecision.excluded(
                    familia,
                    FamilyExclusionReason.LICENSE_POLICY,
                    license_class=licenca,
                ),
                f"{familia} é {licenca} e este build é {self.scope}; a política não "
                "autoriza descartá-la, e usá-la seria publicar dado sem direito",
            )

        if familia in record.families_unresolved_identity:
            return (
                FamilyDecision.excluded(familia, FamilyExclusionReason.UNRESOLVED_IDENTITY),
                f"{familia} depende de identidade não resolvida e é obrigatória"
                if obrigatoria
                else None,
            )

        if familia in record.families_in_conflict:
            if obrigatoria:
                return (
                    FamilyDecision.excluded(familia, FamilyExclusionReason.UNRESOLVED_CONFLICT),
                    f"{familia} é obrigatória e as fontes divergem sem resolução — "
                    "escolher uma seria inventar o fato (§45)",
                )
            if self.on_optional_conflict is OptionalConflictHandling.REVIEW_FAMILY:
                return (
                    FamilyDecision.needs_review(familia, FamilyExclusionReason.UNRESOLVED_CONFLICT),
                    None,
                )
            return (
                FamilyDecision.excluded(familia, FamilyExclusionReason.UNRESOLVED_CONFLICT),
                None,
            )

        return FamilyDecision.included(familia), None

    def _familias_consideradas(self, record: MatchQualityRecord) -> tuple[CoverageFamily, ...]:
        """As famílias que este build precisa se pronunciar sobre.

        AS DECLARADAS PELA FONTE ENTRAM MESMO FORA DE ESCOPO, e é o §20: uma
        fonte que trouxe eventos precisa ver «EVENT excluída, fora do escopo
        desta fase» — e não o silêncio, que seria indistinguível de esquecimento.
        """
        declaradas = frozenset(record.assessment.coverage.declared_families)
        alvo = self.required_families | self.optional_families | declaradas
        return tuple(f for f in FAMILY_ORDER if f in alvo)

    def _licenca_de(
        self, footprint: LicenseFootprint, familia: CoverageFamily
    ) -> tuple[UsageEligibility, LicenseClass]:
        """O veredito de uso desta família neste escopo, e a licença culpada.

        SEM CONTRIBUIÇÃO REGISTRADA É `UNKNOWN`, e não «livre». Uma família
        de cuja origem não se sabe nada não é permissiva — é exatamente o caso
        que a `licensing` do PR-04.1 manda mandar para revisão.

        O VEREDITO VEM DE `family_verdict`, e não é recalculado aqui (§5,
        PR-04.2.1 §35). É ele que conhece o suporte independente — a diferença
        entre uma fonte restrita que DERIVOU o valor e uma que apenas o
        CONFIRMOU. Refazer a conta com `worst` neste método faria a política
        de build decidir por um critério diferente do que a avaliação gravou,
        e as duas respostas divergiriam no primeiro ajuste.

        A LICENÇA CULPADA continua sendo a mais restritiva presente: quando o
        veredito não é elegível, é ela que o operador precisa ver.
        """
        licencas = footprint.by_family.get(familia)
        if not licencas:
            return UsageEligibility.REVIEW_REQUIRED, LicenseClass.UNKNOWN
        veredito = footprint.family_verdict(familia, self.scope)
        culpada = next((lic for lic in _RESTRICAO if lic in licencas), LicenseClass.UNKNOWN)
        return veredito, culpada

    # ------------------------------------------------------------- leitura --

    def fact_types_for(self, decision: BuildDecision) -> tuple[CanonicalFactType, ...]:
        """Os tipos de fato que esta decisão manda materializar.

        `MATCH_RESULT` ACOMPANHA `MATCH` E É UM FATO À PARTE (§26, §33). A
        família de cobertura é a mesma; os fatos não são — e é exatamente essa
        distinção que impede o placar de voltar para dentro do agregado.
        """
        if not decision.outcome.materializes:
            return ()
        tipos: list[CanonicalFactType] = []
        if decision.includes(CoverageFamily.MATCH):
            tipos.append(CanonicalFactType.MATCH)
            tipos.append(CanonicalFactType.MATCH_RESULT)
        if decision.includes(CoverageFamily.LINEUP):
            tipos.append(CanonicalFactType.LINEUP)
        if decision.includes(CoverageFamily.ODDS):
            tipos.append(CanonicalFactType.ODDS_OBSERVATION)
        return tuple(tipos)

    def as_canonical(self) -> dict[str, object]:
        """A forma determinística — ela é gravada junto da execução (§18)."""
        return {
            "license_droppable_families": sorted(f.value for f in self.license_droppable_families),
            "on_optional_conflict": self.on_optional_conflict.value,
            "on_review_required": self.on_review_required.value,
            "optional_families": sorted(f.value for f in self.optional_families),
            "require_result": self.require_result,
            "required_families": sorted(f.value for f in self.required_families),
            "scope": self.scope.value,
            "version": str(self.version),
        }

    def __str__(self) -> str:
        return f"política de build v{self.version} ({self.scope})"


def _disponivel(record: MatchQualityRecord, familia: CoverageFamily) -> bool:
    """Se a fonte de fato trouxe alguma coisa desta família.

    `NOT_DECLARED` E CONTAGEM ZERO SÃO A MESMA COISA PARA O BUILD e coisas
    diferentes para o RELATÓRIO (§58) — a distinção sobrevive no assessment,
    onde ela responde «a fonte não trabalha com isso» contra «trabalha e não
    veio nada». Aqui as duas dão no mesmo: não há o que materializar.
    """
    cobertura = record.assessment.coverage.of_family(familia)
    if cobertura is None:
        return False
    if cobertura.state is CoverageState.NOT_DECLARED:
        return False
    return cobertura.available_count > 0


def _sem_resultado(record: MatchQualityRecord) -> bool:
    """Se a avaliação registrou ausência de placar.

    LÊ O PROBLEMA JÁ EMITIDO, e não reinspeciona o candidato: quem observou a
    ausência foi o avaliador, sob a política de qualidade, e reobservá-la aqui
    seria a segunda opinião que o §5 proíbe.
    """
    return any(problema.code is IssueCode.MISSING_RESULT for problema in record.assessment.issues)


#: O BUILD DE PESQUISA. Inclui tudo que a fonte trouxe, porque `RESEARCH_ONLY`
#: é elegível para pesquisa — não há nada a descartar, e por isso a lista de
#: descartáveis é vazia.
DEFAULT_RESEARCH_BUILD_POLICY: Final[CanonicalBuildPolicy] = CanonicalBuildPolicy(
    version=CURRENT_BUILD_POLICY_VERSION,
    scope=UsageScope.RESEARCH,
    required_families=frozenset({CoverageFamily.MATCH}),
    optional_families=frozenset({CoverageFamily.LINEUP, CoverageFamily.ODDS}),
    license_droppable_families=frozenset(),
    on_review_required=ReviewHandling.NEVER_BUILD,
    on_optional_conflict=OptionalConflictHandling.EXCLUDE_FAMILY,
    require_result=True,
)

#: O BUILD COMERCIAL. Idêntico ao de pesquisa em tudo, menos numa coisa: ele
#: pode DESCARTAR as famílias que a política de QUALIDADE já declarou
#: descartáveis.
#:
#: A LISTA VEM DE LÁ E NÃO É REESCRITA AQUI (§5). Duas listas de famílias
#: descartáveis divergiriam no primeiro ajuste, e a divergência significaria
#: publicar comercialmente uma família que a política de qualidade considerava
#: restrita — o defeito mais caro deste PR, porque é jurídico e silencioso.
DEFAULT_COMMERCIAL_BUILD_POLICY: Final[CanonicalBuildPolicy] = CanonicalBuildPolicy(
    version=CURRENT_BUILD_POLICY_VERSION,
    scope=UsageScope.COMMERCIAL,
    required_families=frozenset({CoverageFamily.MATCH}),
    optional_families=frozenset({CoverageFamily.LINEUP, CoverageFamily.ODDS}),
    license_droppable_families=DEFAULT_QUALITY_POLICY.commercially_droppable,
    on_review_required=ReviewHandling.NEVER_BUILD,
    on_optional_conflict=OptionalConflictHandling.EXCLUDE_FAMILY,
    require_result=True,
)
