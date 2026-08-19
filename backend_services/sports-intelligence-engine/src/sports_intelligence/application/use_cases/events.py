"""O caso de uso da canonicalização histórica de eventos.

A CADEIA COMPLETA, e o lugar de cada peça (§79):

    registros de evento    lidos de quem os leu — trabalho de BORDA
    referências            traduzidas em lote, três consultas por lote
    elegibilidade          decide, e é a única que decide
    construtor             materializa, e recusa sem decisão
    registro canônico      escreve em massa, com desfecho por evento
    linhagem               grava o que de fato aconteceu — inclusive o recusado

ONDE ELE PARA (§80, §81, §82). No registro canônico. Ele NÃO escreve
pertinência de corpus, NÃO gera `events.parquet` e NÃO toca manifesto: isso é
o PR-04.4.2, e antecipá-lo faria eventos entrarem numa versão publicada sem
passar pelo gate que existe exatamente para isso.

A UNIDADE TRANSACIONAL É O LOTE, como no PR-04.2. Uma transação sobre cem mil
eventos seguraria locks por minutos e refaria tudo por causa de um; uma por
evento pagaria o custo de transação cem mil vezes.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, final

from sports_intelligence.domain.events.build import (
    EVENT_CANONICALIZER,
    EventBuildCounts,
    EventBuildRecord,
    EventBuildRecordStatus,
    counts_of,
)
from sports_intelligence.domain.events.records import HistoricalEventRecord
from sports_intelligence.domain.events.runs import CanonicalEventBuildRun
from sports_intelligence.domain.events.typing_map import EventTypeMapping
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.identity import DatasetId, MatchId, ProviderId
from sports_intelligence.domain.shared.provenance import LicenseClass
from sports_intelligence.historical.events.builder import CanonicalEventBuilder
from sports_intelligence.historical.events.eligibility import (
    EventEligibilityEvaluator,
    EventEligibilityPolicy,
)
from sports_intelligence.historical.events.pipeline import EventBatchCanonicalizer
from sports_intelligence.historical.events.references import EventReferenceReader
from sports_intelligence.ports.clock import ClockPort
from sports_intelligence.ports.repositories.events import (
    CanonicalEventBuildRunRepositoryPort,
    CanonicalEventWritePort,
    EventBuildRecordRepositoryPort,
)
from sports_intelligence.ports.repositories.resolution import (
    ProviderMappingRepositoryPort,
)
from sports_intelligence.ports.unit_of_work import UnitOfWorkPort

#: Quantos registros de evento por lote. Calibrado no §110: 1.000 fica entre o
#: throughput de 5.000 e o pico de memória de 250, e é o ponto em que nenhum
#: dos dois domina.
DEFAULT_EVENT_BATCH: int = 1_000

#: Quantas linhas de linhagem a saída carrega DE VOLTA para quem chamou.
#:
#: A LINHAGEM COMPLETA MORA NO REPOSITÓRIO, e é lá que ela é completa. O que
#: a saída traz é amostra de diagnóstico: acumular cem mil linhas na memória
#: para devolvê-las a um chamador que quase sempre só quer as contagens faria
#: o pico seguir o VOLUME DO ARQUIVO em vez do tamanho do lote (§69, §109).
#: Quando a amostra não cabe, `records_truncated` diz — uma amostra que se
#: apresenta como o todo é pior que amostra nenhuma.
LINEAGE_SAMPLE_LIMIT: int = 5_000


@final
@dataclass(frozen=True, slots=True)
class EventCanonicalizationOutput:
    run: CanonicalEventBuildRun
    #: UMA AMOSTRA da linhagem produzida — as primeiras `LINEAGE_SAMPLE_LIMIT`
    #: linhas —, para que quem chamou possa afirmar coisas sem reler o banco.
    #: Ela NÃO é o corpus (§80) e NÃO é a linhagem completa quando
    #: `records_truncated` é verdadeiro: essa está no repositório.
    records: tuple[EventBuildRecord, ...] = ()
    #: Se a execução produziu mais linhagem do que a amostra cabe. Quem
    #: precisa do total usa `run.counts`; quem precisa das linhas, o
    #: repositório.
    records_truncated: bool = False


@final
@dataclass(frozen=True, slots=True)
class RunHistoricalEventCanonicalization:
    """Do registro de evento ao `CanonicalMatchEvent` persistido."""

    mappings: ProviderMappingRepositoryPort
    events: CanonicalEventWritePort
    lineage: EventBuildRecordRepositoryPort
    runs: CanonicalEventBuildRunRepositoryPort
    clock: ClockPort
    types: EventTypeMapping
    policy: EventEligibilityPolicy
    uow: UnitOfWorkPort | None = None
    reader: EventReferenceReader | None = None
    builder: CanonicalEventBuilder = field(default_factory=CanonicalEventBuilder)

    async def execute(
        self,
        *,
        actor: Actor,
        dataset_id: DatasetId,
        provider_id: ProviderId,
        batches: AsyncIterator[Sequence[HistoricalEventRecord]],
        eligible_matches: frozenset[MatchId],
        license_class: LicenseClass,
        quality_run_id: str | None = None,
    ) -> EventCanonicalizationOutput:
        execucao = CanonicalEventBuildRun.start(
            dataset_id=dataset_id,
            provider_id=provider_id,
            scope=self.policy.scope,
            policy_version=self.policy.version,
            type_mapping_version=self.types.version,
            at=self.clock.now(),
            triggered_by=actor,
            quality_run_id=quality_run_id,
        )
        # A EXECUÇÃO É ABERTA ANTES DO PRIMEIRO EVENTO. A chave estrangeira
        # de `canonical_match_events` aponta para ela — e a ordem também é a
        # certa semanticamente: um fato gravado sem quem o produziu não tem
        # como ser explicado depois.
        execucao = await self.runs.create(execucao)
        leitor = self.reader or EventReferenceReader(mappings=self.mappings)
        canonicalizador = EventBatchCanonicalizer(
            evaluator=EventEligibilityEvaluator(policy=self.policy, types=self.types),
            builder=self.builder,
            build_run_id=execucao.id,
            ingested_at=self.clock.now(),
        )

        contagens = EventBuildCounts()
        amostra: list[EventBuildRecord] = []
        truncada = False
        try:
            async for lote in batches:
                if not lote:
                    continue
                referencias = await leitor.read(provider_id, lote)
                resultado = canonicalizador.canonicalize(
                    lote,
                    references=referencias,
                    eligible_matches=eligible_matches,
                    license_class=license_class,
                )
                linhagem = await self._persistir(resultado, build_run_id=execucao.id)
                # A AMOSTRA PARA DE CRESCER, a execução não. O lote já foi
                # persistido; segurá-lo aqui só serviria para devolvê-lo.
                if len(amostra) < LINEAGE_SAMPLE_LIMIT:
                    amostra.extend(linhagem[: LINEAGE_SAMPLE_LIMIT - len(amostra)])
                truncada = truncada or len(amostra) >= LINEAGE_SAMPLE_LIMIT
                contagens = contagens.merged_with(counts_of(linhagem, read=resultado.records_read))
        except Exception as erro:
            # A FALHA É GRAVADA, e não só levantada: uma execução que some sem
            # estado deixa «o que aconteceu com aquele arquivo» sem resposta.
            await self.runs.finish(
                execucao.fail(reason=f"{type(erro).__name__}: {erro}", at=self.clock.now())
            )
            raise

        concluida = execucao.complete(counts=contagens, at=self.clock.now())
        await self.runs.finish(concluida)
        return EventCanonicalizationOutput(
            run=concluida,
            records=tuple(amostra),
            records_truncated=truncada and contagens.records_read > len(amostra),
        )

    # ------------------------------------------------------------- o lote --

    async def _persistir(
        self, resultado: Any, *, build_run_id: str
    ) -> tuple[EventBuildRecord, ...]:
        """Escreve os eventos e grava a linhagem — nessa ordem, numa transação.

        A ORDEM É O §48 INTEIRO. A linhagem é escrita DEPOIS de a escrita
        canônica voltar, com o desfecho que ela devolveu: um `BUILT` gravado
        antes afirmaria ter construído um evento que a transação seguinte
        poderia não conseguir gravar.
        """
        async with _escopo(self.uow):
            desfechos = await self.events.persist_events(
                resultado.events,
                build_run_id=build_run_id,
                source_keys=resultado.source_keys,
            )
            # AS TRANSIÇÕES DE REVISÃO VÊM DEPOIS DA ESCRITA. Marcar o
            # predecessor como corrigido antes de o sucessor existir deixaria,
            # numa falha, um evento «corrigido» sem correção nenhuma.
            if resultado.superseded:
                await self.events.mark_superseded(resultado.superseded)
            if resultado.cancelled:
                await self.events.mark_cancelled(resultado.cancelled)

            # O DESFECHO REAL SUBSTITUI O PRESUMIDO. O canonicalizador disse
            # `BUILT`; o registro sabe se era reprocessamento, e é ele que
            # manda — afirmar `BUILT` sobre um evento que já existia seria a
            # declaração falsa do §66 do PR-04.2.
            linhagem = tuple(_com_desfecho(registro, desfechos) for registro in resultado.records)
            await self.lineage.append_many(linhagem)
        return linhagem


def _com_desfecho(
    record: EventBuildRecord,
    desfechos: Mapping[uuid.UUID, EventBuildRecordStatus],
) -> EventBuildRecord:
    """O status REAL do registro, vindo de quem escreveu.

    O canonicalizador diz `BUILT` porque construiu; só o registro canônico
    sabe se aquele evento já existia — e afirmar `BUILT` sobre um
    reprocessamento seria a declaração falsa do §66 do PR-04.2.
    """
    if record.event_id is None:
        return record
    real = desfechos.get(record.event_id)
    if real is None or real is record.status:
        return record
    return replace(record, status=real)


def _escopo(uow: UnitOfWorkPort | None) -> Any:
    """A transação do lote, ou um escopo vazio quando não há unidade.

    SEM `uow` O CÓDIGO CONTINUA CORRETO e perde a atomicidade do lote — que é
    o caso dos testes de unidade com duplos. O que ele não faz é fingir que a
    transação existe.
    """
    if uow is not None:
        return uow
    return _SemTransacao()


@final
class _SemTransacao:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


__all__ = [
    "DEFAULT_EVENT_BATCH",
    "EVENT_CANONICALIZER",
    "EventCanonicalizationOutput",
    "RunHistoricalEventCanonicalization",
]
