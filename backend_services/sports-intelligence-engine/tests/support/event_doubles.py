"""Os duplos em memória do PR-04.4.1 — com as MESMAS restrições dos reais.

A armadilha continua sendo a mesma dos PRs anteriores: um duplo mais
permissivo que o real deixa passar exatamente a classe de erro que o real
bloquearia. Então aqui:

    `persist_events`   é idempotente pelo `id` DERIVADO, e distingue `BUILT`
                       de `REUSED` como o `ON CONFLICT` + consulta prévia
    `mark_superseded`  só age sobre quem está `ACTIVE`, como o `WHERE` do real
    `events_of_match`  devolve em ordem DETERMINÍSTICA, como o `ORDER BY`
    `append_many`      é idempotente por `(execução, chave)`, como o UNIQUE
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Final, final

from sports_intelligence.domain.events.build import (
    EventBuildRecord,
    EventBuildRecordStatus,
)
from sports_intelligence.domain.events.canonical import CanonicalMatchEvent, EventStatus
from sports_intelligence.domain.events.runs import CanonicalEventBuildRun
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.mappings import ProviderEntityMapping
from sports_intelligence.domain.resolution.runs import RunStatus
from sports_intelligence.domain.shared.identity import (
    DatasetId,
    EntityId,
    MatchId,
    ProviderId,
)
from sports_intelligence.domain.shared.temporal import Instant, Period

#: A ordem dos períodos, para a leitura determinística. É a mesma constante do
#: adapter — duas cópias divergiriam, e a divergência apareceria como duas
#: leituras discordando sobre os mesmos fatos.
_ORDEM: Final[dict[Period, int]] = {
    Period.PRE_MATCH: 0,
    Period.FIRST_HALF: 1,
    Period.HALF_TIME: 2,
    Period.SECOND_HALF: 3,
    Period.EXTRA_TIME_FIRST: 4,
    Period.EXTRA_TIME_BREAK: 5,
    Period.EXTRA_TIME_SECOND: 6,
    Period.PENALTY_SHOOTOUT: 7,
    Period.FULL_TIME: 8,
}


@final
class FakeProviderMappingRepository:
    """As traduções que a resolução JÁ provou. O que não está aqui não resolve."""

    def __init__(self, mappings: Sequence[ProviderEntityMapping] = ()) -> None:
        self.mappings = list(mappings)
        #: Quantas consultas foram feitas. É o número que prova o lote em vez
        #: de supô-lo — com N+1 ele cresceria com as linhas, não com os lotes.
        self.consultas = 0

    async def by_external_ids(
        self, provider: ProviderId, subject: SubjectType, external_ids: Sequence[str]
    ) -> Sequence[ProviderEntityMapping]:
        self.consultas += 1
        alvo = set(external_ids)
        return [
            m
            for m in self.mappings
            if m.provider_id == provider
            and m.entity_type is subject
            and m.provider_entity_id in alvo
        ]

    async def create_if_absent(self, mapping: ProviderEntityMapping) -> ProviderEntityMapping:
        existente = next(
            (
                m
                for m in self.mappings
                if m.provider_id == mapping.provider_id
                and m.entity_type is mapping.entity_type
                and m.provider_entity_id == mapping.provider_entity_id
            ),
            None,
        )
        if existente is not None:
            return existente
        self.mappings.append(mapping)
        return mapping

    async def by_canonical(
        self, subject: SubjectType, canonical_id: str
    ) -> Sequence[ProviderEntityMapping]:
        return [
            m
            for m in self.mappings
            if m.entity_type is subject and str(m.canonical_entity_id) == canonical_id
        ]


@final
class FakeCanonicalEventWriter:
    """O registro canônico de eventos, em memória."""

    def __init__(self) -> None:
        self.events: dict[uuid.UUID, CanonicalMatchEvent] = {}
        #: Quantos `INSERT` foram ignorados por já existirem. É a idempotência
        #: do §24 medida, e não suposta.
        self.reaproveitados = 0
        self.build_runs: list[str] = []
        self.source_keys: dict[uuid.UUID, str] = {}

    async def persist_events(
        self,
        events: Sequence[CanonicalMatchEvent],
        *,
        build_run_id: str,
        source_keys: Mapping[uuid.UUID, str],
    ) -> Mapping[uuid.UUID, EventBuildRecordStatus]:
        self.build_runs.append(build_run_id)
        self.source_keys.update(source_keys)
        desfechos: dict[uuid.UUID, EventBuildRecordStatus] = {}
        for evento in events:
            if evento.id in self.events:
                self.reaproveitados += 1
                desfechos[evento.id] = EventBuildRecordStatus.REUSED
                continue
            self.events[evento.id] = evento
            desfechos[evento.id] = EventBuildRecordStatus.BUILT
        return desfechos

    async def mark_superseded(self, transitions: Sequence[tuple[uuid.UUID, uuid.UUID]]) -> int:
        marcados = 0
        for anterior, _ in transitions:
            evento = self.events.get(anterior)
            # SÓ QUEM ESTÁ `ACTIVE`, como o `WHERE` do real: um evento já
            # cancelado não se corrige — ele não aconteceu.
            if evento is None or evento.status is not EventStatus.ACTIVE:
                continue
            self.events[anterior] = replace(evento, status=EventStatus.CORRECTED)
            marcados += 1
        return marcados

    async def mark_cancelled(self, event_ids: Sequence[uuid.UUID]) -> int:
        marcados = 0
        for identificador in event_ids:
            evento = self.events.get(identificador)
            if evento is None or evento.status is EventStatus.CANCELLED:
                continue
            self.events[identificador] = replace(evento, status=EventStatus.CANCELLED)
            marcados += 1
        return marcados

    async def events_of_match(
        self, match_id: MatchId, *, include_superseded: bool = False
    ) -> Sequence[CanonicalMatchEvent]:
        candidatos = [
            e
            for e in self.events.values()
            if e.match_id == match_id
            and (include_superseded or e.status is not EventStatus.CORRECTED)
        ]
        return sorted(
            candidatos,
            key=lambda e: (
                _ORDEM[e.clock.period],
                e.clock.minute,
                e.clock.stoppage,
                e.sequence,
                str(e.id),
            ),
        )

    async def existing_ids(self, event_ids: Sequence[uuid.UUID]) -> frozenset[uuid.UUID]:
        return frozenset(i for i in event_ids if i in self.events)


@final
class FakeCanonicalEventBuildRunRepository:
    """Execuções. `finish` é condicional ao estado, como o `UPDATE` real."""

    def __init__(self) -> None:
        self.runs: dict[str, CanonicalEventBuildRun] = {}
        #: Quantos `finish` foram RECUSADOS por estado. É o número que prova a
        #: serialização em vez de supô-la.
        self.recusas = 0

    async def create(self, run: CanonicalEventBuildRun) -> CanonicalEventBuildRun:
        self.runs[run.id] = run
        return run

    async def finish(self, run: CanonicalEventBuildRun) -> bool:
        atual = self.runs.get(run.id)
        if atual is None or atual.status is not RunStatus.RUNNING:
            self.recusas += 1
            return False
        self.runs[run.id] = run
        return True

    async def by_id(self, run_id: str) -> CanonicalEventBuildRun | None:
        return self.runs.get(run_id)

    async def for_dataset(
        self, dataset_id: DatasetId, *, limit: int = 20
    ) -> Sequence[CanonicalEventBuildRun]:
        return [r for r in self.runs.values() if r.dataset_id == dataset_id][:limit]


@final
class FakeEventBuildRecordRepository:
    """A linhagem. APPEND-ONLY e idempotente por `(execução, chave)`."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], EventBuildRecord] = {}
        self.ignorados = 0

    async def append_many(self, records: Sequence[EventBuildRecord]) -> int:
        for registro in records:
            chave = (registro.build_run_id, registro.source_key)
            if chave in self.records:
                self.ignorados += 1
                continue
            self.records[chave] = registro
        return len(records)

    async def for_match(self, match_id: MatchId) -> Sequence[EventBuildRecord]:
        return [r for r in self.records.values() if r.match_id == match_id]

    async def by_source_keys(
        self, build_run_id: str, source_keys: Sequence[str]
    ) -> Sequence[EventBuildRecord]:
        alvo = set(source_keys)
        return [
            r
            for (execucao, chave), r in self.records.items()
            if execucao == build_run_id and chave in alvo
        ]

    def by_status(self, status: EventBuildRecordStatus) -> list[EventBuildRecord]:
        return [r for r in self.records.values() if r.status is status]


def mapeamento(
    *,
    provider: ProviderId,
    subject: SubjectType,
    externo: str,
    canonico: str,
    at: Instant,
) -> ProviderEntityMapping:
    """Uma tradução provada. `resolution_decision_id` é OBRIGATÓRIO no domínio."""
    return ProviderEntityMapping(
        id=str(uuid.uuid4()),
        provider_id=provider,
        entity_type=subject,
        provider_entity_id=externo,
        canonical_entity_id=EntityId(uuid.UUID(canonico)),
        resolution_decision_id=str(uuid.uuid4()),
        created_at=at,
        created_by="pr0441-fixture",
    )
