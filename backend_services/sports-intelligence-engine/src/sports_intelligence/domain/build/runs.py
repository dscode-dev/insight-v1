"""A execução de construção canônica e o registro que ela deixa por fato.

O QUE `CanonicalBuildRecord` RESPONDE, e nada mais responde:

    «por que este Match está no corpus?»   → assessment que o autorizou
    «de onde ele veio?»                    → grupo de fusão, e dali o raw
    «e as odds dele?»                      → família excluída, com motivo

Sem ele, um fato canônico é uma linha numa tabela sem pai. Com ele, a
travessia `fato → build → avaliação → fusão → record_ref → arquivo → SHA-256`
é uma sequência de junções (§47, §102).

DUAS EXECUÇÕES PODEM APONTAR PARA O MESMO FATO (§97). Um `Match` já canônico
não é recriado pela segunda: ele é REUSADO, e a segunda execução grava a
própria linhagem ao lado da primeira. A identidade do fato e a linhagem da
construção são coisas separadas, e é a separação que torna o §61 possível.

UMA EXECUÇÃO CONCLUÍDA É IMUTÁVEL (§22, §51). Política de build nova produz
execução nova; a anterior fica como estava. É o que permite o corpus de
pesquisa e o comercial coexistirem sobre a mesma avaliação (§52).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Self, final

from sports_intelligence.domain.build.decisions import (
    BuildDecision,
    BuildOutcome,
    CanonicalFactType,
)
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.resolution.runs import RunStatus
from sports_intelligence.domain.resolution.versions import PolicyVersion
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import Instant


class BuildRecordStatus(StrEnum):
    """O que aconteceu com UM fato canônico nesta execução."""

    #: O fato não existia e passou a existir.
    BUILT = "BUILT"
    #: O fato JÁ EXISTIA, semanticamente idêntico, e foi reaproveitado (§63).
    #: Distinto de `BUILT` porque a pergunta operacional «quantas partidas
    #: novas este build trouxe» tem respostas diferentes nos dois casos.
    REUSED = "REUSED"
    #: A política mandou não construir. Não é falha.
    SKIPPED = "SKIPPED"
    #: Fica fora do automático até alguém olhar (§85).
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    #: Tentou e não conseguiu — conflito estrutural com o fato existente (§62)
    #: ou erro na persistência. É falha NOSSA ou do dado, e nunca silenciosa.
    FAILED = "FAILED"

    @property
    def persisted_a_fact(self) -> bool:
        return self in (BuildRecordStatus.BUILT, BuildRecordStatus.REUSED)


class MatchWriteOutcome(StrEnum):
    """O que a escrita canônica fez com um fato que pode já existir.

    TRÊS E NÃO `upsert`. Um `upsert` responde «gravado» aos três casos, e o
    terceiro — o fato existente DISCORDA do que estamos gravando — é
    exatamente aquele em que gravar é o erro (§62). `last write wins` sobre um
    fato histórico reescreve silenciosamente o passado.
    """

    INSERTED = "INSERTED"
    #: Já existia e é semanticamente idêntico. Reaproveitado (§63).
    REUSED_EQUIVALENT = "REUSED_EQUIVALENT"
    #: Já existe e é DIFERENTE. Nada foi escrito, e alguém precisa decidir.
    CONFLICT = "CONFLICT"

    @property
    def is_conflict(self) -> bool:
        return self is MatchWriteOutcome.CONFLICT


@final
@dataclass(frozen=True, slots=True)
class BuildCounts:
    """O resumo de uma execução de construção."""

    records_attempted: int = 0
    records_built: int = 0
    records_reused: int = 0
    records_skipped: int = 0
    records_review_required: int = 0
    records_failed: int = 0
    families_excluded: int = 0

    def __post_init__(self) -> None:
        for nome, valor in (
            ("records_attempted", self.records_attempted),
            ("records_built", self.records_built),
            ("records_reused", self.records_reused),
            ("records_skipped", self.records_skipped),
            ("records_review_required", self.records_review_required),
            ("records_failed", self.records_failed),
            ("families_excluded", self.families_excluded),
        ):
            if valor < 0:
                raise ValidationError(f"{nome} negativo: {valor}")

    def assert_consistent(self) -> None:
        soma = (
            self.records_built
            + self.records_reused
            + self.records_skipped
            + self.records_review_required
            + self.records_failed
        )
        if soma != self.records_attempted:
            raise ValidationError(
                f"{self.records_attempted} partidas tentadas e {soma} classificadas — "
                "a diferença é onde uma partida some sem ninguém notar",
                context={"attempted": self.records_attempted, "classified": soma},
            )

    def merged_with(self, other: BuildCounts) -> BuildCounts:
        return BuildCounts(
            records_attempted=self.records_attempted + other.records_attempted,
            records_built=self.records_built + other.records_built,
            records_reused=self.records_reused + other.records_reused,
            records_skipped=self.records_skipped + other.records_skipped,
            records_review_required=self.records_review_required
            + other.records_review_required,
            records_failed=self.records_failed + other.records_failed,
            families_excluded=self.families_excluded + other.families_excluded,
        )


@final
@dataclass(frozen=True, slots=True)
class CanonicalBuildRecord:
    """A linhagem de UM fato canônico produzido (ou recusado) por UM build.

    `fact_id` É `None` QUANDO NADA FOI MATERIALIZADO, e a ausência é a
    informação: um registro `SKIPPED` com id de fato apontaria para uma coisa
    que não existe, e a travessia de linhagem terminaria num beco.
    """

    id: str
    build_run_id: str
    match_id: MatchId
    fact_type: CanonicalFactType
    #: O grupo de fusão de onde a evidência veio — o elo para trás (§47).
    source_fusion_group_id: str
    #: A avaliação que AUTORIZOU ou RECUSOU a construção (§50). Obrigatória:
    #: um fato canônico sem avaliação é um fato que entrou sem critério.
    quality_assessment_id: str
    status: BuildRecordStatus
    fact_id: str | None = None
    included_families: tuple[CoverageFamily, ...] = ()
    excluded_families: tuple[CoverageFamily, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.quality_assessment_id.strip():
            raise ValidationError(
                f"{self.fact_type} de {self.match_id} sem avaliação de qualidade — "
                "«por que este fato entrou no corpus» ficaria sem resposta (§50)"
            )
        if not self.source_fusion_group_id.strip():
            raise ValidationError(
                f"{self.fact_type} de {self.match_id} sem grupo de fusão: a linhagem "
                "para trás se romperia no primeiro elo (§47, §48)"
            )
        if self.status.persisted_a_fact and not (self.fact_id or "").strip():
            raise ValidationError(
                f"{self.fact_type} em {self.status} sem id do fato — ele afirma ter "
                "materializado e não diz o quê"
            )
        if not self.status.persisted_a_fact and self.fact_id is not None:
            raise ValidationError(
                f"{self.fact_type} em {self.status} com id de fato: o id apontaria "
                "para uma coisa que este build não gravou"
            )
        if self.status is BuildRecordStatus.FAILED and not (self.reason or "").strip():
            raise ValidationError("registro FAILED sem motivo")
        comuns = set(self.included_families) & set(self.excluded_families)
        if comuns:
            raise ValidationError(
                f"família incluída E excluída no mesmo registro: "
                f"{sorted(f.value for f in comuns)}"
            )

    @classmethod
    def of(
        cls,
        *,
        build_run_id: str,
        decision: BuildDecision,
        fact_type: CanonicalFactType,
        source_fusion_group_id: str,
        quality_assessment_id: str,
        status: BuildRecordStatus,
        fact_id: str | None = None,
        reason: str | None = None,
    ) -> Self:
        """Deriva o registro da decisão — as famílias não são redigitadas.

        Copiá-las à mão seria a segunda cópia da mesma verdade, e a segunda
        cópia diverge.
        """
        return cls(
            id=str(uuid.uuid4()),
            build_run_id=build_run_id,
            match_id=decision.match_id,
            fact_type=fact_type,
            source_fusion_group_id=source_fusion_group_id,
            quality_assessment_id=quality_assessment_id,
            status=status,
            fact_id=fact_id,
            included_families=decision.included_families,
            excluded_families=decision.excluded_families,
            reason=reason or decision.reason,
        )

    def as_canonical(self) -> dict[str, object]:
        """A forma determinística. SEM `id` e SEM `build_run_id` (§54): os
        dois são identificadores de execução, e duas execuções idênticas
        precisam produzir a mesma impressão."""
        return {
            "excluded_families": [f.value for f in self.excluded_families],
            "fact_type": self.fact_type.value,
            "included_families": [f.value for f in self.included_families],
            "match_id": str(self.match_id),
            "quality_assessment_id": self.quality_assessment_id,
            "source_fusion_group_id": self.source_fusion_group_id,
            "status": self.status.value,
        }

    def __str__(self) -> str:
        return f"{self.match_id} · {self.fact_type} · {self.status}"


@final
@dataclass(frozen=True, slots=True)
class CanonicalBuildRun:
    """Uma construção canônica sobre UMA avaliação, sob UMA política de build."""

    id: str
    quality_run_id: str
    #: As fusões que alimentaram a avaliação. Copiadas para cá porque a
    #: pergunta «de quais datasets veio este corpus» não deveria exigir dois
    #: saltos numa investigação.
    input_fusion_run_ids: tuple[str, ...]
    build_policy_version: PolicyVersion
    #: A impressão do CONTEÚDO da política de build (PR-04.2.1 §37). A versão
    #: pega a mudança declarada; esta pega a que ninguém declarou — alguém
    #: edita a lista de famílias descartáveis e esquece de subir o número, e
    #: dois corpus comerciais rotulados `1.0` passam a incluir coisas
    #: diferentes.
    #:
    #: `None` SÓ NAS EXECUÇÕES ANTERIORES À MIGRATION 0006. Quem cria uma
    #: execução hoje passa a impressão, e o caso de uso não a omite.
    build_policy_fingerprint: ContentHash | None
    scope: UsageScope
    #: A versão da política de QUALIDADE sob a qual a avaliação rodou (§21).
    #: Guardada aqui também: um build é explicável por DUAS políticas, e ter
    #: de ir buscar a segunda em outra tabela faz alguém não ir.
    quality_policy_version: PolicyVersion
    status: RunStatus
    started_at: Instant
    triggered_by: Actor
    counts: BuildCounts = field(default_factory=BuildCounts)
    completed_at: Instant | None = None
    failure_reason: str | None = None
    #: A impressão do conjunto de registros produzidos. Prova determinismo
    #: (§53, §54) sem carregar as duas execuções.
    output_fingerprint: ContentHash | None = None

    def __post_init__(self) -> None:
        if not self.quality_run_id.strip():
            raise ValidationError(
                "construção sem execução de qualidade: ela constrói com base em quê?"
            )
        if len(set(self.input_fusion_run_ids)) != len(self.input_fusion_run_ids):
            raise ValidationError("a mesma execução de fusão declarada duas vezes")
        if self.status.is_terminal and self.completed_at is None:
            raise ValidationError(f"execução em {self.status} sem instante de conclusão")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValidationError("execução concluída antes de começar")
        if self.status is RunStatus.FAILED and not (self.failure_reason or "").strip():
            raise ValidationError("execução FAILED sem motivo")
        self.counts.assert_consistent()

    @classmethod
    def start(
        cls,
        *,
        quality_run_id: str,
        input_fusion_run_ids: tuple[str, ...],
        build_policy_version: PolicyVersion,
        build_policy_fingerprint: ContentHash,
        scope: UsageScope,
        quality_policy_version: PolicyVersion,
        at: Instant,
        triggered_by: Actor,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            quality_run_id=quality_run_id,
            input_fusion_run_ids=input_fusion_run_ids,
            build_policy_version=build_policy_version,
            build_policy_fingerprint=build_policy_fingerprint,
            scope=scope,
            quality_policy_version=quality_policy_version,
            status=RunStatus.RUNNING,
            started_at=at,
            triggered_by=triggered_by,
        )

    def complete(
        self,
        *,
        counts: BuildCounts,
        at: Instant,
        output_fingerprint: ContentHash | None = None,
    ) -> Self:
        """Fecha a execução. O status SAI DAS CONTAGENS (§66).

        UM ÚNICO FATO QUE FALHOU LEVA A `FAILED`, e não a `COMPLETED`. Um
        corpus que perdeu uma partida por conflito estrutural e se declara
        concluído mente exatamente onde a mentira é mais cara: no número que
        alguém vai usar para decidir publicar.

        Partidas em revisão levam a `COMPLETED_WITH_REVIEW` — sucesso com
        trabalho pendente, que é uma terceira coisa.
        """
        self._assert_can_finish()
        counts.assert_consistent()
        if counts.records_failed:
            return replace(
                self,
                status=RunStatus.FAILED,
                counts=counts,
                completed_at=at,
                failure_reason=(
                    f"{counts.records_failed} fato(s) não puderam ser construídos — "
                    "ver os registros em FAILED"
                ),
                output_fingerprint=output_fingerprint,
            )
        destino = (
            RunStatus.COMPLETED_WITH_REVIEW
            if counts.records_review_required
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
                f"construção já terminou em {self.status} — uma execução concluída é "
                "imutável; política nova produz execução nova (ADR-0024)",
                context={"run_id": self.id, "status": self.status.value},
            )

    @property
    def duration_seconds(self) -> float | None:
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()

    def __str__(self) -> str:
        return (
            f"build {self.id[:8]} [{self.status}] {self.scope} política "
            f"{self.build_policy_version} · {self.counts.records_built} construído(s), "
            f"{self.counts.records_reused} reusado(s)"
        )


def assert_not_a_published_corpus(run: CanonicalBuildRun) -> None:
    """A guarda do limite DESTA fase. Recusa sempre.

    O QUE SAI DAQUI SÃO FATOS CANÔNICOS PERSISTIDOS — não um corpus histórico
    publicável. Falta a eles tudo que o PR-04.3 traz: a versão imutável do
    dataset, o manifesto, a impressão do corpus, o Parquet e a interface que
    os publica.

    Existe para ser chamada por qualquer caminho que pretenda tratar uma
    execução de build como uma versão publicada do histórico (§110, §111).
    """
    from sports_intelligence.domain.shared.errors import InvariantViolationError

    raise InvariantViolationError(
        f"a execução de build {run.id} produziu FATOS canônicos, não uma versão "
        "publicável do corpus histórico. Faltam a versão imutável do dataset, o "
        "manifesto e a impressão do corpus, que são o PR-04.3 (ADR-0016, ADR-0024).",
        context={"run_id": run.id, "status": run.status.value},
    )


def counts_of(
    decisions: tuple[BuildDecision, ...], records: tuple[CanonicalBuildRecord, ...]
) -> BuildCounts:
    """As contagens de um lote — por PARTIDA, e as famílias por decisão.

    A UNIDADE DE `records_*` É A PARTIDA E NÃO O FATO, e a escolha importa:
    contar fatos faria uma partida com placar e odds valer três, e o número
    «partidas no corpus» deixaria de ser o número de partidas.
    """
    por_partida: dict[str, BuildRecordStatus] = {}
    for registro in records:
        chave = str(registro.match_id)
        atual = por_partida.get(chave)
        por_partida[chave] = _pior(atual, registro.status)
    return BuildCounts(
        records_attempted=len(decisions),
        records_built=sum(1 for s in por_partida.values() if s is BuildRecordStatus.BUILT),
        records_reused=sum(
            1 for s in por_partida.values() if s is BuildRecordStatus.REUSED
        ),
        records_skipped=sum(
            1 for s in por_partida.values() if s is BuildRecordStatus.SKIPPED
        ),
        records_review_required=sum(
            1 for s in por_partida.values() if s is BuildRecordStatus.REVIEW_REQUIRED
        ),
        records_failed=sum(
            1 for s in por_partida.values() if s is BuildRecordStatus.FAILED
        ),
        families_excluded=sum(len(d.excluded_families) for d in decisions),
    )


#: Da mais grave para a menos. Quando uma partida produz fatos com desfechos
#: diferentes — `Match` reusado e `MatchResult` falhado —, a partida conta
#: pelo PIOR: um build que reaproveitou a partida e perdeu o placar não é um
#: sucesso parcial, é uma falha com um sucesso dentro.
_GRAVIDADE: dict[BuildRecordStatus, int] = {
    BuildRecordStatus.FAILED: 0,
    BuildRecordStatus.REVIEW_REQUIRED: 1,
    BuildRecordStatus.SKIPPED: 2,
    BuildRecordStatus.BUILT: 3,
    BuildRecordStatus.REUSED: 4,
}


def _pior(atual: BuildRecordStatus | None, novo: BuildRecordStatus) -> BuildRecordStatus:
    if atual is None:
        return novo
    return min(atual, novo, key=lambda s: _GRAVIDADE[s])


def outcome_to_record_status(outcome: BuildOutcome) -> BuildRecordStatus:
    """A tradução entre a decisão e o desfecho de um fato NÃO materializado.

    EXISTE PARA QUE ELA SEJA UMA SÓ. A mesma tradução escrita em dois pontos
    do orquestrador divergiria, e a divergência apareceria como uma partida
    contada em `SKIPPED` num lugar e em `REVIEW_REQUIRED` noutro.
    """
    return {
        BuildOutcome.SKIP: BuildRecordStatus.SKIPPED,
        BuildOutcome.REVIEW_REQUIRED: BuildRecordStatus.REVIEW_REQUIRED,
        BuildOutcome.BUILD: BuildRecordStatus.BUILT,
    }[outcome]
