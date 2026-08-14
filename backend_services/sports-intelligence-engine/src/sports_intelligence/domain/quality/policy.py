"""A política de qualidade histórica — versionada, e o único lugar com números.

POR QUE OS LIMIARES NÃO MORAM NOS VALIDADORES (§23). Um `if confianca < 0.9`
dentro de um verificador é uma decisão de negócio escondida num laço: para
mudá-la é preciso encontrá-la, para auditá-la é preciso ler código, e para
saber sob qual valor uma avaliação de seis meses atrás rodou não há resposta
nenhuma.

Aqui os números estão num objeto, o objeto tem versão, e a versão fica gravada
na execução (§24). «Este registro reprovou» passa a ter a continuação «sob a
política 1.0, que exigia identidade acima de 0,90» — e reprocessar sob a 1.1
produz uma execução NOVA, ao lado da anterior, que continua intacta.

O QUE A POLÍTICA DECIDE, e nenhum outro lugar decide:

    severidade de cada código de problema
    quais eixos de qualidade são críticos
    o piso de cada eixo crítico
    o piso de confiança por tipo de identidade
    se linhagem completa é exigida
    quais famílias podem ser excluídas de um build comercial

O QUE ELA NÃO DECIDE: o que os validadores acham. Achar é observação; pesar é
política. Misturar os dois foi o defeito que o PR-03.1 encontrou na resolução,
e não vale a pena repeti-lo aqui.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, final

from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.quality.dimensions import QualityDimension
from sports_intelligence.domain.quality.issues import IssueCode, Severity
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.versions import PolicyVersion
from sports_intelligence.domain.shared.errors import ValidationError

#: A versão que este PR entrega. Sobe quando qualquer número abaixo muda —
#: e subir é o que permite comparar duas avaliações da mesma entrada.
CURRENT_QUALITY_POLICY_VERSION: Final[PolicyVersion] = PolicyVersion(major=1, minor=0)


@final
@dataclass(frozen=True, slots=True)
class HistoricalQualityPolicy:
    """Os pesos e pisos de uma avaliação histórica. Imutável e versionada."""

    version: PolicyVersion

    #: Severidade por código. O que NÃO estiver aqui é `WARNING` — um default
    #: brando de propósito: um código novo não pode passar a bloquear o corpus
    #: por acidente de omissão, e um `WARNING` inesperado aparece no relatório
    #: sem parar a linha.
    severities: dict[IssueCode, Severity] = field(default_factory=dict)

    #: Os eixos que governam a elegibilidade. Os demais são REPORTADOS e não
    #: reprovam — é o que impede completude baixa (que é cobertura disfarçada)
    #: de derrubar um registro de identidade e linhagem perfeitas (§29).
    critical_dimensions: frozenset[QualityDimension] = field(default_factory=frozenset)

    #: O piso de cada eixo crítico. Ausente = sem piso.
    minimums: dict[QualityDimension, float] = field(default_factory=dict)

    #: O piso de confiança POR TIPO DE IDENTIDADE (§9). Um número só faria a
    #: confiança de competição — que é quase sempre 1,0 por vir de catálogo
    #: fechado — mascarar a de jogador, que é a que contamina o futuro.
    identity_minimums: dict[SubjectType, float] = field(default_factory=dict)

    #: Se um fato sem linhagem completa até o byte bruto pode ser promovido.
    require_complete_lineage: bool = True

    #: As famílias que um build comercial pode DESCARTAR para contornar uma
    #: licença restritiva (§36). Vazio significa «nenhuma»: a exclusão é uma
    #: permissão declarada, nunca um recurso que o motor usa por conta.
    commercially_droppable: frozenset[CoverageFamily] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        for dimensao, piso in self.minimums.items():
            if not 0.0 <= piso <= 1.0:
                raise ValidationError(f"piso de {dimensao} = {piso!r} fora de [0,1]")
            if dimensao not in self.critical_dimensions:
                raise ValidationError(
                    f"{dimensao} tem piso {piso} e não é crítica — um piso que não "
                    "reprova é um número que engana quem lê a política"
                )
        for sujeito, piso in self.identity_minimums.items():
            if not 0.0 <= piso <= 1.0:
                raise ValidationError(f"piso de identidade {sujeito} = {piso!r} inválido")
        if not self.critical_dimensions:
            raise ValidationError(
                "política sem eixo crítico: ela não conseguiria reprovar nada, e uma "
                "avaliação que nunca reprova não avalia"
            )

    def severity_of(self, code: IssueCode) -> Severity:
        """A severidade de um código sob ESTA política."""
        return self.severities.get(code, Severity.WARNING)

    def minimum_for(self, dimension: QualityDimension) -> float | None:
        return self.minimums.get(dimension)

    def identity_minimum_for(self, subject: SubjectType) -> float | None:
        return self.identity_minimums.get(subject)

    def as_canonical(self) -> dict[str, object]:
        """A forma determinística — ela entra na impressão do manifesto."""
        return {
            "commercially_droppable": sorted(
                f.value for f in self.commercially_droppable
            ),
            "critical_dimensions": sorted(d.value for d in self.critical_dimensions),
            "identity_minimums": {
                s.value: round(v, 6)
                for s, v in sorted(self.identity_minimums.items(), key=lambda p: p[0].value)
            },
            "minimums": {
                d.value: round(v, 6)
                for d, v in sorted(self.minimums.items(), key=lambda p: p[0].value)
            },
            "require_complete_lineage": self.require_complete_lineage,
            "severities": {
                c.value: s.name
                for c, s in sorted(self.severities.items(), key=lambda p: p[0].value)
            },
            "version": str(self.version),
        }

    def __str__(self) -> str:
        return f"política de qualidade v{self.version}"


#: A política que este PR entrega. Cada número é uma escolha de RISCO, e cada
#: uma tem o motivo escrito ao lado.
DEFAULT_QUALITY_POLICY: Final[HistoricalQualityPolicy] = HistoricalQualityPolicy(
    version=CURRENT_QUALITY_POLICY_VERSION,
    severities={
        # BLOQUEANTES. Cada um destes produziria um fato histórico que parece
        # verdadeiro e não é — que é o único tipo de defeito que este PR
        # existe para impedir.
        IssueCode.MISSING_REQUIRED_IDENTITY: Severity.BLOCKING,
        IssueCode.DANGLING_CANONICAL_REFERENCE: Severity.BLOCKING,
        IssueCode.SAME_TEAM_BOTH_SIDES: Severity.BLOCKING,
        IssueCode.UNRESOLVED_IDENTITY: Severity.BLOCKING,
        IssueCode.COMPETITION_SEASON_MISMATCH: Severity.BLOCKING,
        # A linhagem quebrada bloqueia porque o corpus inteiro se justifica
        # por ser rastreável: um fato que não volta ao byte bruto é uma
        # afirmação sem testemunha.
        IssueCode.BROKEN_LINEAGE: Severity.BLOCKING,
        IssueCode.MANIFEST_FINGERPRINT_MISMATCH: Severity.BLOCKING,
        # Conflito de fusão não resolvido em campo do NÚCLEO bloqueia; em
        # campo analítico, o validador nem chega a emitir — ver `assessment`.
        IssueCode.UNRESOLVED_FUSION_CONFLICT: Severity.BLOCKING,
        IssueCode.INCOMPLETE_CORE_MATCH: Severity.BLOCKING,
        # ERROS QUE NÃO BLOQUEIAM SOZINHOS. São graves, aparecem no relatório
        # e não impedem o corpus: um placar ausente reduz o que se pode fazer
        # com a partida e não a torna falsa.
        IssueCode.LOW_IDENTITY_CONFIDENCE: Severity.ERROR,
        IssueCode.TEMPORAL_INCONSISTENCY: Severity.ERROR,
        IssueCode.KICKOFF_OUTSIDE_SEASON_WINDOW: Severity.ERROR,
        IssueCode.LINEUP_TEAM_MISMATCH: Severity.ERROR,
        IssueCode.NEGATIVE_OBSERVED_VALUE: Severity.ERROR,
        IssueCode.TENURE_NOT_VALID_AT_DATE: Severity.ERROR,
        IssueCode.EVENT_OUT_OF_ORDER: Severity.WARNING,
        IssueCode.MISSING_RESULT: Severity.WARNING,
        IssueCode.INVALID_SEASON_REFERENCE: Severity.ERROR,
        # LICENÇA NÃO É QUALIDADE (§30) e por isso não bloqueia AQUI. Quem
        # decide o que fazer com ela é a elegibilidade de uso, que roda ao
        # lado e produz veredito próprio.
        IssueCode.LICENSE_RESTRICTED: Severity.INFO,
        IssueCode.LICENSE_UNKNOWN: Severity.WARNING,
    },
    # QUATRO DOS SEIS SÃO CRÍTICOS. Ficam de fora `completeness` — que é
    # cobertura sob outro nome e não deve reprovar (§29) — e
    # `temporal_integrity`, que é grave, entra como `ERROR` e raramente
    # justifica descartar um fato inteiro.
    critical_dimensions=frozenset(
        {
            QualityDimension.INTEGRITY,
            QualityDimension.CONSISTENCY,
            QualityDimension.IDENTITY_CONFIDENCE,
            QualityDimension.PROVENANCE_QUALITY,
        }
    ),
    minimums={
        QualityDimension.INTEGRITY: 1.0,
        QualityDimension.CONSISTENCY: 0.95,
        QualityDimension.IDENTITY_CONFIDENCE: 0.90,
        QualityDimension.PROVENANCE_QUALITY: 1.0,
    },
    identity_minimums={
        # Catálogo fechado: ou casa exato, ou não é uma das cinco.
        SubjectType.COMPETITION: 1.0,
        SubjectType.SEASON: 0.95,
        SubjectType.TEAM: 0.92,
        SubjectType.MATCH: 0.90,
        # O MAIS ALTO, e é o mesmo 0,96 do resolver: um `PlayerId` errado
        # contamina influência, força de elenco e grafo tático de forma que
        # não se detecta depois, porque tudo continua somando.
        SubjectType.PLAYER: 0.96,
    },
    require_complete_lineage=True,
    # ODDS SÃO DESCARTÁVEIS NUM BUILD COMERCIAL, e é a exclusão que torna o
    # §36 possível: uma fonte `RESEARCH_ONLY` que só trouxe cotações não
    # precisa condenar o núcleo da partida.
    commercially_droppable=frozenset({CoverageFamily.ODDS}),
)
