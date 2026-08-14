"""A EXECUÇÃO da avaliação de qualidade — e por que ela não é um relatório.

O QUE PR-04.1 ENTREGOU foi o VEREDITO: `MatchQualityAssessment` diz se uma
partida pode entrar no corpus, sob uma política com número de versão. O que
faltava é o que torna esse veredito utilizável meses depois:

    sobre QUAIS entradas ele foi produzido    fusão concluída e sua impressão
    sob QUAL versão de política                gravada, não inferida
    QUANDO, e por quem                         instante e ator de serviço
    e quantas partidas caíram em cada estado   contagem, não amostra

Sem isso, «esta partida reprovou» é uma frase sem contexto: não dá para saber
se ela reprovaria hoje, nem o que mudou entre duas avaliações.

UMA EXECUÇÃO CONCLUÍDA É IMUTÁVEL (ADR-0019, ADR-0020, e agora ADR-0023).
Política 1.1 sobre a MESMA fusão produz uma execução NOVA, ao lado da
anterior — que fica exatamente como estava. Comparar as duas é o único jeito
honesto de medir o que a política nova passou a enxergar; se ela pudesse
reescrever a anterior, a comparação seria contra si mesma.

A ENTRADA É UMA FUSÃO CONCLUÍDA, e o tipo não basta para garanti-lo — quem
garante é `QualityRunInput`, que carrega a impressão da saída fundida. Sem
ela, «esta avaliação rodou sobre a fusão X» é uma afirmação sobre uma fusão
que pode ter sido reexecutada desde então.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Final, Self, final

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.quality.assessment import (
    BuildEligibility,
    MatchQualityAssessment,
)
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.resolution.runs import RunStatus
from sports_intelligence.domain.resolution.versions import PolicyVersion
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import Instant

#: O ator de serviço da avaliação. Identificado pelo que ELE É — nunca
#: `system`, que numa trilha de auditoria significa «não sabemos quem» (§75).
QUALITY_ASSESSOR: Final[str] = "historical-quality-assessor"


@final
@dataclass(frozen=True, slots=True)
class QualityRunInput:
    """Uma execução de fusão consumida por esta avaliação.

    A IMPRESSÃO É O QUE FECHA A LINHAGEM (§8). O id da fusão diz de onde veio;
    a impressão diz o QUE veio. Duas execuções de fusão com o mesmo id não
    existem, mas a mesma fusão pode ter sido lida antes e depois de alguém
    reprocessar a resolução — e a impressão é o que distingue os dois casos.

    `fusion_output_fingerprint` É `None` QUANDO A FUSÃO NÃO PRODUZIU NADA, e
    a ausência é honesta: uma fusão sem candidato não tem saída para imprimir,
    e um hash de vazio pareceria uma saída.
    """

    fusion_run_id: str
    fusion_output_fingerprint: ContentHash | None = None

    def __post_init__(self) -> None:
        if not self.fusion_run_id.strip():
            raise ValidationError(
                "entrada de avaliação sem execução de fusão: ela avalia o quê?"
            )

    def as_canonical(self) -> dict[str, str | None]:
        return {
            "fusion_run_id": self.fusion_run_id,
            "fusion_output_fingerprint": (
                self.fusion_output_fingerprint.value
                if self.fusion_output_fingerprint
                else None
            ),
        }

    def __str__(self) -> str:
        return f"fusão {self.fusion_run_id[:8]}"


@final
@dataclass(frozen=True, slots=True)
class QualityCounts:
    """Quantas partidas caíram em cada veredito.

    OS TRÊS SOMAM O EXAMINADO, e a conferência existe porque a alternativa é
    um painel que mostra «10.000 examinadas, 9.000 elegíveis» sem que ninguém
    saiba onde estão as mil restantes — a diferença silenciosa é exatamente
    onde um lote perdido se esconde.
    """

    records_examined: int = 0
    eligible: int = 0
    review_required: int = 0
    ineligible: int = 0

    def __post_init__(self) -> None:
        for nome, valor in (
            ("records_examined", self.records_examined),
            ("eligible", self.eligible),
            ("review_required", self.review_required),
            ("ineligible", self.ineligible),
        ):
            if valor < 0:
                raise ValidationError(f"{nome} negativo: {valor}")

    def assert_consistent(self) -> None:
        soma = self.eligible + self.review_required + self.ineligible
        if soma != self.records_examined:
            raise ValidationError(
                f"{self.records_examined} partidas examinadas e {soma} classificadas: "
                "a diferença é onde um lote se perde sem ninguém notar",
                context={"examined": self.records_examined, "classified": soma},
            )

    @classmethod
    def of(cls, assessments: tuple[MatchQualityAssessment, ...]) -> Self:
        """As contagens de um conjunto de vereditos."""
        contagem = dict.fromkeys(BuildEligibility, 0)
        for avaliacao in assessments:
            contagem[avaliacao.eligibility] += 1
        return cls(
            records_examined=len(assessments),
            eligible=contagem[BuildEligibility.ELIGIBLE],
            review_required=contagem[BuildEligibility.REVIEW_REQUIRED],
            ineligible=contagem[BuildEligibility.INELIGIBLE],
        )

    def merged_with(self, other: QualityCounts) -> QualityCounts:
        """Soma dois lotes. É como a execução acumula sem materializar tudo."""
        return QualityCounts(
            records_examined=self.records_examined + other.records_examined,
            eligible=self.eligible + other.eligible,
            review_required=self.review_required + other.review_required,
            ineligible=self.ineligible + other.ineligible,
        )

    @property
    def eligible_ratio(self) -> float | None:
        """`None` quando nada foi examinado. NUNCA zero — ver PR-02: um corpus
        vazio não tem 0% de aproveitamento, tem aproveitamento indefinido."""
        if not self.records_examined:
            return None
        return self.eligible / self.records_examined


@final
@dataclass(frozen=True, slots=True)
class MatchQualityRecord:
    """O veredito de uma partida COMO ESTA EXECUÇÃO o produziu.

    POR QUE UM ENVELOPE E NÃO CAMPOS A MAIS EM `MatchQualityAssessment`. O
    assessment é o VEREDITO — a resposta do domínio de qualidade, decidida
    pela política e nada mais. Isto aqui é o registro de uma EXECUÇÃO: em qual
    ela saiu, de qual grupo de fusão, e os dois conjuntos que a construção
    precisa e a qualidade não julga.

    Misturá-los faria o veredito carregar identificador de execução — e o
    mesmo veredito reavaliado sob política nova precisaria de outro objeto
    para dizer a mesma coisa.

    `families_in_conflict` NÃO É DEFEITO DE QUALIDADE (§46). Um conflito de
    formação entre duas fontes não torna a partida falsa; ele torna a
    ESCALAÇÃO indecidível. Quem decide o que fazer com isso é a política de
    build, e ela precisa da lista para decidir — daí ela viajar aqui em vez de
    virar um problema de qualidade que reprovaria o registro inteiro.

    `families_unresolved_identity` é o mesmo raciocínio para o §14: um jogador
    não resolvido afeta a família que depende dele, e não o núcleo da partida.
    """

    id: str
    quality_run_id: str
    #: O grupo de fusão que originou o candidato — o elo da linhagem para trás.
    fusion_group_id: str
    assessment: MatchQualityAssessment
    families_in_conflict: tuple[CoverageFamily, ...] = ()
    families_unresolved_identity: tuple[CoverageFamily, ...] = ()

    def __post_init__(self) -> None:
        if not self.quality_run_id.strip():
            raise ValidationError("registro de qualidade sem execução")
        if not self.fusion_group_id.strip():
            raise ValidationError(
                "registro de qualidade sem grupo de fusão — sem ele a linhagem para "
                "trás se rompe no primeiro elo, e o fato canônico deixa de ter "
                "caminho até o byte bruto (§47)"
            )
        for nome, familias in (
            ("families_in_conflict", self.families_in_conflict),
            ("families_unresolved_identity", self.families_unresolved_identity),
        ):
            if len(set(familias)) != len(familias):
                raise ValidationError(f"{nome} com família repetida")

    @classmethod
    def of(
        cls,
        *,
        quality_run_id: str,
        fusion_group_id: str,
        assessment: MatchQualityAssessment,
        families_in_conflict: tuple[CoverageFamily, ...] = (),
        families_unresolved_identity: tuple[CoverageFamily, ...] = (),
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            quality_run_id=quality_run_id,
            fusion_group_id=fusion_group_id,
            assessment=assessment,
            families_in_conflict=tuple(
                sorted(set(families_in_conflict), key=lambda f: f.value)
            ),
            families_unresolved_identity=tuple(
                sorted(set(families_unresolved_identity), key=lambda f: f.value)
            ),
        )

    @property
    def match_id(self) -> MatchId:
        return self.assessment.match_id

    @property
    def eligibility(self) -> BuildEligibility:
        return self.assessment.eligibility

    def as_canonical(self) -> dict[str, object]:
        """A forma determinística. NÃO inclui `id` nem `quality_run_id`: eles
        são identificadores de execução, e misturá-los na impressão faria duas
        execuções idênticas produzirem impressões diferentes (§54)."""
        return {
            "assessment": self.assessment.as_canonical(),
            "families_in_conflict": [f.value for f in self.families_in_conflict],
            "families_unresolved_identity": [
                f.value for f in self.families_unresolved_identity
            ],
            "fusion_group_id": self.fusion_group_id,
        }

    def __str__(self) -> str:
        return str(self.assessment)


@final
@dataclass(frozen=True, slots=True)
class QualityRun:
    """Uma avaliação de qualidade sobre fusões declaradas. Imutável ao fechar."""

    id: str
    inputs: tuple[QualityRunInput, ...]
    policy_version: PolicyVersion
    #: A impressão da POLÍTICA INTEIRA, e não só o número da versão. Ela é o
    #: que pega o caso em que alguém edita um limiar sem subir a versão — que
    #: é silencioso, e faz duas execuções rotuladas `1.0` decidirem diferente.
    policy_fingerprint: ContentHash
    status: RunStatus
    started_at: Instant
    triggered_by: Actor
    counts: QualityCounts = field(default_factory=QualityCounts)
    completed_at: Instant | None = None
    failure_reason: str | None = None
    #: A impressão do CONJUNTO de vereditos, quando concluída. Permite dizer
    #: «estas duas execuções decidiram a mesma coisa» sem carregar as duas.
    output_fingerprint: ContentHash | None = None

    def __post_init__(self) -> None:
        if not self.inputs:
            raise ValidationError(
                "execução de qualidade sem entrada: ela avalia a saída de qual fusão?"
            )
        vistos = [e.fusion_run_id for e in self.inputs]
        if len(set(vistos)) != len(vistos):
            raise ValidationError(
                "a mesma execução de fusão declarada duas vezes — os candidatos dela "
                "seriam avaliados em dobro e as contagens mentiriam"
            )
        if self.status.is_terminal and self.completed_at is None:
            raise ValidationError(f"execução em {self.status} sem instante de conclusão")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValidationError("execução concluída antes de começar")
        if self.status is RunStatus.FAILED and not (self.failure_reason or "").strip():
            raise ValidationError(
                "execução FAILED sem motivo: sem ele a investigação começa do zero"
            )
        self.counts.assert_consistent()

    @classmethod
    def start(
        cls,
        *,
        inputs: tuple[QualityRunInput, ...],
        policy_version: PolicyVersion,
        policy_fingerprint: ContentHash,
        at: Instant,
        triggered_by: Actor,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            inputs=inputs,
            policy_version=policy_version,
            policy_fingerprint=policy_fingerprint,
            status=RunStatus.RUNNING,
            started_at=at,
            triggered_by=triggered_by,
        )

    def complete(
        self,
        *,
        counts: QualityCounts,
        at: Instant,
        output_fingerprint: ContentHash | None = None,
    ) -> Self:
        """Fecha a execução. O status SAI DAS CONTAGENS, não de um parâmetro.

        `REVIEW_REQUIRED` LEVA A `COMPLETED_WITH_REVIEW`, e não a `COMPLETED`.
        Os dois são sucesso; a diferença é que o segundo diz «nada a fazer», e
        há partidas esperando uma decisão humana — que é justamente o estado
        que um booleano apagaria (§7).
        """
        self._assert_can_finish()
        counts.assert_consistent()
        destino = (
            RunStatus.COMPLETED_WITH_REVIEW
            if counts.review_required > 0
            else RunStatus.COMPLETED
        )
        return replace(
            self,
            status=destino,
            counts=counts,
            completed_at=at,
            output_fingerprint=output_fingerprint,
        )

    def fail(self, *, reason: str, at: Instant) -> Self:
        self._assert_can_finish()
        return replace(
            self, status=RunStatus.FAILED, completed_at=at, failure_reason=reason[:500]
        )

    def _assert_can_finish(self) -> None:
        if self.status.is_terminal:
            raise ConflictError(
                f"execução de qualidade já terminou em {self.status} — uma execução "
                "concluída é imutável; política nova produz execução nova (ADR-0023)",
                context={"run_id": self.id, "status": self.status.value},
            )

    @property
    def fusion_run_ids(self) -> tuple[str, ...]:
        return tuple(e.fusion_run_id for e in self.inputs)

    @property
    def produced_usable_output(self) -> bool:
        """Se a construção canônica pode consumir esta execução.

        `COMPLETED_WITH_REVIEW` PODE. As partidas elegíveis dela são
        construíveis; as que foram para revisão simplesmente não entram — e
        bloquear a execução inteira por causa de dez partidas ambíguas em dez
        mil pararia o corpus pelo motivo errado.
        """
        return self.status.produced_usable_output

    @property
    def duration_seconds(self) -> float | None:
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()

    def __str__(self) -> str:
        return (
            f"qualidade {self.id[:8]} [{self.status}] política {self.policy_version} · "
            f"{self.counts.eligible}/{self.counts.records_examined} elegível(is)"
        )


def assert_run_is_consumable(run: QualityRun) -> None:
    """Recusa construir sobre uma avaliação que não terminou bem.

    UMA EXECUÇÃO `FAILED` NÃO SERVE, e a razão é a mesma da fusão: ela pode
    ter avaliado metade das partidas, e construir sobre metade produziria um
    corpus que parece completo e não é (§66).
    """
    if not run.produced_usable_output:
        raise ConflictError(
            f"a execução de qualidade {run.id} terminou em {run.status} e não produziu "
            "saída utilizável — construir sobre ela daria um corpus que parece "
            "completo e não é",
            context={"run_id": run.id, "status": run.status.value},
        )
