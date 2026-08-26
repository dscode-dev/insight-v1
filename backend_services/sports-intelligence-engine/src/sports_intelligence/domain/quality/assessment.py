"""A avaliação de UMA partida — onde qualidade, cobertura e licença se juntam.

POR QUE POR PARTIDA E NÃO POR DATASET (§26). Um corpus 99% bom e 1% corrompido
avaliado só no agregado promove o 1% junto — e o 1% corrompido é exatamente o
que vira um fato histórico errado que ninguém detecta, porque tudo continua
somando. A granularidade mínima é a entidade canônica que será promovida.

TRÊS ENTRADAS INDEPENDENTES, UM VEREDITO:

    QualityVector    posso confiar no que está aqui?
    CoverageReport   o que está aqui?          → NÃO reprova (§29)
    UsageVerdict     tenho direito de usar?    → veredito PRÓPRIO (§30)

A elegibilidade de BUILD é a combinação das duas primeiras com os problemas
encontrados. A de USO fica ao lado, sem se misturar: um registro pode ser
tecnicamente elegível e comercialmente inelegível, e as duas afirmações são
verdadeiras ao mesmo tempo.

`ELIGIBLE` NÃO É BOOLEANO (§27). `REVIEW_REQUIRED` é o desfecho de quem tem
problema sério e não bloqueante — e ele precisa ficar FORA do build automático
até alguém olhar (§38). Com um booleano, esse caso viraria `False` e sumiria
da fila, ou `True` e entraria sem revisão. Os dois estão errados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Self, final

from sports_intelligence.domain.quality.coverage import CoverageReport
from sports_intelligence.domain.quality.dimensions import QualityDimension, QualityVector
from sports_intelligence.domain.quality.issues import (
    QualityIssue,
    Severity,
    sorted_issues,
)
from sports_intelligence.domain.quality.licensing import UsageScope, UsageVerdict
from sports_intelligence.domain.quality.policy import HistoricalQualityPolicy
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.shared.identity import MatchId


class BuildEligibility(StrEnum):
    """Se este registro pode entrar no corpus, e como."""

    ELIGIBLE = "ELIGIBLE"
    #: Problema sério que não bloqueia. FICA DE FORA do build automático até
    #: decisão humana — é o meio-termo que um booleano não expressa.
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INELIGIBLE = "INELIGIBLE"

    @property
    def enters_build(self) -> bool:
        """Só `ELIGIBLE` entra sozinho (§38)."""
        return self is BuildEligibility.ELIGIBLE


@final
@dataclass(frozen=True, slots=True)
class IdentityConfidences:
    """A confiança POR TIPO de identidade desta partida (§9).

    NÃO É UMA MÉDIA, e é a diferença que importa: uma competição em 1,0 e um
    jogador em 0,4 dão média 0,7, que passa em quase qualquer piso — e o
    jogador errado é o que contamina o futuro. Cada tipo é conferido contra o
    piso DELE.

    Os valores vêm das `ResolutionDecision` já produzidas e NÃO são
    recalibrados aqui (§9): recalibrar seria inventar uma segunda opinião
    sobre uma decisão que já tem evidência e versão gravadas.
    """

    by_subject: dict[SubjectType, float] = field(default_factory=dict)

    def weakest_against(
        self, policy: HistoricalQualityPolicy
    ) -> tuple[SubjectType, float, float] | None:
        """O tipo que mais fica abaixo do piso dele, ou `None` se todos passam.

        A MARGEM É O CRITÉRIO, e não o valor absoluto: um jogador em 0,94 com
        piso 0,96 está mais em falta que uma temporada em 0,93 com piso 0,95,
        embora 0,93 seja o número menor.
        """
        faltas = [
            (sujeito, valor, piso)
            for sujeito, valor in self.by_subject.items()
            if (piso := policy.identity_minimum_for(sujeito)) is not None and valor < piso
        ]
        if not faltas:
            return None
        return min(faltas, key=lambda f: (f[1] - f[2], f[0].value))

    @property
    def aggregate(self) -> float:
        """O ELO MAIS FRACO, para preencher o eixo do vetor de qualidade (§83).

        Mínimo e não média — a mesma decisão do PR-00, pela mesma razão: média
        deixa um eixo em 0,4 ser mascarado por quatro em 0,95.
        """
        return min(self.by_subject.values(), default=0.0)

    def as_canonical(self) -> dict[str, float]:
        return {
            s.value: round(v, 6)
            for s, v in sorted(self.by_subject.items(), key=lambda p: p[0].value)
        }


@final
@dataclass(frozen=True, slots=True)
class MatchQualityAssessment:
    """O veredito de uma partida candidata. Imutável.

    ELA NÃO CONSTRÓI NADA. Avaliar e construir são etapas separadas, e a
    separação é o que permite reavaliar sob política nova sem reconstruir, e
    reconstruir sob política de build nova sem reavaliar.
    """

    match_id: MatchId
    quality: QualityVector
    coverage: CoverageReport
    identity: IdentityConfidences
    usage: UsageVerdict
    issues: tuple[QualityIssue, ...] = ()
    eligibility: BuildEligibility = BuildEligibility.INELIGIBLE
    #: O que decidiu o veredito, em texto legível. Existe para o operador —
    #: «por que esta partida não entrou» precisa ter resposta sem depurar.
    reason: str | None = None

    @classmethod
    def evaluate(
        cls,
        *,
        match_id: MatchId,
        quality: QualityVector,
        coverage: CoverageReport,
        identity: IdentityConfidences,
        usage: UsageVerdict,
        issues: tuple[QualityIssue, ...],
        policy: HistoricalQualityPolicy,
    ) -> Self:
        """Aplica a política sobre as observações. TODA a decisão mora aqui.

        A ORDEM DAS GUARDAS É A ORDEM DA GRAVIDADE, e ela importa: a primeira
        que dispara é a que vira `reason`, então a mais séria precisa vir
        primeiro para que o operador leia a causa raiz e não um sintoma.
        """
        ordenados = sorted_issues(issues)

        # 1. BLOQUEANTE — nada mais precisa ser conferido.
        bloqueantes = [i for i in ordenados if policy.severity_of(i.code).blocks]
        if bloqueantes:
            return cls(
                match_id=match_id,
                quality=quality,
                coverage=coverage,
                identity=identity,
                usage=usage,
                issues=ordenados,
                eligibility=BuildEligibility.INELIGIBLE,
                reason=f"{len(bloqueantes)} problema(s) bloqueante(s): {bloqueantes[0].code}",
            )

        # 2. PISO DE EIXO CRÍTICO. Elo mais fraco entre os CRÍTICOS — os
        # demais são reportados e não reprovam (§29).
        for dimensao in sorted(policy.critical_dimensions, key=lambda d: d.value):
            piso = policy.minimum_for(dimensao)
            if piso is not None and quality[dimensao] < piso:
                return cls(
                    match_id=match_id,
                    quality=quality,
                    coverage=coverage,
                    identity=identity,
                    usage=usage,
                    issues=ordenados,
                    eligibility=BuildEligibility.INELIGIBLE,
                    reason=f"{dimensao} em {quality[dimensao]:.2f}, abaixo do piso {piso:.2f}",
                )

        # 3. PISO DE IDENTIDADE, POR TIPO. Nunca pela média.
        falta = identity.weakest_against(policy)
        if falta is not None:
            sujeito, valor, piso = falta
            return cls(
                match_id=match_id,
                quality=quality,
                coverage=coverage,
                identity=identity,
                usage=usage,
                issues=ordenados,
                eligibility=BuildEligibility.REVIEW_REQUIRED,
                reason=f"identidade de {sujeito} em {valor:.2f}, abaixo do piso "
                f"{piso:.2f} — pode ser decidida por revisão",
            )

        # 4. USO EM REVISÃO. Licença desconhecida não reprova a qualidade e
        # não deixa promover em silêncio (§34).
        if usage.research is not usage.research.ELIGIBLE:
            return cls(
                match_id=match_id,
                quality=quality,
                coverage=coverage,
                identity=identity,
                usage=usage,
                issues=ordenados,
                eligibility=BuildEligibility.REVIEW_REQUIRED,
                reason=f"elegibilidade de uso para pesquisa: {usage.research}",
            )

        # 5. ERROS NÃO BLOQUEANTES vão para revisão. Não reprovam sozinhos e
        # não entram sem alguém ver.
        graves = [i for i in ordenados if policy.severity_of(i.code) >= Severity.ERROR]
        if graves:
            return cls(
                match_id=match_id,
                quality=quality,
                coverage=coverage,
                identity=identity,
                usage=usage,
                issues=ordenados,
                eligibility=BuildEligibility.REVIEW_REQUIRED,
                reason=f"{len(graves)} problema(s) grave(s): {graves[0].code}",
            )

        # COBERTURA NUNCA CHEGA A SER CONFERIDA AQUI, e é deliberado: ela não
        # reprova (§85). `eventos = 0%` reduz o que se pode construir sobre o
        # corpus e não torna a partida falsa.
        return cls(
            match_id=match_id,
            quality=quality,
            coverage=coverage,
            identity=identity,
            usage=usage,
            issues=ordenados,
            eligibility=BuildEligibility.ELIGIBLE,
            reason=None,
        )

    def allows(self, scope: UsageScope) -> bool:
        """Se este registro entra num corpus daquele escopo.

        AS DUAS CONDIÇÕES, E NÃO UMA: elegível para build **e** com direito de
        uso. Um registro tecnicamente impecável sob licença de pesquisa não
        entra no corpus comercial, e um registro de licença livre com
        identidade duvidosa não entra em corpus nenhum.
        """
        return self.eligibility.enters_build and self.usage.allows(scope)

    def as_canonical(self) -> dict[str, object]:
        return {
            "coverage": self.coverage.as_canonical(),
            "eligibility": self.eligibility.value,
            "identity": self.identity.as_canonical(),
            "issues": [i.as_canonical() for i in self.issues],
            "match_id": str(self.match_id),
            "quality": self.quality.as_canonical(),
            "reason": self.reason,
            "usage": self.usage.as_canonical(),
        }

    def __str__(self) -> str:
        return f"{self.match_id} · {self.eligibility}" + (
            f" ({self.reason})" if self.reason else ""
        )


def summarize(
    assessments: tuple[MatchQualityAssessment, ...],
) -> dict[BuildEligibility, int]:
    """Quantas partidas em cada veredito. A linha de topo do relatório."""
    contagem = dict.fromkeys(BuildEligibility, 0)
    for avaliacao in assessments:
        contagem[avaliacao.eligibility] += 1
    return contagem


def aggregate_quality(
    assessments: tuple[MatchQualityAssessment, ...],
) -> QualityVector | None:
    """O vetor do conjunto, eixo a eixo, pelo PIOR caso (§83).

    `None` quando não há avaliação — e não um vetor perfeito: um corpus vazio
    não é um corpus impecável.

    MÍNIMO POR EIXO E NÃO MÉDIA, pelo mesmo motivo de sempre. Uma média sobre
    dez mil partidas faria cem partidas de linhagem quebrada desaparecerem no
    terceiro decimal — e são justamente elas que precisam aparecer.
    """
    if not assessments:
        return None
    piores = {
        dimensao: min(a.quality[dimensao] for a in assessments) for dimensao in QualityDimension
    }
    return QualityVector(
        integrity=piores[QualityDimension.INTEGRITY],
        consistency=piores[QualityDimension.CONSISTENCY],
        completeness=piores[QualityDimension.COMPLETENESS],
        identity_confidence=piores[QualityDimension.IDENTITY_CONFIDENCE],
        temporal_integrity=piores[QualityDimension.TEMPORAL_INTEGRITY],
        provenance_quality=piores[QualityDimension.PROVENANCE_QUALITY],
    )
