"""A composição do PR-04.2 e a BORDA que alimenta os dois casos de uso.

POR QUE UM ARQUIVO À PARTE, de novo. `composition.py` monta o intake e
`resolution_composition.py` monta o PR-03. Este monta a avaliação de qualidade
e a construção canônica, mais as duas funções que NÃO são caso de uso: elas
releem a fonte, remontam os candidatos fundidos e entregam lotes.

ESSA LEITURA É TRABALHO DE BORDA, pelo mesmo motivo do PR-03: ela envolve
object store, arquivo temporário e formato. Com ela dentro do caso de uso,
avaliar qualidade exigiria um object store configurado — e o caso de uso
deixaria de ser testável sem infraestrutura.

POR QUE OS CANDIDATOS SÃO REMONTADOS E NÃO LIDOS DO BANCO. `fused_candidates`
guarda a forma CANÔNICA da saída — a que produziu a impressão —, e ela não
carrega a licença por contribuição nem o tipo de fonte, que a avaliação de
licença por família precisa. Remontar a partir do mesmo caminho que a fusão
usou garante que o que se avalia é exatamente o que ela produziu; reconstruir
a partir das tabelas normalizadas correria o risco de uma forma ligeiramente
diferente, e a impressão deixaria de conferir.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, final

from apps.resolution_composition import (
    ResolutionContainer,
    read_batches,
    resolved_match_map,
    to_resolved_records,
)
from sports_intelligence.adapters.postgres.canonical import (
    PostgresCanonicalBuildRecordRepository,
    PostgresCanonicalBuildRunRepository,
    PostgresCanonicalIdentityReader,
    PostgresCanonicalRegistryWriter,
)
from sports_intelligence.adapters.postgres.database import Database, PostgresUnitOfWork
from sports_intelligence.adapters.postgres.quality import (
    PostgresQualityAssessmentRepository,
    PostgresQualityRunRepository,
)
from sports_intelligence.application.use_cases.canonical_build import (
    BuildCandidateBatch,
    GetCanonicalBuildRun,
    GetMatchLineage,
    RunCanonicalBuild,
)
from sports_intelligence.application.use_cases.quality import (
    GetQualityRun,
    ListQualityAssessments,
    RunHistoricalQualityAssessment,
)
from sports_intelligence.domain.build.policy import (
    DEFAULT_COMMERCIAL_BUILD_POLICY,
    DEFAULT_RESEARCH_BUILD_POLICY,
    CanonicalBuildPolicy,
)
from sports_intelligence.domain.fusion.models import FusionGroup, ResolvedSourceRecord
from sports_intelligence.domain.fusion.runs import FusedMatchCandidate
from sports_intelligence.domain.quality.policy import (
    DEFAULT_QUALITY_POLICY,
    HistoricalQualityPolicy,
)
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.historical.quality.assessor import CandidateEvidence
from sports_intelligence.ingestion.fusion.engine import FusionEngine, group_by_identity
from sports_intelligence.ports.raw_dataset_archive import RawDatasetArchivePort
from sports_intelligence.ports.repositories.dataset_registry import (
    DatasetRepositoryPort,
)

#: Quantas partidas por lote de avaliação e de construção. O mesmo raciocínio
#: do lote de resolução: troca memória por idas ao banco, e o ponto certo
#: depende da máquina. Quinhentas é o valor que o PR-03.1 calibrou.
DEFAULT_BUILD_BATCH_SIZE: int = 500


@final
@dataclass(frozen=True, slots=True)
class BuildContainer:
    """O grafo do PR-04.2, montado uma vez por processo."""

    quality_runs: PostgresQualityRunRepository
    assessments: PostgresQualityAssessmentRepository
    identities: PostgresCanonicalIdentityReader
    registry_writer: PostgresCanonicalRegistryWriter
    build_runs: PostgresCanonicalBuildRunRepository
    build_records: PostgresCanonicalBuildRecordRepository

    run_quality: RunHistoricalQualityAssessment
    get_quality_run: GetQualityRun
    list_assessments: ListQualityAssessments
    #: DOIS BUILDS, e não um com parâmetro (§18, §86). A mesma avaliação sob a
    #: política de pesquisa e sob a comercial produz corpus diferentes, e os
    #: dois coexistem — ter os dois montados torna a diferença visível na
    #: composição em vez de escondida num argumento.
    run_research_build: RunCanonicalBuild
    run_commercial_build: RunCanonicalBuild
    get_build_run: GetCanonicalBuildRun
    get_lineage: GetMatchLineage

    def build_for(self, policy: CanonicalBuildPolicy) -> RunCanonicalBuild:
        """O caso de uso de uma política qualquer — para testes e para o
        PR-04.3, que vai receber a política pela requisição."""
        from dataclasses import replace

        return replace(self.run_research_build, policy=policy)


def build_build_container(
    *,
    database: Database,
    resolution: ResolutionContainer,
    clock: Any,
    audit: Any,
    quality_policy: HistoricalQualityPolicy = DEFAULT_QUALITY_POLICY,
) -> BuildContainer:
    quality_runs = PostgresQualityRunRepository(database)
    assessments = PostgresQualityAssessmentRepository(database)
    identities = PostgresCanonicalIdentityReader(database)
    escritor = PostgresCanonicalRegistryWriter(database)
    build_runs = PostgresCanonicalBuildRunRepository(database)
    build_records = PostgresCanonicalBuildRecordRepository(database)

    def montar_build(policy: CanonicalBuildPolicy) -> RunCanonicalBuild:
        return RunCanonicalBuild(
            quality_runs=quality_runs,
            assessments=assessments,
            identities=identities,
            registry=escritor,
            build_runs=build_runs,
            records=build_records,
            clock=clock,
            audit=audit,
            uow=PostgresUnitOfWork(database),
            policy=policy,
        )

    return BuildContainer(
        quality_runs=quality_runs,
        assessments=assessments,
        identities=identities,
        registry_writer=escritor,
        build_runs=build_runs,
        build_records=build_records,
        run_quality=RunHistoricalQualityAssessment(
            fusion_runs=resolution.fusion_runs,
            quality_runs=quality_runs,
            assessments=assessments,
            clock=clock,
            audit=audit,
            policy=quality_policy,
        ),
        get_quality_run=GetQualityRun(quality_runs=quality_runs),
        list_assessments=ListQualityAssessments(
            quality_runs=quality_runs, assessments=assessments
        ),
        run_research_build=montar_build(DEFAULT_RESEARCH_BUILD_POLICY),
        run_commercial_build=montar_build(DEFAULT_COMMERCIAL_BUILD_POLICY),
        get_build_run=GetCanonicalBuildRun(build_runs=build_runs),
        get_lineage=GetMatchLineage(records=build_records),
    )


# ============================================================== a borda ==


async def rebuild_fusion_output(
    *,
    resolution: ResolutionContainer,
    datasets: DatasetRepositoryPort,
    archive: RawDatasetArchivePort,
    resolution_run_ids: Sequence[str],
) -> tuple[tuple[FusionGroup, ...], tuple[FusedMatchCandidate, ...]]:
    """Relê as fontes e reconstrói grupos e candidatos da fusão.

    O MESMO CAMINHO QUE A FUSÃO USOU, e é o ponto: o que a qualidade avalia
    precisa ser exatamente o que a fusão produziu. A fusão é determinística
    sobre a mesma entrada e a mesma política, então reexecutá-la sobre os
    mesmos registros resolvidos devolve os mesmos candidatos — com a licença
    por contribuição que a forma canônica gravada não carrega.

    ELE MATERIALIZA OS GRUPOS EM MEMÓRIA, e é o limite conhecido desta fase:
    o número de grupos é o número de partidas, e cinco mil partidas cabem. O
    corpus completo do PR-04.3 vai precisar disto por temporada — está
    registrado como dívida, não como esquecimento.
    """
    registros: list[ResolvedSourceRecord] = []
    resolvidos = await resolved_match_map(resolution.decisions, resolution_run_ids)
    for run_id in resolution_run_ids:
        execucao = await resolution.get_resolution_run.execute(run_id)
        dataset = await datasets.by_id(execucao.dataset_id)
        if dataset is None:
            continue
        mapeamento = await resolution.source_mappings.active_for(dataset.id)
        if mapeamento is None:
            continue
        lotes = read_batches(
            dataset,
            archive=archive,
            reader=resolution.reader,
            mapping=mapeamento,
            manifest_fingerprint=execucao.manifest_fingerprint,
        )
        async for registro in to_resolved_records(
            lotes,
            resolved=resolvidos,
            provider_source_type=dataset.source.source_type,
            license_class=dataset.source.license_class,
        ):
            registros.append(registro)

    grupos, _ = group_by_identity(tuple(registros))
    motor = FusionEngine(resolution.run_fusion.policy)
    return grupos, tuple(motor.fuse(grupo) for grupo in grupos)


async def evidence_batches(
    *,
    resolution: ResolutionContainer,
    groups: Sequence[FusionGroup],
    candidates: Sequence[FusedMatchCandidate],
    resolution_run_ids: Sequence[str],
    batch_size: int = DEFAULT_BUILD_BATCH_SIZE,
) -> AsyncIterator[Sequence[CandidateEvidence]]:
    """Os lotes de evidência que a avaliação consome.

    A CONFIANÇA POR TIPO VEM DAS DECISÕES REAIS (§13) e é carregada POR LOTE,
    numa consulta — não por partida. É o mesmo desenho do carregamento de
    candidatos do PR-03: uma ida ao banco para as N linhas do lote.
    """
    por_grupo = {g.id: g for g in groups}
    ordenados = sorted(candidates, key=lambda c: str(c.canonical_match_id))

    for inicio in range(0, len(ordenados), batch_size):
        bloco = ordenados[inicio : inicio + batch_size]
        grupos_do_bloco = [
            grupo
            for candidato in bloco
            if (grupo := por_grupo.get(candidato.group_id)) is not None
        ]
        refs = [
            str(registro.record_ref)
            for grupo in grupos_do_bloco
            for registro in grupo.records
        ]
        confiancas = await resolution.decisions.confidences_for_records(
            resolution_run_ids, refs
        )
        yield [
            CandidateEvidence(
                candidate=candidato,
                group=grupo,
                identity_confidences=_confianca_do_grupo(grupo, confiancas),
            )
            for candidato in bloco
            if (grupo := por_grupo.get(candidato.group_id)) is not None
        ]


async def candidate_batches(
    *,
    candidates: Sequence[FusedMatchCandidate],
    batch_size: int = DEFAULT_BUILD_BATCH_SIZE,
) -> AsyncIterator[BuildCandidateBatch]:
    """Os lotes de candidatos que a construção consome.

    ORDENADOS POR PARTIDA, e não pela ordem de processamento: duas execuções
    que montem os mesmos candidatos em ordens diferentes precisam produzir a
    mesma impressão, senão ela não prova determinismo nenhum (§53).
    """
    ordenados = sorted(candidates, key=lambda c: str(c.canonical_match_id))
    for inicio in range(0, len(ordenados), batch_size):
        yield BuildCandidateBatch(
            candidates=tuple(ordenados[inicio : inicio + batch_size])
        )


def _confianca_do_grupo(
    group: FusionGroup, por_registro: dict[str, dict[SubjectType, float]]
) -> dict[SubjectType, float]:
    """A confiança de cada tipo de identidade DESTE grupo.

    O MÍNIMO ENTRE AS FONTES, e não a média nem a máxima. Um grupo montado com
    uma fonte cuja partida resolveu em 0,98 e outra em 0,72 tem uma
    contribuição fraca dentro dele, e a média a esconderia — que é exatamente
    o que o §13 proíbe, um nível acima.
    """
    juntas: dict[SubjectType, float] = {}
    for registro in group.records:
        for sujeito, valor in por_registro.get(str(registro.record_ref), {}).items():
            atual = juntas.get(sujeito)
            juntas[sujeito] = valor if atual is None else min(atual, valor)
    return juntas
