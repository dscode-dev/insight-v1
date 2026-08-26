"""Os repositórios do dataset normalizado, em SQL escrito à mão.

O QUE É PARTICULAR DESTE ARQUIVO:

TRÊS IMPRESSÕES DE CONTEÚDO, E TRÊS COLUNAS. A tentação é gravar só a global e
derivar as outras duas na leitura — e não dá: derivar a de referência exigiria
reler as linhas. A do meio é a que responde «a base de comparação mudou entre
estas duas publicações?», e sem coluna própria a resposta seria uma varredura.

A REPRESENTAÇÃO É RECONSTRUÍDA DO `jsonb`, e as colunas são CONFERIDAS contra
ele — o mesmo desenho do `spec` do dataset cru. As colunas existem para filtrar
(«quais versões são comparáveis com esta?»), e um índice que apontasse para uma
impressão diferente da do documento tornaria essa consulta silenciosamente
errada.

O CONTRATO 1:1 É CONFERIDO NO BANCO E NO TIPO. O `CHECK` da migration recusa
publicar com contagem diferente da crua; o `__post_init__` do domínio recusa
construir o objeto. Uma guarda só cobriria o caminho por onde ela passa.

A TRANSIÇÃO É `UPDATE ... WHERE status = $esperado`, como nos outros dois
registros: é essa cláusula que serializa duas construções simultâneas sem lock
distribuído.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any, Final, final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.dataset.split import DatasetSplit, SplitCounts
from sports_intelligence.domain.features.normalized.manifest import (
    ArtifactMapEntry,
    NormalizationAvailabilitySummary,
    NormalizedFeatureDatasetManifest,
    NormalizedObjectRef,
)
from sports_intelligence.domain.features.normalized.plan import NormalizationPlan
from sports_intelligence.domain.features.normalized.versions import (
    NormalizedFeatureDatasetBuildRun,
    NormalizedFeatureRepresentationSpec,
    NormalizedHistoricalFeatureDataset,
    NormalizedHistoricalFeatureDatasetVersion,
)
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import ConflictError, NotFoundError
from sports_intelligence.domain.shared.temporal import Instant, instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

_COLUNAS_DATASET: Final[str] = (
    "id, name, source_dataset_id, description, created_at, created_by, created_by_kind"
)

_COLUNAS_VERSAO: Final[str] = """
    id, dataset_id, version_major, version_minor, status,
    source_version_id, source_version_major, source_version_minor,
    source_raw_content_fingerprint, source_row_count,
    space_fingerprint, plan_name, plan_version, plan_fingerprint,
    artifact_set_id, artifact_set_fingerprint, representation_fingerprint,
    representation,
    normalized_content_fingerprint, normalized_reference_content_fingerprint,
    normalized_evaluation_content_fingerprint,
    manifest_id, match_count, row_count,
    reference_matches, evaluation_matches, reference_rows, evaluation_rows,
    created_at, created_by, created_by_kind, completed_at, failure_reason,
    superseded_by
"""

_COLUNAS_EXECUCAO: Final[str] = """
    id, version_id, status, started_at, started_by, started_by_kind,
    finished_at, rows_read, rows_written, objects_written, bytes_written,
    artifact_unavailable_cells, failure_reason
