"""A composição da resolução e da fusão — e a orquestração que sobra.

POR QUE UM ARQUIVO À PARTE DE `composition.py`. Aquele monta o grafo do
intake, que a CLI e a API já compartilham. Este acrescenta o grafo do PR-03 e
mais duas funções que NÃO são caso de uso: elas leem o arquivo bruto,
materializam um temporário e alimentam o caso de uso com lotes.

Essa leitura é trabalho de BORDA — envolve object store, arquivo temporário e
formato — e enfiá-la dentro de `RunIdentityResolution` faria o caso de uso
conhecer o object store para poder resolver identidade. Deixá-la aqui mantém o
caso de uso puro sobre lotes, que é o que o torna testável sem infraestrutura.

`apps/composition.py` e `apps/_shared.py` continuam sendo as únicas exceções
ao teste de arquitetura; este arquivo entra na lista pelo mesmo motivo: ele É
a borda.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.adapters.postgres.resolution import (
    PostgresCanonicalRegistry,
    PostgresEntityAliasRepository,
    PostgresFusionRunRepository,
    PostgresProviderMappingRepository,
    PostgresResolutionDecisionRepository,
    PostgresResolutionRunRepository,
    PostgresReviewQueueRepository,
    PostgresSourceMappingRepository,
)
from sports_intelligence.application.use_cases.fusion import (
    BuildResolvedRecords,
    GetFusionRun,
    ListFusionConflicts,
    RunFusion,
)
from sports_intelligence.application.use_cases.resolution import (
    GetResolutionRun,
    ListResolutionDecisions,
    ListResolutionReviewItems,
    RegisterSourceMapping,
    ResolveReviewItem,
    RunIdentityResolution,
)
from sports_intelligence.domain.datasets.models import Dataset
from sports_intelligence.domain.fusion.models import ResolvedSourceRecord
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.sources.records import DatasetRecordRef, SourceBatch
from sports_intelligence.ingestion.historical.reader import ReadContext, SourceReader
from sports_intelligence.ingestion.normalization.names import NameNormalizer
from sports_intelligence.ingestion.resolution.resolvers import ResolverBundle
from sports_intelligence.ports.raw_dataset_archive import RawDatasetArchivePort


@final
@dataclass(frozen=True, slots=True)
class ResolutionContainer:
    """O grafo do PR-03, montado uma vez por processo."""

    source_mappings: PostgresSourceMappingRepository
    resolution_runs: PostgresResolutionRunRepository
    decisions: PostgresResolutionDecisionRepository
    review: PostgresReviewQueueRepository
    fusion_runs: PostgresFusionRunRepository
    resolvers: ResolverBundle
    reader: SourceReader

    register_mapping: RegisterSourceMapping
    run_resolution: RunIdentityResolution
    resolve_review: ResolveReviewItem
    get_resolution_run: GetResolutionRun
    list_decisions: ListResolutionDecisions
    list_review: ListResolutionReviewItems
    build_resolved: BuildResolvedRecords
    run_fusion: RunFusion
    get_fusion_run: GetFusionRun
    list_conflicts: ListFusionConflicts


def build_resolution_container(
    *,
    database: Database,
    archive: RawDatasetArchivePort,
    datasets: Any,
    clock: Any,
    audit: Any,
    publisher: Any,
    batch_size: int = 2_000,
) -> ResolutionContainer:
    normalizador = NameNormalizer()
    resolvers = ResolverBundle.build(normalizador)

    source_mappings = PostgresSourceMappingRepository(database)
    registry = PostgresCanonicalRegistry(database)
    provider_mappings = PostgresProviderMappingRepository(database)
    aliases = PostgresEntityAliasRepository(database)
    runs = PostgresResolutionRunRepository(database)
    decisions = PostgresResolutionDecisionRepository(database)
    review = PostgresReviewQueueRepository(database)
    fusion_runs = PostgresFusionRunRepository(database)

    return ResolutionContainer(
        source_mappings=source_mappings,
        resolution_runs=runs,
        decisions=decisions,
        review=review,
        fusion_runs=fusion_runs,
        resolvers=resolvers,
        reader=SourceReader(batch_size=batch_size),
        register_mapping=RegisterSourceMapping(
            datasets=datasets, mappings=source_mappings, clock=clock, audit=audit
        ),
        run_resolution=RunIdentityResolution(
            datasets=datasets,
            source_mappings=source_mappings,
            registry=registry,
            provider_mappings=provider_mappings,
            aliases=aliases,
            runs=runs,
            decisions=decisions,
            review=review,
            resolvers=resolvers,
            clock=clock,
            audit=audit,
            publisher=publisher,
            batch_size=batch_size,
        ),
        resolve_review=ResolveReviewItem(
            review=review,
            decisions=decisions,
            provider_mappings=provider_mappings,
            aliases=aliases,
            clock=clock,
            audit=audit,
        ),
        get_resolution_run=GetResolutionRun(runs=runs),
        list_decisions=ListResolutionDecisions(decisions=decisions),
        list_review=ListResolutionReviewItems(review=review),
        build_resolved=BuildResolvedRecords(decisions=decisions),
        run_fusion=RunFusion(
            resolution_runs=runs,
            decisions=decisions,
            fusion_runs=fusion_runs,
            clock=clock,
            audit=audit,
            publisher=publisher,
        ),
        get_fusion_run=GetFusionRun(fusion_runs=fusion_runs),
        list_conflicts=ListFusionConflicts(fusion_runs=fusion_runs),
    )


async def read_batches(
    dataset: Dataset,
    *,
    archive: RawDatasetArchivePort,
    reader: SourceReader,
    mapping: Any,
    manifest_fingerprint: Any,
) -> AsyncIterator[SourceBatch]:
    """Materializa cada arquivo do dataset e devolve os lotes.

    MATERIALIZAÇÃO EM DISCO, pelo mesmo motivo do PR-02: o Parquet exige
    acesso aleatório e não há como ler seu rodapé a partir de um stream
    sequencial. O custo é disco e uma leitura extra; o pico de MEMÓRIA
    continua sendo o de um lote.

    O temporário é removido no `finally`, inclusive quando a leitura levanta.

    ENTREGA LOTE A LOTE, e não uma lista pronta (§41 a §43). A versão anterior
    devolvia `list[SourceBatch]` e o chamador materializava o dataset inteiro
    antes de a resolução começar — era o que fazia o pico de cem mil registros
    ser 224 MB em vez do tamanho de um lote. Como gerador, o arquivo temporário
    de cada arquivo do dataset também vive só enquanto ele está sendo lido.
    """
    for arquivo in dataset.stored_files:
        caminho: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="sie-resolve-",
                suffix=arquivo.format.canonical_extension,
                delete=False,
            ) as destino:
                caminho = Path(destino.name)
                async for bloco in archive.open(arquivo):
                    destino.write(bloco)
            contexto = ReadContext(
                dataset_id=dataset.id,
                dataset_version=dataset.version,
                file_id=str(arquivo.id),
                manifest_fingerprint=manifest_fingerprint,
                provenance=arquivo.provenance,
                mapping=mapping,
            )
            for lote in reader.read(caminho, file_format=arquivo.format, context=contexto):
                yield lote
        finally:
            if caminho is not None:
                caminho.unlink(missing_ok=True)


async def to_resolved_records(
    batches: AsyncIterator[SourceBatch],
    *,
    resolved: dict[str, str],
    provider_source_type: SourceType,
    license_class: LicenseClass,
) -> AsyncIterator[ResolvedSourceRecord]:
    """Converte lotes em registros resolvidos, filtrando por decisão.

    A CHAVE É `record_ref → "entidade|decisão"`, e a decisão viaja junto
    porque `ResolvedSourceRecord` não se constrói sem ela. É assim que a
    ordem obrigatória — identidade, depois fusão — vira assinatura em vez de
    convenção (ADR-0022).
    """
    async for lote in batches:
        for registro in lote.records:
            chave = str(registro.ref)
            achado = resolved.get(chave)
            if achado is None:
                continue
            entidade, decisao = achado.split("|", 1)
            yield (
                ResolvedSourceRecord(
                    record_ref=DatasetRecordRef.parse(chave),
                    provider_id=registro.provider_id,
                    source_type=provider_source_type,
                    license_class=license_class,
                    canonical_entity_id=MatchId.parse(entidade),
                    resolution_decision_id=decisao,
                    values={
                        papel: texto
                        for papel in registro.values
                        if (texto := registro.text_of(papel)) is not None
                    },
                )
            )


async def resolved_match_map(
    decisions: PostgresResolutionDecisionRepository, run_ids: Sequence[str]
) -> dict[str, str]:
    """Junta os mapas de várias execuções.

    QUANDO DUAS EXECUÇÕES RESOLVEM O MESMO REGISTRO, a última declarada
    vence. É determinístico porque a ordem das execuções vem da requisição —
    e é o comportamento certo: reprocessar uma fonte com resolver melhor deve
    poder substituir a resolução anterior daquela fonte na fusão.
    """
    juntos: dict[str, str] = {}
    for run_id in run_ids:
        juntos.update(await decisions.resolved_entities_of_run(run_id, SubjectType.MATCH))
    return juntos
