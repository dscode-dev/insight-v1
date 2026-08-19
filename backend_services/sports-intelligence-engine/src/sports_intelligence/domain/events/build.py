"""A decisão de construir UM evento, e o rastro do que aconteceu com ele.

A PERGUNTA QUE ESTE MÓDULO EXISTE PARA RESPONDER é a do §42:

    «por que este evento entrou ou não entrou no registro canônico?»

E ela precisa ter resposta por EVENTO, não por partida. A `MatchQualityAssessment`
continua sendo a autoridade sobre a partida — se a partida não é elegível,
nenhum evento dela é. Mas o inverso não vale: uma partida perfeitamente
elegível tem eventos que não entram, porque o jogador não resolveu, porque o
tipo não está mapeado, ou porque a licença do escopo não permite.

    MatchQualityAssessment    «esta PARTIDA pode entrar?»       PR-04.1/04.2
    EventEligibility          «este EVENTO pode entrar?»        aqui

O QUE ELE NÃO CRIA (§41, §43): nenhum eixo de qualidade novo. Os seis do
PR-04.1 bastam, e acrescentar um sétimo só para eventos faria «qualidade»
significar coisas diferentes em dois lugares do mesmo motor.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.events.records import HistoricalEventRecord
from sports_intelligence.domain.quality.issues import QualityIssue
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.provenance import LicenseClass

#: O ator de serviço da canonicalização de eventos. Nomeado pelo que ELE É
#: (PR-04.2 §75) — nunca `system`, `root` nem `admin`.
EVENT_CANONICALIZER: Final[str] = "historical-event-canonicalizer"


@final
class EventOutcome(StrEnum):
    """O destino de um evento candidato. Fechado."""

    INCLUDED = "INCLUDED"
    #: Problema sério que não bloqueia sozinho. Fica de FORA do registro
    #: automático até decisão humana — o meio-termo que um booleano não tem.
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    EXCLUDED = "EXCLUDED"

    @property
    def materializes(self) -> bool:
        return self is EventOutcome.INCLUDED


@final
class EventExclusionReason(StrEnum):
    """POR QUE um evento ficou de fora. Catálogo tipado, nunca texto livre.

    UM `str` AQUI SERIA O FIM DA CONSULTA. «Quantos eventos caíram por licença
    neste build» exige agrupar por motivo, e agrupar por texto livre agrupa
    `license`, `LICENSE` e `licença` em três respostas para a mesma pergunta.
    """

    #: A partida do evento não é elegível, ou não existe no registro.
    MATCH_NOT_ELIGIBLE = "MATCH_NOT_ELIGIBLE"
    #: `TeamId` ou `PlayerId` exigido pelo tipo não resolveu.
    IDENTITY_FAILURE = "IDENTITY_FAILURE"
    #: O tipo do provedor não está na tabela de tradução (§14).
    UNMAPPED_TYPE = "UNMAPPED_TYPE"
    #: Um problema bloqueante da política de qualidade.
    QUALITY_BLOCKER = "QUALITY_BLOCKER"
    #: A licença da evidência não permite este escopo de uso.
    LICENSE_POLICY = "LICENSE_POLICY"
    #: Duas linhas com a MESMA identidade de provedor e conteúdo incompatível,
    #: sem semântica de revisão que explique (§29).
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    #: A revisão aponta para um predecessor que não existe neste conjunto.
    DANGLING_REVISION = "DANGLING_REVISION"
    #: O relógio ou o período não formam um momento válido.
    INVALID_CLOCK = "INVALID_CLOCK"

    @property
    def is_license(self) -> bool:
        return self is EventExclusionReason.LICENSE_POLICY


@final
@dataclass(frozen=True, slots=True)
class EventEligibility:
    """O veredito sobre UM evento, com o porquê.

    A LICENÇA VIAJA JUNTO quando ela é a causa, pela mesma razão do PR-04.2:
    «evento excluído» não responde nada; «excluído por LICENSE_POLICY,
    RESEARCH_ONLY, num build COMMERCIAL» responde tudo, e é a pergunta que uma
    auditoria jurídica de fato faz.
    """

    record_key: str
    outcome: EventOutcome
    scope: UsageScope
    reason: EventExclusionReason | None = None
    license_class: LicenseClass | None = None
    issues: tuple[QualityIssue, ...] = ()
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.outcome is EventOutcome.INCLUDED and self.reason is not None:
            raise ValidationError(
                f"{self.record_key} incluído com motivo {self.reason} — um motivo "
                "aqui seria lido como se o evento tivesse ficado de fora"
            )
        if self.outcome is not EventOutcome.INCLUDED and self.reason is None:
            raise ValidationError(
                f"{self.record_key} em {self.outcome} sem motivo: um evento que some "
                "sem explicação é indistinguível de um que nunca existiu"
            )
        if self.reason is EventExclusionReason.LICENSE_POLICY and self.license_class is None:
            raise ValidationError(
                f"{self.record_key} excluído por licença e sem dizer QUAL — a "
                "exclusão por licença é a que mais precisa de resposta"
            )
        if (
            self.license_class is not None
            and self.reason is not EventExclusionReason.LICENSE_POLICY
        ):
            raise ValidationError(
                f"{self.record_key} carrega licença com motivo {self.reason}: ela "
                "afirmaria uma causa que não foi a causa"
            )

    @classmethod
    def included(
        cls, *, record_key: str, scope: UsageScope, issues: tuple[QualityIssue, ...] = ()
    ) -> Self:
        return cls(
            record_key=record_key,
            outcome=EventOutcome.INCLUDED,
            scope=scope,
            issues=issues,
        )

    @classmethod
    def excluded(
        cls,
        *,
        record_key: str,
        scope: UsageScope,
        reason: EventExclusionReason,
        license_class: LicenseClass | None = None,
        issues: tuple[QualityIssue, ...] = (),
        detail: str | None = None,
    ) -> Self:
        return cls(
            record_key=record_key,
            outcome=EventOutcome.EXCLUDED,
            scope=scope,
            reason=reason,
            license_class=license_class,
            issues=issues,
            detail=detail,
        )

    @classmethod
    def review(
        cls,
        *,
        record_key: str,
        scope: UsageScope,
        reason: EventExclusionReason,
        issues: tuple[QualityIssue, ...] = (),
        detail: str | None = None,
    ) -> Self:
        return cls(
            record_key=record_key,
            outcome=EventOutcome.REVIEW_REQUIRED,
            scope=scope,
            reason=reason,
            issues=issues,
            detail=detail,
        )

    def __str__(self) -> str:
        if self.outcome is EventOutcome.INCLUDED:
            return f"{self.record_key}: INCLUÍDO [{self.scope}]"
        licenca = f", {self.license_class}" if self.license_class else ""
        return f"{self.record_key}: {self.outcome} por {self.reason}{licenca}"


@final
class EventBuildRecordStatus(StrEnum):
    """O que de fato aconteceu com um evento na construção."""

    BUILT = "BUILT"
    #: Já existia no registro com o mesmo conteúdo. Linhagem nova, fato o
    #: mesmo — é o desfecho normal do reprocessamento (§24).
    REUSED = "REUSED"
    SKIPPED = "SKIPPED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"

    @property
    def persisted_a_fact(self) -> bool:
        return self in (EventBuildRecordStatus.BUILT, EventBuildRecordStatus.REUSED)


@final
@dataclass(frozen=True, slots=True)
class EventBuildRecord:
    """A linhagem de UM evento — a ponte do canônico até o byte bruto (§48).

    ELA GUARDA A CHAVE DA FONTE E O `record_ref`, e os dois servem a coisas
    diferentes: a chave identifica o evento DENTRO do provedor; o `record_ref`
    identifica a LINHA do arquivo que o produziu. Um evento corrigido tem a
    mesma chave e outra linha.
    """

    id: str
    build_run_id: str
    match_id: MatchId
    #: `provider:external_id`, ou `dataset:arquivo:linha` quando a fonte não
    #: dá id — a segunda forma é posicional e o contrato avisa disso.
    source_key: str
    record_ref: str
    status: EventBuildRecordStatus
    event_id: uuid.UUID | None = None
    reason: EventExclusionReason | None = None
    raw_type: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not self.source_key.strip():
            raise ValidationError("registro de evento sem chave de origem")
        if not self.record_ref.strip():
            raise ValidationError(
                f"{self.source_key} sem `record_ref`: a linhagem para trás se "
                "romperia no primeiro elo — não haveria como chegar ao arquivo"
            )
        if self.status.persisted_a_fact and self.event_id is None:
            raise ValidationError(
                f"{self.source_key} em {self.status} sem id do evento: ele afirma "
                "ter materializado e não diz o quê"
            )
        if not self.status.persisted_a_fact and self.event_id is not None:
            raise ValidationError(
                f"{self.source_key} em {self.status} com id de evento: o id "
                "apontaria para uma coisa que esta construção não gravou"
            )
        if self.status is EventBuildRecordStatus.FAILED and not (self.detail or "").strip():
            raise ValidationError("registro de evento FAILED sem detalhe")


@final
@dataclass(frozen=True, slots=True)
class EventBuildCounts:
    """As contagens de uma execução. Elas FECHAM, e a soma é verificada.

    A DIFERENÇA SILENCIOSA ENTRE ELAS é onde um lote perdido se esconde —
    a mesma razão da constraint de `canonical_build_runs` no PR-04.2.
    """

    records_read: int = 0
    events_built: int = 0
    events_reused: int = 0
    events_skipped: int = 0
    events_review_required: int = 0
    events_failed: int = 0

    def assert_consistent(self) -> None:
        soma = (
            self.events_built
            + self.events_reused
            + self.events_skipped
            + self.events_review_required
            + self.events_failed
        )
        if soma != self.records_read:
            raise ValidationError(
                f"{self.records_read} registro(s) lido(s) e {soma} classificado(s): "
                "a diferença é onde um lote perdido se esconde",
                context={"read": str(self.records_read), "classified": str(soma)},
            )

    def merged_with(self, other: EventBuildCounts) -> EventBuildCounts:
        return EventBuildCounts(
            records_read=self.records_read + other.records_read,
            events_built=self.events_built + other.events_built,
            events_reused=self.events_reused + other.events_reused,
            events_skipped=self.events_skipped + other.events_skipped,
            events_review_required=self.events_review_required + other.events_review_required,
            events_failed=self.events_failed + other.events_failed,
        )

    def __str__(self) -> str:
        return (
            f"{self.records_read} lido(s) · {self.events_built} construído(s), "
            f"{self.events_reused} reusado(s), {self.events_skipped} pulado(s), "
            f"{self.events_review_required} em revisão, {self.events_failed} falho(s)"
        )


def counts_of(records: tuple[EventBuildRecord, ...], *, read: int) -> EventBuildCounts:
    """As contagens a partir do que de fato foi gravado."""
    por_status = dict.fromkeys(EventBuildRecordStatus, 0)
    for registro in records:
        por_status[registro.status] += 1
    return EventBuildCounts(
        records_read=read,
        events_built=por_status[EventBuildRecordStatus.BUILT],
        events_reused=por_status[EventBuildRecordStatus.REUSED],
        events_skipped=por_status[EventBuildRecordStatus.SKIPPED],
        events_review_required=por_status[EventBuildRecordStatus.REVIEW_REQUIRED],
        events_failed=por_status[EventBuildRecordStatus.FAILED],
    )


def source_key_of(record: HistoricalEventRecord) -> str:
    """A chave de um registro — forte quando há id, posicional quando não há.

    A DEGRADAÇÃO É EXPLÍCITA E VISÍVEL. Sem `provider_event_id`, a identidade
    do evento passa a ser a POSIÇÃO no arquivo, e reler o mesmo arquivo com
    uma linha a mais no começo deslocaria todas as identidades. O contrato
    avisa disso na configuração (`EventContractReport.is_reprocessable`);
    aqui a chave apenas não mente sobre o que ela é.
    """
    return record.source_key or f"ref:{record.record_ref}"