"""

_COLUNAS_OBJETO: Final[str] = (
    "object_key, split, competition, season, sha256, size_bytes, row_count, "
    "match_count, source_object_key, content_type"
)

_COLUNAS_MANIFESTO: Final[str] = (
    "id, version_id, schema_version, document, normalized_content_fingerprint, "
    "manifest_sha256, object_key, created_at"
)


@final
class PostgresNormalizedFeatureDatasetRepository:
    """Identidade e versões da representação normalizada."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_dataset(
        self,
        *,
        name: str,
        source_dataset_id: str,
        at: Instant,
        created_by: Actor,
        description: str | None = None,
    ) -> NormalizedHistoricalFeatureDataset:
        dataset = NormalizedHistoricalFeatureDataset.create(
            name=name,
            source_dataset_id=source_dataset_id,
            at=at,
            created_by=created_by,
            description=description,
        )
        async with self._db.acquire() as conexao:
            try:
                await conexao.execute(
                    f"""
                    INSERT INTO normalized_feature_datasets ({_COLUNAS_DATASET})
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    uuid.UUID(dataset.id),
                    dataset.name,
                    uuid.UUID(source_dataset_id),
                    dataset.description,
                    dataset.created_at,
                    dataset.created_by.id,
                    dataset.created_by.kind.value,
                )
            except Exception as erro:  # asyncpg.UniqueViolationError
                if "nfd_nome_unico" not in str(erro):
                    raise
                raise ConflictError(
                    f"já existe um dataset normalizado chamado {dataset.name!r}",
                    context={"name": dataset.name},
                ) from erro
        return dataset

    async def dataset_by_name(self, name: str) -> NormalizedHistoricalFeatureDataset | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_DATASET} FROM normalized_feature_datasets WHERE name = $1",
                name,
            )
        return None if linha is None else _para_dataset(linha)

    async def dataset_by_id(self, dataset_id: str) -> NormalizedHistoricalFeatureDataset | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_DATASET} FROM normalized_feature_datasets WHERE id = $1",
                uuid.UUID(dataset_id),
            )
        return None if linha is None else _para_dataset(linha)

    async def create_version(
        self,
        *,
        dataset_id: str,
        version: DatasetVersion,
        source_version_id: str,
        source_version: DatasetVersion,
        source_raw_content_fingerprint: ContentHash,
        source_row_count: int,
        representation: NormalizedFeatureRepresentationSpec,
        at: Instant,
        created_by: Actor,
    ) -> NormalizedHistoricalFeatureDatasetVersion:
        criada = NormalizedHistoricalFeatureDatasetVersion.draft(
            dataset_id=dataset_id,
            version=version,
            source_version_id=source_version_id,
            source_version=source_version,
            source_raw_content_fingerprint=source_raw_content_fingerprint,
            source_row_count=source_row_count,
            representation=representation,
            at=at,
            created_by=created_by,
        )
        async with self._db.acquire() as conexao:
            try:
                await conexao.execute(
                    """
                    INSERT INTO normalized_feature_dataset_versions (
                        id, dataset_id, version_major, version_minor, status,
                        source_version_id, source_version_major, source_version_minor,
                        source_raw_content_fingerprint, source_row_count,
                        space_fingerprint, plan_name, plan_version, plan_fingerprint,
                        artifact_set_id, artifact_set_fingerprint,
                        representation_fingerprint, representation,
                        created_at, created_by, created_by_kind
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                            $13, $14, $15, $16, $17, $18, $19, $20, $21)
                    """,
                    uuid.UUID(criada.id),
                    uuid.UUID(dataset_id),
                    version.major,
                    version.minor,
                    criada.status.value,
                    uuid.UUID(source_version_id),
                    source_version.major,
                    source_version.minor,
                    source_raw_content_fingerprint.value,
                    source_row_count,
                    representation.space_fingerprint,
                    representation.plan_name,
                    representation.plan_version,
                    representation.plan_fingerprint,
                    uuid.UUID(representation.artifact_set_id),
                    representation.artifact_set_fingerprint,
                    representation.fingerprint,
                    json.dumps(representation.as_document(), sort_keys=True),
                    at,
                    created_by.id,
                    created_by.kind.value,
                )
            except Exception as erro:
                if "nfdv_versao_unica" not in str(erro):
                    raise
                raise ConflictError(
                    f"a versão {version} deste dataset normalizado já existe",
                    context={"version": str(version)},
                ) from erro
        return criada

    async def version_by_id(
        self, version_id: str
    ) -> NormalizedHistoricalFeatureDatasetVersion | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_VERSAO} FROM normalized_feature_dataset_versions WHERE id = $1",
                uuid.UUID(version_id),
            )
        return None if linha is None else _para_versao(linha)

    async def version_of(
        self, dataset_id: str, version: DatasetVersion
    ) -> NormalizedHistoricalFeatureDatasetVersion | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_VERSAO} FROM normalized_feature_dataset_versions "
                "WHERE dataset_id = $1 AND version_major = $2 AND version_minor = $3",
                uuid.UUID(dataset_id),
                version.major,
                version.minor,
            )
        return None if linha is None else _para_versao(linha)

    async def transition(
        self,
        version_id: str,
        *,
        target: DatasetVersionStatus,
        at: Instant,
        normalized_content_fingerprint: ContentHash | None = None,
        normalized_reference_content_fingerprint: ContentHash | None = None,
        normalized_evaluation_content_fingerprint: ContentHash | None = None,
        manifest_id: str | None = None,
        match_count: int | None = None,
        row_count: int | None = None,
        counts: SplitCounts | None = None,
        failure_reason: str | None = None,
        superseded_by: str | None = None,
    ) -> NormalizedHistoricalFeatureDatasetVersion:
        atual = await self.version_by_id(version_id)
        if atual is None:
            raise NotFoundError(
                f"a versão normalizada {version_id} não existe",
                context={"version_id": version_id},
            )
        atual.require_transition(target)
        # `None` SIGNIFICA «NÃO MEXA», e não «apague». Uma transição para READY
        # não reenvia contagens, e tratá-las como zero apagaria o que a
        # construção contou.
        movida = replace(
            atual,
            status=target,
            normalized_content_fingerprint=(
                atual.normalized_content_fingerprint
                if normalized_content_fingerprint is None
                else normalized_content_fingerprint
            ),
            normalized_reference_content_fingerprint=(
                atual.normalized_reference_content_fingerprint
                if normalized_reference_content_fingerprint is None
                else normalized_reference_content_fingerprint
            ),
            normalized_evaluation_content_fingerprint=(
                atual.normalized_evaluation_content_fingerprint
                if normalized_evaluation_content_fingerprint is None
                else normalized_evaluation_content_fingerprint
            ),
            manifest_id=atual.manifest_id if manifest_id is None else manifest_id,
            match_count=atual.match_count if match_count is None else match_count,
            row_count=atual.row_count if row_count is None else row_count,
            counts=atual.counts if counts is None else counts,
            completed_at=at if target.is_terminal else atual.completed_at,
            failure_reason=(atual.failure_reason if failure_reason is None else failure_reason),
            superseded_by=(atual.superseded_by if superseded_by is None else superseded_by),
        )
        async with self._db.acquire() as conexao:
            resultado = await conexao.execute(
                """
                UPDATE normalized_feature_dataset_versions
                SET status = $2,
                    normalized_content_fingerprint = $3,
                    normalized_reference_content_fingerprint = $4,
                    normalized_evaluation_content_fingerprint = $5,
                    manifest_id = $6,
                    match_count = $7,
                    row_count = $8,
                    reference_matches = $9,
                    evaluation_matches = $10,
                    reference_rows = $11,
                    evaluation_rows = $12,
                    completed_at = $13,
                    failure_reason = $14,
                    superseded_by = $15
                WHERE id = $1 AND status = $16
                """,
                uuid.UUID(version_id),
                movida.status.value,
                _texto(movida.normalized_content_fingerprint),
                _texto(movida.normalized_reference_content_fingerprint),
                _texto(movida.normalized_evaluation_content_fingerprint),
                None if movida.manifest_id is None else uuid.UUID(movida.manifest_id),
                movida.match_count,
                movida.row_count,
                movida.counts.reference_matches,
                movida.counts.evaluation_matches,
                movida.counts.reference_rows,
                movida.counts.evaluation_rows,
                movida.completed_at,
                movida.failure_reason,
                None if movida.superseded_by is None else uuid.UUID(movida.superseded_by),
                atual.status.value,
            )
        if _linhas_afetadas(resultado) != 1:
            raise ConflictError(
                f"a versão normalizada {version_id} não estava mais em {atual.status} "
                "quando a transição foi aplicada: outra execução a moveu",
                context={"expected": atual.status.value, "target": target.value},
            )
        return movida

    async def list_versions(
        self,
        dataset_id: str,
        *,
        status: DatasetVersionStatus | None = None,
        limit: int = 50,
    ) -> Sequence[NormalizedHistoricalFeatureDatasetVersion]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"""
                SELECT {_COLUNAS_VERSAO}
                FROM normalized_feature_dataset_versions
                WHERE dataset_id = $1 AND ($2::text IS NULL OR status = $2)
                ORDER BY version_major DESC, version_minor DESC
                LIMIT $3
                """,
                uuid.UUID(dataset_id),
                None if status is None else status.value,
                limit,
            )
        return [_para_versao(linha) for linha in linhas]

    async def latest_ready(
        self, dataset_id: str
    ) -> NormalizedHistoricalFeatureDatasetVersion | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"""
                SELECT {_COLUNAS_VERSAO}
                FROM normalized_feature_dataset_versions
                WHERE dataset_id = $1 AND status = 'READY'
                ORDER BY version_major DESC, version_minor DESC
                LIMIT 1
                """,
                uuid.UUID(dataset_id),
            )
        return None if linha is None else _para_versao(linha)

    async def versions_from_artifact_set(
        self, artifact_set_id: str, *, limit: int = 50
    ) -> Sequence[NormalizedHistoricalFeatureDatasetVersion]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"""
                SELECT {_COLUNAS_VERSAO}
                FROM normalized_feature_dataset_versions
                WHERE artifact_set_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                uuid.UUID(artifact_set_id),
                limit,
            )
        return [_para_versao(linha) for linha in linhas]


