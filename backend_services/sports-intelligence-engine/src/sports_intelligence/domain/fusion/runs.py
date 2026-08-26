"""A execução de fusão e o candidato canônico que ela produz.

O QUE SAI DAQUI NÃO É CONHECIMENTO HISTÓRICO. `FusedMatchCandidate` é um
CANDIDATO: uma partida montada a partir de várias fontes, com cada campo
carregando quem o disse, quem discordou e sob qual regra foi escolhido.
Falta a ele tudo que o PR-04 traz — avaliação de qualidade do conjunto,
construção canônica, e a decisão de promover.

    RAW → STAGED → RESOLUTION RUN → FUSION RUN → CANDIDATO
                                                    ≠
                                              HISTORICAL_ACTIVE

A guarda é executável (`assert_not_historical_active`), e recusa sempre.

UMA EXECUÇÃO CONCLUÍDA É IMUTÁVEL (ADR-0020). Política de fusão nova produz
execução nova; a anterior fica exatamente como estava. Comparar as duas é o
único jeito honesto de saber o que a política nova mudou — e se ela pudesse
reescrever a anterior, a comparação seria contra si mesma.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Final, Self, final

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.fusion.models import (
    CanonicalFieldCandidate,
    FusionGroup,
    ObservationSet,
)
from sports_intelligence.domain.resolution.runs import RunStatus
from sports_intelligence.domain.resolution.versions import PolicyVersion
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import MatchId, ProviderId
from sports_intelligence.domain.shared.provenance import LicenseClass
from sports_intelligence.domain.shared.temporal import Instant

#: A versão do FORMATO da saída fundida. Sobe quando um campo muda de
#: significado — nunca quando um campo novo entra no fim.
FUSION_OUTPUT_SCHEMA_VERSION: Final[str] = "1.0"


@final
@dataclass(frozen=True, slots=True)
class FusedMatchCandidate:
    """Uma partida montada de várias fontes. Candidata, não canônica."""

    canonical_match_id: MatchId
    group_id: str
    fields: tuple[CanonicalFieldCandidate, ...]
    observation_sets: tuple[ObservationSet, ...] = ()
    schema_version: str = FUSION_OUTPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        nomes = [f.field_name for f in self.fields]
        if len(set(nomes)) != len(nomes):
            repetidos = sorted({n.value for n in nomes if nomes.count(n) > 1})
            raise ValidationError(
                f"campo fundido duas vezes: {repetidos} — dois valores para o mesmo "
                "campo é exatamente o que a fusão existe para não produzir"
            )
        tipos = [o.kind for o in self.observation_sets]
        if len(set(tipos)) != len(tipos):
            raise ValidationError("dois conjuntos de observação do mesmo tipo")

    @property
    def unresolved_conflicts(self) -> tuple[CanonicalFieldCandidate, ...]:
        return tuple(f for f in self.fields if f.is_unresolved_conflict)

    @property
    def has_unresolved_conflict(self) -> bool:
        return bool(self.unresolved_conflicts)

    @property
    def contributing_providers(self) -> tuple[ProviderId, ...]:
        provedores = {c.provider_id for campo in self.fields for c in campo.contributions} | {
            o.provider_id for conjunto in self.observation_sets for o in conjunto.observations
        }
        return tuple(sorted(provedores, key=str))

    @property
    def licenses(self) -> frozenset[LicenseClass]:
        """As licenças de TODAS as fontes que contribuíram, escalares e
        observações (§76).

        O candidato herda a restrição do CONJUNTO, e não a da fonte que venceu
        mais campos. Um campo cujo conflito foi resolvido consultando a fonte
        restrita foi produzido usando-a — mesmo que o valor final tenha vindo
        de outra.
        """
        das_escalares = frozenset(lic for campo in self.fields for lic in campo.licenses)
        das_observacoes = frozenset(
            lic for conjunto in self.observation_sets for lic in conjunto.licenses
        )
        return das_escalares | das_observacoes

    @property
    def most_restrictive_license(self) -> LicenseClass:
        """A licença que governa o uso deste candidato.

        A MAIS RESTRITIVA DO CONJUNTO. Um candidato montado com uma fonte
        `PUBLIC_DOMAIN` e uma `RESEARCH_ONLY` é `RESEARCH_ONLY`: usar a
        permissiva porque ela contribuiu com mais campos seria contornar a
        restrição da outra pelo caminho de trás.
        """
        ordem = [
            LicenseClass.UNKNOWN,
            LicenseClass.RESEARCH_ONLY,
            LicenseClass.ATTRIBUTION_REQUIRED,
            LicenseClass.COMMERCIAL_ALLOWED,
            LicenseClass.PUBLIC_DOMAIN,
        ]
        presentes = self.licenses
        return next((lic for lic in ordem if lic in presentes), LicenseClass.UNKNOWN)

    def field(self, name: str) -> CanonicalFieldCandidate | None:
        return next((f for f in self.fields if f.field_name.value == name), None)

    def as_canonical(self) -> dict[str, Any]:
        """A forma determinística da saída, para impressão e para a API.

        ORDENADA POR NOME DE CAMPO e por fonte, pelo mesmo motivo do
        manifesto do PR-02: a ordem de reconstrução a partir do banco não é a
        de inserção, e sem ordenação a mesma saída produziria impressões
        diferentes.
        """
        return {
            "canonical_match_id": str(self.canonical_match_id),
            "schema_version": self.schema_version,
            "fields": [
                {
                    "confidence": round(campo.confidence, 6),
                    "name": campo.field_name.value,
                    "rule": campo.rule.value,
                    "selected_from": str(campo.selected_from) if campo.selected_from else None,
                    "selected_value": campo.selected_value,
                    "sources": [
                        {
                            "provider": str(c.provider_id),
                            "record": str(c.record_ref),
                            "value": c.value,
                        }
                        for c in sorted(campo.contributions, key=lambda c: str(c.provider_id))
                    ],
                }
                for campo in sorted(self.fields, key=lambda f: f.field_name.value)
            ],
            "observation_sets": [
                {
                    "kind": conjunto.kind,
                    "observations": [
                        {
                            "discriminator": o.discriminator,
                            "provider": str(o.provider_id),
                            "record": str(o.record_ref),
                            "values": dict(sorted(o.values.items())),
                        }
                        for o in sorted(conjunto.observations, key=lambda o: o.discriminator)
                    ],
                }
                for conjunto in sorted(self.observation_sets, key=lambda s: s.kind)
            ],
        }

    @property
    def fingerprint(self) -> ContentHash:
        """A impressão da saída fundida.

        VALE O CUSTO PELO MESMO MOTIVO DO MANIFESTO: ela responde «duas
        execuções produziram a mesma coisa?» comparando 64 caracteres, em vez
        de percorrer campo a campo. É o que permite provar reprodutibilidade
        num teste — e num incidente.
        """
        bruto = json.dumps(
            self.as_canonical(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return ContentHash(hashlib.sha256(bruto).hexdigest())

    def __str__(self) -> str:
        conflitos = len(self.unresolved_conflicts)
        marca = f" · {conflitos} conflito(s)" if conflitos else ""
        return (
            f"candidato {self.canonical_match_id} · {len(self.fields)} campo(s) · "
            f"{len(self.observation_sets)} conjunto(s){marca}"
        )


@final
@dataclass(frozen=True, slots=True)
class FusionCounts:
    """O resumo de uma execução de fusão."""

    groups: int = 0
    multi_source_groups: int = 0
    fields_selected: int = 0
    conflicts: int = 0
    unresolved_conflicts: int = 0
    observation_sets: int = 0

    def __post_init__(self) -> None:
        if self.unresolved_conflicts > self.conflicts:
            raise ValidationError(
                f"{self.unresolved_conflicts} conflitos não resolvidos de "
                f"{self.conflicts} totais: o subconjunto é maior que o conjunto"
            )
        if self.multi_source_groups > self.groups:
            raise ValidationError("mais grupos multi-fonte que grupos")

    @property
    def conflict_rate(self) -> float | None:
        """`None` quando não houve campo. Nunca zero — ver PR-02."""
        return self.conflicts / self.fields_selected if self.fields_selected else None


@final
@dataclass(frozen=True, slots=True)
class FusionRun:
    """Uma execução de fusão sobre execuções de resolução declaradas."""

    id: str
    #: As execuções de resolução que alimentaram esta. PLURAL: a fusão é
    #: multi-fonte por definição, e cada fonte tem a sua.
    input_resolution_run_ids: tuple[str, ...]
    policy_version: PolicyVersion
    status: RunStatus
    started_at: Instant
    triggered_by: Actor
    counts: FusionCounts = field(default_factory=FusionCounts)
    completed_at: Instant | None = None
    failure_reason: str | None = None
    #: A impressão do conjunto de saída, quando concluída. Permite comparar
    #: duas execuções sem carregar as duas.
    output_fingerprint: ContentHash | None = None

    def __post_init__(self) -> None:
        if not self.input_resolution_run_ids:
            raise ValidationError("execução de fusão sem entrada: ela funde o quê?")
        if len(set(self.input_resolution_run_ids)) != len(self.input_resolution_run_ids):
            raise ValidationError(
                "a mesma execução de resolução listada duas vezes — os registros "
                "dela entrariam duplicados e inflariam a concordância"
            )
        if self.status.is_terminal and self.completed_at is None:
            raise ValidationError(f"execução em {self.status} sem instante de conclusão")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValidationError("execução concluída antes de começar")
        if self.status is RunStatus.FAILED and not (self.failure_reason or "").strip():
            raise ValidationError("execução FAILED sem motivo")

    @classmethod
    def start(
        cls,
        *,
        input_resolution_run_ids: tuple[str, ...],
        policy_version: PolicyVersion,
        at: Instant,
        triggered_by: Actor,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            input_resolution_run_ids=input_resolution_run_ids,
            policy_version=policy_version,
            status=RunStatus.RUNNING,
            started_at=at,
            triggered_by=triggered_by,
        )

    def complete(
        self,
        *,
        counts: FusionCounts,
        at: Instant,
        output_fingerprint: ContentHash | None = None,
    ) -> Self:
        """Fecha a execução. O status sai das contagens.

        CONFLITO NÃO RESOLVIDO LEVA A `COMPLETED_WITH_REVIEW`, e não a
        `COMPLETED`. Os dois são sucesso; a diferença é que o segundo diz
        «nada a fazer», e há coisa a fazer.
        """
        self._assert_can_finish()
        destino = (
            RunStatus.COMPLETED_WITH_REVIEW
            if counts.unresolved_conflicts > 0
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
        return replace(self, status=RunStatus.FAILED, completed_at=at, failure_reason=reason[:500])

    def _assert_can_finish(self) -> None:
        if self.status.is_terminal:
            raise ConflictError(
                f"execução de fusão já terminou em {self.status} — uma execução "
                "concluída é imutável; política nova produz execução nova (ADR-0020)",
                context={"run_id": self.id},
            )

    @property
    def duration_seconds(self) -> float | None:
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()

    def __str__(self) -> str:
        return (
            f"fusão {self.id[:8]} [{self.status}] política {self.policy_version} · "
            f"{self.counts.groups} grupo(s), {self.counts.unresolved_conflicts} conflito(s)"
        )


def assert_not_historical_active(candidate: FusedMatchCandidate) -> None:
    """A guarda do limite deste PR. Recusa SEMPRE.

    Existe para ser chamada por qualquer caminho futuro que pretenda promover
    um candidato fundido para o índice histórico. Entre uma coisa e outra
    estão a avaliação de qualidade e a construção canônica — o PR-04 — mais a
    barreira do ADR-0007.
    """
    from sports_intelligence.domain.shared.errors import InvariantViolationError

    raise InvariantViolationError(
        f"o candidato {candidate.canonical_match_id} é uma partida MONTADA a partir "
        "de fontes, não conhecimento histórico ativo. Falta a avaliação de qualidade "
        "do conjunto e a construção canônica, que são o PR-04 (ADR-0007, ADR-0016).",
        context={"match_id": str(candidate.canonical_match_id)},
    )


def assert_group_is_fully_resolved(group: FusionGroup) -> None:
    """Reconfere, na entrada da fusão, que todo registro tem decisão.

    O TIPO JÁ GARANTE ISSO — `ResolvedSourceRecord` não se constrói sem
    `resolution_decision_id`. Esta função existe como segunda linha para o
    caminho que reconstrói um grupo a partir do banco, onde o tipo é montado
    por nós e um `None` que escapou viraria fusão de identidade não provada
    (ADR-0022).
    """
    sem_decisao = [r for r in group.records if not r.resolution_decision_id.strip()]
    if sem_decisao:
        raise ConflictError(
            f"grupo {group.id} tem {len(sem_decisao)} registro(s) sem decisão de "
            "resolução — a fusão só aceita identidade provada",
            context={"group_id": group.id},
        )