@final
class PostgresNormalizedDatasetBuildRepository:
    """Rastros de execução, objetos e manifesto."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def start_run(
        self, *, version_id: str, at: Instant, started_by: Actor
    ) -> NormalizedFeatureDatasetBuildRun:
        execucao = NormalizedFeatureDatasetBuildRun.start(
            version_id=version_id, at=at, started_by=started_by
        )
        async with self._db.acquire() as conexao:
            await conexao.execute(
                """
                INSERT INTO normalized_feature_dataset_build_runs (
                    id, version_id, status, started_at, started_by, started_by_kind
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                uuid.UUID(execucao.id),
                uuid.UUID(version_id),
                execucao.status.value,
                at,
                started_by.id,
                started_by.kind.value,
            )
        return execucao

    async def finish_run(
        self,
        run_id: str,
        *,
        status: DatasetVersionStatus,
        at: Instant,
        rows_read: int = 0,
        rows_written: int = 0,
        objects_written: int = 0,
        bytes_written: int = 0,
        artifact_unavailable_cells: int = 0,
        failure_reason: str | None = None,
    ) -> NormalizedFeatureDatasetBuildRun:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"""
                UPDATE normalized_feature_dataset_build_runs
                SET status = $2, finished_at = $3, rows_read = $4,
                    rows_written = $5, objects_written = $6, bytes_written = $7,
                    artifact_unavailable_cells = $8, failure_reason = $9
                WHERE id = $1
                RETURNING {_COLUNAS_EXECUCAO}
                """,
                uuid.UUID(run_id),
                status.value,
                at,
                rows_read,
                rows_written,
                objects_written,
                bytes_written,
                artifact_unavailable_cells,
                failure_reason,
            )
        if linha is None:
            raise NotFoundError(
                f"a execução de construção normalizada {run_id} não existe",
                context={"run_id": run_id},
            )
        return _para_execucao(linha)

    async def runs_of(
        self, version_id: str, *, limit: int = 20
    ) -> Sequence[NormalizedFeatureDatasetBuildRun]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"""
                SELECT {_COLUNAS_EXECUCAO}
                FROM normalized_feature_dataset_build_runs
                WHERE version_id = $1
                ORDER BY started_at DESC
                LIMIT $2
                """,
                uuid.UUID(version_id),
                limit,
            )
        return [_para_execucao(linha) for linha in linhas]

    async def record_objects(self, version_id: str, objects: Sequence[NormalizedObjectRef]) -> int:
        if not objects:
            return 0
        async with self._db.acquire() as conexao:
            await conexao.executemany(
                """
                INSERT INTO normalized_feature_objects (
                    version_id, object_key, split, competition, season, sha256,
                    size_bytes, row_count, match_count, source_object_key, content_type
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (version_id, object_key) DO UPDATE
                SET sha256 = EXCLUDED.sha256,
                    size_bytes = EXCLUDED.size_bytes,
                    row_count = EXCLUDED.row_count,
                    match_count = EXCLUDED.match_count,
                    source_object_key = EXCLUDED.source_object_key
                """,
                [
                    (
                        uuid.UUID(version_id),
                        o.object_key,
                        o.split.value,
                        o.competition,
                        o.season,
                        o.sha256.value,
                        o.size_bytes,
                        o.row_count,
                        o.match_count,
                        o.source_object_key,
                        o.content_type,
                    )
                    for o in objects
                ],
            )
        return len(objects)

    async def objects_of(self, version_id: str) -> Sequence[NormalizedObjectRef]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"""
                SELECT {_COLUNAS_OBJETO}
                FROM normalized_feature_objects
                WHERE version_id = $1
                ORDER BY object_key
                """,
                uuid.UUID(version_id),
            )
        return [_para_objeto(linha) for linha in linhas]

    async def save_manifest(
        self,
        manifest: NormalizedFeatureDatasetManifest,
        *,
        manifest_key: str,
        manifest_sha256: str,
    ) -> NormalizedFeatureDatasetManifest:
        async with self._db.acquire() as conexao:
            await conexao.execute(
                """
                INSERT INTO normalized_feature_dataset_manifests (
                    id, version_id, schema_version, document,
                    normalized_content_fingerprint, manifest_sha256,
                    object_key, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                uuid.UUID(manifest.id),
                uuid.UUID(manifest.dataset_version_id),
                manifest.schema_version,
                manifest.to_json().decode("utf-8"),
                manifest.normalized_content_fingerprint.value,
                manifest_sha256,
                manifest_key,
                manifest.created_at,
            )
        return manifest

    async def manifest_by_version(self, version_id: str) -> NormalizedFeatureDatasetManifest | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_MANIFESTO} FROM normalized_feature_dataset_manifests "
                "WHERE version_id = $1",
                uuid.UUID(version_id),
            )
        return None if linha is None else _para_manifesto(linha)


# =============================================================== mapeamento ==


def _para_dataset(linha: Any) -> NormalizedHistoricalFeatureDataset:
    return NormalizedHistoricalFeatureDataset(
        id=str(linha["id"]),
        name=linha["name"],
        source_dataset_id=str(linha["source_dataset_id"]),
        description=linha["description"],
        created_at=linha["created_at"],
        created_by=Actor(id=linha["created_by"], kind=ActorKind(linha["created_by_kind"])),
    )


def _para_representacao(linha: Any) -> NormalizedFeatureRepresentationSpec:
    """A representação, reconstruída do DOCUMENTO e conferida contra as colunas.

    DO `jsonb`, E NÃO DAS COLUNAS. Elas guardam o que se CONSULTA; o documento
    guarda a ponte numérica, que não tem coluna e sem a qual a representação
    voltaria com a política padrão — silenciosamente, e com impressão diferente.
    """
    documento = linha["representation"]
    if isinstance(documento, str):
        documento = json.loads(documento)
    representacao = NormalizedFeatureRepresentationSpec.from_canonical(documento)
    for coluna, no_documento in (
        ("space_fingerprint", representacao.space_fingerprint),
        ("plan_fingerprint", representacao.plan_fingerprint),
        ("artifact_set_fingerprint", representacao.artifact_set_fingerprint),
        ("representation_fingerprint", representacao.fingerprint),
    ):
        if linha[coluna] != no_documento:
            raise ConflictError(
                f"a coluna {coluna} discorda do documento da representação: a "
                "consulta «quais versões são comparáveis com esta?» estaria "
                "apontando para outra escala",
                context={"column": str(linha[coluna]), "document": str(no_documento)},
            )
    return representacao


def _para_versao(linha: Any) -> NormalizedHistoricalFeatureDatasetVersion:
    return NormalizedHistoricalFeatureDatasetVersion(
        id=str(linha["id"]),
        dataset_id=str(linha["dataset_id"]),
        version=DatasetVersion(major=linha["version_major"], minor=linha["version_minor"]),
        source_version_id=str(linha["source_version_id"]),
        source_version=DatasetVersion(
            major=linha["source_version_major"], minor=linha["source_version_minor"]
        ),
        source_raw_content_fingerprint=ContentHash(linha["source_raw_content_fingerprint"]),
        source_row_count=linha["source_row_count"],
        representation=_para_representacao(linha),
        status=DatasetVersionStatus(linha["status"]),
        created_at=linha["created_at"],
        created_by=Actor(id=linha["created_by"], kind=ActorKind(linha["created_by_kind"])),
        normalized_content_fingerprint=_hash(linha["normalized_content_fingerprint"]),
        normalized_reference_content_fingerprint=_hash(
            linha["normalized_reference_content_fingerprint"]
        ),
        normalized_evaluation_content_fingerprint=_hash(
            linha["normalized_evaluation_content_fingerprint"]
        ),
        manifest_id=None if linha["manifest_id"] is None else str(linha["manifest_id"]),
        match_count=linha["match_count"],
        row_count=linha["row_count"],
        counts=SplitCounts(
            reference_matches=linha["reference_matches"],
            evaluation_matches=linha["evaluation_matches"],
            reference_rows=linha["reference_rows"],
            evaluation_rows=linha["evaluation_rows"],
        ),
        completed_at=linha["completed_at"],
        failure_reason=linha["failure_reason"],
        superseded_by=(None if linha["superseded_by"] is None else str(linha["superseded_by"])),
    )


def _para_execucao(linha: Any) -> NormalizedFeatureDatasetBuildRun:
    return NormalizedFeatureDatasetBuildRun(
        id=str(linha["id"]),
        version_id=str(linha["version_id"]),
        started_at=linha["started_at"],
        started_by=Actor(id=linha["started_by"], kind=ActorKind(linha["started_by_kind"])),
        status=DatasetVersionStatus(linha["status"]),
        finished_at=linha["finished_at"],
        rows_read=linha["rows_read"],
        rows_written=linha["rows_written"],
        objects_written=linha["objects_written"],
        bytes_written=linha["bytes_written"],
        artifact_unavailable_cells=linha["artifact_unavailable_cells"],
        failure_reason=linha["failure_reason"],
    )


def _para_objeto(linha: Any) -> NormalizedObjectRef:
    return NormalizedObjectRef(
        object_key=linha["object_key"],
        split=DatasetSplit(linha["split"]),
        competition=linha["competition"],
        season=linha["season"],
        sha256=ContentHash(linha["sha256"]),
        size_bytes=linha["size_bytes"],
        row_count=linha["row_count"],
        match_count=linha["match_count"],
        source_object_key=linha["source_object_key"],
        content_type=linha["content_type"],
    )


def _para_manifesto(linha: Any) -> NormalizedFeatureDatasetManifest:
    """Reconstrói o manifesto a partir do DOCUMENTO gravado.

    DO DOCUMENTO, E NÃO DAS COLUNAS. As colunas existem para consultar; o
    documento é o que foi publicado, e reconstruir das colunas produziria um
    manifesto parecido — e `manifest_sha256` deixaria de fechar sobre ele.
    """
    documento = linha["document"]
    if isinstance(documento, str):
        documento = json.loads(documento)
    contagens = documento["counts"]
    impressoes = documento["fingerprints"]
    disponibilidade = documento["availability"]
    return NormalizedFeatureDatasetManifest(
        id=documento["id"],
        schema_version=documento["schema_version"],
        dataset_id=documento["dataset_id"],
        dataset_name=documento["dataset_name"],
        dataset_version=DatasetVersion.parse(documento["dataset_version"]),
        dataset_version_id=documento["dataset_version_id"],
        source_dataset_version_id=documento["source"]["version_id"],
        source_version=DatasetVersion.parse(documento["source"]["version"]),
        source_raw_content_fingerprint=ContentHash(documento["source"]["raw_content_fingerprint"]),
        source_row_count=documento["source"]["row_count"],
        representation=NormalizedFeatureRepresentationSpec.from_canonical(
            documento["representation"]
        ),
        plan=NormalizationPlan.from_canonical(documento["plan"]),
        counts=SplitCounts(
            reference_matches=contagens["reference_matches"],
            evaluation_matches=contagens["evaluation_matches"],
            reference_rows=contagens["reference_rows"],
            evaluation_rows=contagens["evaluation_rows"],
        ),
        match_count=documento["match_count"],
        row_count=documento["row_count"],
        availability=NormalizationAvailabilitySummary(
            total_cells=disponibilidade["total_cells"],
            by_state=dict(disponibilidade["by_state"]),
            by_source_state=dict(disponibilidade["by_source_state"]),
        ),
        normalized_content_fingerprint=ContentHash(impressoes["normalized"]),
        normalized_reference_content_fingerprint=ContentHash(impressoes["reference"]),
        normalized_evaluation_content_fingerprint=ContentHash(impressoes["evaluation"]),
        reference_end_exclusive=_instante(documento["fit"]["reference_end_exclusive"]),
        created_at=_instante(documento["created_at"]),
        row_digest_algorithm=documento["row_digest_algorithm"],
        content_fingerprint_algorithm=documento["content_fingerprint_algorithm"],
        objects=tuple(
            NormalizedObjectRef(
                object_key=o["object_key"],
                split=DatasetSplit(o["split"]),
                competition=o["competition"],
                season=o["season"],
                sha256=ContentHash(o["sha256"]),
                size_bytes=o["size_bytes"],
                row_count=o["row_count"],
                match_count=o["match_count"],
                source_object_key=o["source_object_key"],
                content_type=o["content_type"],
            )
            for o in documento["objects"]
        ),
        artifact_map=tuple(
            ArtifactMapEntry(
                competition=e["competition"],
                feature_key=e["feature_key"],
                strategy=e["strategy"],
                status=e["status"],
                artifact_fingerprint=e["artifact_fingerprint"],
                sample_size=e["sample_size"],
            )
            for e in documento["artifact_map"]
        ),
        rows_by_partition=dict(documento["rows_by_partition"]),
    )


def _hash(valor: str | None) -> ContentHash | None:
    return None if valor is None else ContentHash(valor)


def _texto(valor: ContentHash | None) -> str | None:
    return None if valor is None else valor.value


def _instante(texto: str) -> Instant:
    return instant(datetime.fromisoformat(texto))


def _linhas_afetadas(resultado: str) -> int:
    partes = resultado.split()
    return int(partes[-1]) if partes and partes[-1].isdigit() else 0
