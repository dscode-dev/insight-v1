"""Os repositórios do dataset histórico de features, em SQL escrito à mão.

O QUE É PARTICULAR DESTE ARQUIVO:

O BANCO NÃO GUARDA LINHA DE FEATURE NENHUMA (ADR-0037). Ele guarda identidade,
políticas, contagens, rastro e PONTEIROS; o conteúdo mora no Parquet. Nenhuma
consulta aqui devolve um valor de feature, e a ausência é o desenho.

A TRANSIÇÃO É `UPDATE ... WHERE status = $esperado`, e o estado esperado sai do
que foi lido. É essa cláusula que serializa duas construções simultâneas sem
lock distribuído: a segunda vê zero linhas afetadas e decide, em vez de
sobrescrever.

O GRAFO É CONFERIDO DOS DOIS LADOS. O domínio recusa `DRAFT → READY` no tipo; a
cláusula `WHERE` recusa a mesma coisa por corrida. Uma guarda só cobriria o
caso fácil.

OS OBJETOS SÃO `ON CONFLICT DO UPDATE` POR CHAVE. Reescrever o mesmo
`part-00003.parquet` é o caminho normal do retry depois de uma falha parcial, e
ele não pode duplicar a contagem — nem manter o hash antigo se o conteúdo foi
regravado.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any, Final, final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.corpus.versions import (
    DatasetVersionStatus,
    can_transition,
)
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.dataset.manifest import (
    AvailabilitySummary,
    FeatureObjectRef,
    HistoricalFeatureDatasetManifest,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit, SplitCounts
from sports_intelligence.domain.features.dataset.versions import (
    FeatureDatasetBuildRun,
    FeatureDatasetSpec,
    HistoricalFeatureDataset,
    HistoricalFeatureDatasetVersion,
)
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import ConflictError, NotFoundError
from sports_intelligence.domain.shared.temporal import Instant, instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

_COLUNAS_DATASET: Final[str] = "id, name, description, created_at, created_by, created_by_kind"

_COLUNAS_VERSAO: Final[str] = """
    id, dataset_id, version_major, version_minor, status,
    source_version_id, source_version_major, source_version_minor,
    source_corpus_fingerprint,
    space_name, space_version, space_fingerprint,
    grid_name, grid_version, grid_fingerprint,
    split_name, split_version, split_fingerprint, reference_end_exclusive,
    spec,
    raw_content_fingerprint, manifest_id, match_count, row_count,
    reference_matches, evaluation_matches, reference_rows, evaluation_rows,
    created_at, created_by, created_by_kind, completed_at, failure_reason,
    superseded_by
"""

_COLUNAS_EXECUCAO: Final[str] = """
    id, version_id, status, started_at, started_by, started_by_kind,
    finished_at, matches_processed, rows_written, objects_written,
    bytes_written, failure_reason
"""

_COLUNAS_OBJETO: Final[str] = (
    "object_key, split, competition, season, sha256, size_bytes, row_count, "
    "match_count, content_type"
)

_COLUNAS_MANIFESTO: Final[str] = (
    "id, version_id, schema_version, document, raw_content_fingerprint, "
    "manifest_sha256, object_key, created_at"
)


@final
class PostgresHistoricalFeatureDatasetRepository:
    """Identidade e versões do dataset de features."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_dataset(
        self,
        *,
        name: str,
        at: Instant,
        created_by: Actor,
        description: str | None = None,
    ) -> HistoricalFeatureDataset:
        dataset = HistoricalFeatureDataset.create(
            name=name, at=at, created_by=created_by, description=description
        )
        async with self._db.acquire() as conexao:
            try:
                await conexao.execute(
                    """
                    INSERT INTO historical_feature_datasets (
                        id, name, description, created_at, created_by, created_by_kind
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    uuid.UUID(dataset.id),
                    dataset.name,
                    dataset.description,
                    dataset.created_at,
                    dataset.created_by.id,
                    dataset.created_by.kind.value,
                )
            except Exception as erro:  # asyncpg.UniqueViolationError
                if "hfd_nome_unico" not in str(erro):
                    raise
                raise ConflictError(
                    f"já existe um dataset de features chamado {dataset.name!r}",
                    context={"name": dataset.name},
                ) from erro
        return dataset

    async def dataset_by_name(self, name: str) -> HistoricalFeatureDataset | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_DATASET} FROM historical_feature_datasets WHERE name = $1",
                name,
            )
        return None if linha is None else _para_dataset(linha)

    async def dataset_by_id(self, dataset_id: str) -> HistoricalFeatureDataset | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_DATASET} FROM historical_feature_datasets WHERE id = $1",
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
        source_corpus_fingerprint: ContentHash,
        spec: FeatureDatasetSpec,
        at: Instant,
        created_by: Actor,
    ) -> HistoricalFeatureDatasetVersion:
        criada = HistoricalFeatureDatasetVersion.draft(
            dataset_id=dataset_id,
            version=version,
            source_version_id=source_version_id,
            source_version=source_version,
            source_corpus_fingerprint=source_corpus_fingerprint,
            spec=spec,
            at=at,
            created_by=created_by,
        )
        async with self._db.acquire() as conexao:
            try:
                await conexao.execute(
                    """
                    INSERT INTO historical_feature_dataset_versions (
                        id, dataset_id, version_major, version_minor, status,
                        source_version_id, source_version_major, source_version_minor,
                        source_corpus_fingerprint,
                        space_name, space_version, space_fingerprint,
                        grid_name, grid_version, grid_fingerprint,
                        split_name, split_version, split_fingerprint,
                        reference_end_exclusive, spec,
                        created_at, created_by, created_by_kind
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                            $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23)
                    """,
                    uuid.UUID(criada.id),
                    uuid.UUID(dataset_id),
                    version.major,
                    version.minor,
                    criada.status.value,
                    uuid.UUID(source_version_id),
                    source_version.major,
                    source_version.minor,
                    source_corpus_fingerprint.value,
                    spec.space_name,
                    spec.space_version,
                    spec.space_fingerprint,
                    spec.grid_name,
                    spec.grid_version,
                    spec.grid_fingerprint,
                    spec.split_name,
                    spec.split_version,
                    spec.split_fingerprint,
                    spec.reference_end_exclusive,
                    json.dumps(spec.as_canonical(), sort_keys=True),
                    at,
                    created_by.id,
                    created_by.kind.value,
                )
            except Exception as erro:
                if "hfdv_versao_unica" not in str(erro):
                    raise
                raise ConflictError(
                    f"a versão {version} deste dataset de features já existe",
                    context={"version": str(version)},
                ) from erro
        return criada

    async def version_by_id(self, version_id: str) -> HistoricalFeatureDatasetVersion | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_VERSAO} FROM historical_feature_dataset_versions WHERE id = $1",
                uuid.UUID(version_id),
            )
        return None if linha is None else _para_versao(linha)

    async def version_of(
        self, dataset_id: str, version: DatasetVersion
    ) -> HistoricalFeatureDatasetVersion | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_VERSAO} FROM historical_feature_dataset_versions "
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
        raw_content_fingerprint: ContentHash | None = None,
        manifest_id: str | None = None,
        match_count: int | None = None,
        row_count: int | None = None,
        counts: SplitCounts | None = None,
        failure_reason: str | None = None,
        superseded_by: str | None = None,
    ) -> HistoricalFeatureDatasetVersion:
        """Move a versão, conferindo o grafo NO TIPO e por CORRIDA.

        A LEITURA E A ESCRITA NÃO SÃO ATÔMICAS ENTRE SI, e não precisam ser: a
        cláusula `WHERE status = $esperado` faz a segunda transição simultânea
        pegar zero linhas, e o `ConflictError` que ela levanta é a resposta
        certa — «alguém mudou isto debaixo de você», e não um estado meio
        gravado.
        """
        atual = await self.version_by_id(version_id)
        if atual is None:
            raise NotFoundError(
                f"a versão de features {version_id} não existe",
                context={"version_id": version_id},
            )
        atual.require_transition(target)
        movida = _com_transicao(
            atual,
            target=target,
            at=at,
            raw_content_fingerprint=raw_content_fingerprint,
            manifest_id=manifest_id,
            match_count=match_count,
            row_count=row_count,
            counts=counts,
            failure_reason=failure_reason,
            superseded_by=superseded_by,
        )
        async with self._db.acquire() as conexao:
            resultado = await conexao.execute(
                """
                UPDATE historical_feature_dataset_versions
                SET status = $2,
                    raw_content_fingerprint = $3,
                    manifest_id = $4,
                    match_count = $5,
                    row_count = $6,
                    reference_matches = $7,
                    evaluation_matches = $8,
                    reference_rows = $9,
                    evaluation_rows = $10,
                    completed_at = $11,
                    failure_reason = $12,
                    superseded_by = $13
                WHERE id = $1 AND status = $14
                """,
                uuid.UUID(version_id),
                movida.status.value,
                None
                if movida.raw_content_fingerprint is None
                else movida.raw_content_fingerprint.value,
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
                f"a versão de features {version_id} não estava mais em {atual.status} "
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
    ) -> Sequence[HistoricalFeatureDatasetVersion]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"""
                SELECT {_COLUNAS_VERSAO}
                FROM historical_feature_dataset_versions
                WHERE dataset_id = $1 AND ($2::text IS NULL OR status = $2)
                ORDER BY version_major DESC, version_minor DESC
                LIMIT $3
                """,
                uuid.UUID(dataset_id),
                None if status is None else status.value,
                limit,
            )
        return [_para_versao(linha) for linha in linhas]

    async def latest_ready(self, dataset_id: str) -> HistoricalFeatureDatasetVersion | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"""
                SELECT {_COLUNAS_VERSAO}
                FROM historical_feature_dataset_versions
                WHERE dataset_id = $1 AND status = 'READY'
                ORDER BY version_major DESC, version_minor DESC
                LIMIT 1
                """,
                uuid.UUID(dataset_id),
            )
        return None if linha is None else _para_versao(linha)

    async def versions_from_corpus(
        self, source_version_id: str, *, limit: int = 50
    ) -> Sequence[HistoricalFeatureDatasetVersion]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"""
                SELECT {_COLUNAS_VERSAO}
                FROM historical_feature_dataset_versions
                WHERE source_version_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                uuid.UUID(source_version_id),
                limit,
            )
        return [_para_versao(linha) for linha in linhas]


@final
class PostgresFeatureDatasetBuildRepository:
    """Rastros de execução e objetos materializados."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def start_run(
        self, *, version_id: str, at: Instant, started_by: Actor
    ) -> FeatureDatasetBuildRun:
        execucao = FeatureDatasetBuildRun.start(version_id=version_id, at=at, started_by=started_by)
        async with self._db.acquire() as conexao:
            await conexao.execute(
                """
                INSERT INTO historical_feature_dataset_build_runs (
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
        matches_processed: int = 0,
        rows_written: int = 0,
        objects_written: int = 0,
        bytes_written: int = 0,
        failure_reason: str | None = None,
    ) -> FeatureDatasetBuildRun:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"""
                UPDATE historical_feature_dataset_build_runs
                SET status = $2, finished_at = $3, matches_processed = $4,
                    rows_written = $5, objects_written = $6, bytes_written = $7,
                    failure_reason = $8
                WHERE id = $1
                RETURNING {_COLUNAS_EXECUCAO}
                """,
                uuid.UUID(run_id),
                status.value,
                at,
                matches_processed,
                rows_written,
                objects_written,
                bytes_written,
                failure_reason,
            )
        if linha is None:
            raise NotFoundError(
                f"a execução de construção {run_id} não existe",
                context={"run_id": run_id},
            )
        return _para_execucao(linha)

    async def runs_of(
        self, version_id: str, *, limit: int = 20
    ) -> Sequence[FeatureDatasetBuildRun]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"""
                SELECT {_COLUNAS_EXECUCAO}
                FROM historical_feature_dataset_build_runs
                WHERE version_id = $1
                ORDER BY started_at DESC
                LIMIT $2
                """,
                uuid.UUID(version_id),
                limit,
            )
        return [_para_execucao(linha) for linha in linhas]

    async def record_objects(self, version_id: str, objects: Sequence[FeatureObjectRef]) -> int:
        if not objects:
            return 0
        async with self._db.acquire() as conexao:
            await conexao.executemany(
                """
                INSERT INTO historical_feature_objects (
                    version_id, object_key, split, competition, season, sha256,
                    size_bytes, row_count, match_count, content_type
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (version_id, object_key) DO UPDATE
                SET sha256 = EXCLUDED.sha256,
                    size_bytes = EXCLUDED.size_bytes,
                    row_count = EXCLUDED.row_count,
                    match_count = EXCLUDED.match_count
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
                        o.content_type,
                    )
                    for o in objects
                ],
            )
        return len(objects)

    async def objects_of(self, version_id: str) -> Sequence[FeatureObjectRef]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"""
                SELECT {_COLUNAS_OBJETO}
                FROM historical_feature_objects
                WHERE version_id = $1
                ORDER BY object_key
                """,
                uuid.UUID(version_id),
            )
        return [_para_objeto(linha) for linha in linhas]


@final
class PostgresFeatureDatasetManifestRepository:
    """O manifesto persistido."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(
        self,
        manifest: HistoricalFeatureDatasetManifest,
        *,
        manifest_key: str,
        manifest_sha256: str,
    ) -> HistoricalFeatureDatasetManifest:
        async with self._db.acquire() as conexao:
            await conexao.execute(
                """
                INSERT INTO historical_feature_dataset_manifests (
                    id, version_id, schema_version, document,
                    raw_content_fingerprint, manifest_sha256, object_key, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                uuid.UUID(manifest.id),
                uuid.UUID(manifest.dataset_version_id),
                manifest.schema_version,
                manifest.to_json().decode("utf-8"),
                manifest.raw_content_fingerprint.value,
                manifest_sha256,
                manifest_key,
                manifest.created_at,
            )
        return manifest

    async def by_version(self, version_id: str) -> HistoricalFeatureDatasetManifest | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_MANIFESTO} FROM historical_feature_dataset_manifests "
                "WHERE version_id = $1",
                uuid.UUID(version_id),
            )
        return None if linha is None else _para_manifesto(linha)

    async def by_fingerprint(
        self, fingerprint: ContentHash, *, limit: int = 20
    ) -> Sequence[HistoricalFeatureDatasetManifest]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"""
                SELECT {_COLUNAS_MANIFESTO}
                FROM historical_feature_dataset_manifests
                WHERE raw_content_fingerprint = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                fingerprint.value,
                limit,
            )
        return [_para_manifesto(linha) for linha in linhas]


# =============================================================== mapeamento ==


def _para_dataset(linha: Any) -> HistoricalFeatureDataset:
    return HistoricalFeatureDataset(
        id=str(linha["id"]),
        name=linha["name"],
        description=linha["description"],
        created_at=linha["created_at"],
        created_by=Actor(id=linha["created_by"], kind=ActorKind(linha["created_by_kind"])),
    )


def _para_spec(linha: Any) -> FeatureDatasetSpec:
    """A especificação, reconstruída do DOCUMENTO e conferida contra as colunas.

    DO `jsonb`, E NÃO DAS COLUNAS. As colunas guardam nome, versão e impressão —
    o que se consulta —, e não os PARÂMETROS: uma grade de cinco cortes
    reconstruída delas voltaria com noventa e um, e a impressão acusaria sem
    conseguir consertar.

    AS COLUNAS SÃO CONFERIDAS mesmo assim. Elas existem para filtrar, e um
    índice que aponte para uma impressão diferente da do documento tornaria a
    consulta «quais versões são comparáveis com esta?» silenciosamente errada.
    """
    documento = linha["spec"]
    if isinstance(documento, str):
        documento = json.loads(documento)
    spec = FeatureDatasetSpec.from_canonical(documento)
    for coluna, no_documento in (
        ("grid_fingerprint", spec.grid_fingerprint),
        ("split_fingerprint", spec.split_fingerprint),
        ("space_fingerprint", spec.space_fingerprint),
        # A FRONTEIRA TAMBÉM: ela é coluna para responder «que datasets têm
        # avaliação começando depois de junho?», e uma coluna que discordasse do
        # documento faria essa consulta selecionar a versão errada.
        ("reference_end_exclusive", spec.reference_end_exclusive),
    ):
        if linha[coluna] != no_documento:
            raise ConflictError(
                f"a coluna {coluna} discorda do documento da especificação: a "
                "consulta administrativa estaria apontando para outra política",
                context={"column": str(linha[coluna]), "document": str(no_documento)},
            )
    return spec


def _para_versao(linha: Any) -> HistoricalFeatureDatasetVersion:
    return HistoricalFeatureDatasetVersion(
        id=str(linha["id"]),
        dataset_id=str(linha["dataset_id"]),
        version=DatasetVersion(major=linha["version_major"], minor=linha["version_minor"]),
        source_version_id=str(linha["source_version_id"]),
        source_version=DatasetVersion(
            major=linha["source_version_major"], minor=linha["source_version_minor"]
        ),
        source_corpus_fingerprint=ContentHash(linha["source_corpus_fingerprint"]),
        spec=_para_spec(linha),
        status=DatasetVersionStatus(linha["status"]),
        created_at=linha["created_at"],
        created_by=Actor(id=linha["created_by"], kind=ActorKind(linha["created_by_kind"])),
        raw_content_fingerprint=(
            None
            if linha["raw_content_fingerprint"] is None
            else ContentHash(linha["raw_content_fingerprint"])
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


def _para_execucao(linha: Any) -> FeatureDatasetBuildRun:
    return FeatureDatasetBuildRun(
        id=str(linha["id"]),
        version_id=str(linha["version_id"]),
        started_at=linha["started_at"],
        started_by=Actor(id=linha["started_by"], kind=ActorKind(linha["started_by_kind"])),
        status=DatasetVersionStatus(linha["status"]),
        finished_at=linha["finished_at"],
        matches_processed=linha["matches_processed"],
        rows_written=linha["rows_written"],
        objects_written=linha["objects_written"],
        bytes_written=linha["bytes_written"],
        failure_reason=linha["failure_reason"],
    )


def _para_objeto(linha: Any) -> FeatureObjectRef:
    return FeatureObjectRef(
        object_key=linha["object_key"],
        split=DatasetSplit(linha["split"]),
        competition=linha["competition"],
        season=linha["season"],
        sha256=ContentHash(linha["sha256"]),
        size_bytes=linha["size_bytes"],
        row_count=linha["row_count"],
        match_count=linha["match_count"],
        content_type=linha["content_type"],
    )


def _para_manifesto(linha: Any) -> HistoricalFeatureDatasetManifest:
    """Reconstrói o manifesto a partir do DOCUMENTO gravado.

    DO DOCUMENTO, E NÃO DAS COLUNAS. As colunas existem para consultar; o
    documento é o que foi publicado, e reconstruir a partir delas produziria um
    manifesto parecido com o que foi gravado — e `manifest_sha256` deixaria de
    fechar sobre ele.
    """
    documento = linha["document"]
    if isinstance(documento, str):
        documento = json.loads(documento)
    spec = documento["spec"]
    contagens = documento["counts"]
    return HistoricalFeatureDatasetManifest(
        id=documento["id"],
        schema_version=documento["schema_version"],
        dataset_id=documento["dataset_id"],
        dataset_name=documento["dataset_name"],
        dataset_version=DatasetVersion.parse(documento["dataset_version"]),
        dataset_version_id=documento["dataset_version_id"],
        source_version_id=documento["source"]["version_id"],
        source_version=DatasetVersion.parse(documento["source"]["version"]),
        source_corpus_fingerprint=ContentHash(documento["source"]["corpus_fingerprint"]),
        spec=FeatureDatasetSpec.from_canonical(spec),
        counts=SplitCounts(
            reference_matches=contagens["reference_matches"],
            evaluation_matches=contagens["evaluation_matches"],
            reference_rows=contagens["reference_rows"],
            evaluation_rows=contagens["evaluation_rows"],
        ),
        match_count=documento["match_count"],
        row_count=documento["row_count"],
        availability=AvailabilitySummary(
            total_values=documento["availability"]["total_values"],
            by_state=dict(documento["availability"]["by_state"]),
        ),
        raw_content_fingerprint=ContentHash(documento["raw_content_fingerprint"]),
        created_at=_instante(documento["created_at"]),
        row_digest_algorithm=documento["row_digest_algorithm"],
        content_fingerprint_algorithm=documento["content_fingerprint_algorithm"],
        objects=tuple(
            FeatureObjectRef(
                object_key=o["object_key"],
                split=DatasetSplit(o["split"]),
                competition=o["competition"],
                season=o["season"],
                sha256=ContentHash(o["sha256"]),
                size_bytes=o["size_bytes"],
                row_count=o["row_count"],
                match_count=o["match_count"],
                content_type=o["content_type"],
            )
            for o in documento["objects"]
        ),
        rows_by_partition=dict(documento["rows_by_partition"]),
    )


def _instante(texto: str) -> Instant:
    from datetime import datetime

    return instant(datetime.fromisoformat(texto))


def _com_transicao(
    atual: HistoricalFeatureDatasetVersion,
    *,
    target: DatasetVersionStatus,
    at: Instant,
    raw_content_fingerprint: ContentHash | None,
    manifest_id: str | None,
    match_count: int | None,
    row_count: int | None,
    counts: SplitCounts | None,
    failure_reason: str | None,
    superseded_by: str | None,
) -> HistoricalFeatureDatasetVersion:
    """A versão movida, com os campos novos ou os antigos.

    `None` SIGNIFICA «NÃO MEXA», e não «apague». Uma transição para `READY` não
    reenvia contagens, e tratá-las como zero apagaria o que a construção contou.
    """
    if not can_transition(atual.status, target):
        atual.require_transition(target)
    from dataclasses import replace

    return replace(
        atual,
        status=target,
        raw_content_fingerprint=(
            atual.raw_content_fingerprint
            if raw_content_fingerprint is None
            else raw_content_fingerprint
        ),
        manifest_id=atual.manifest_id if manifest_id is None else manifest_id,
        match_count=atual.match_count if match_count is None else match_count,
        row_count=atual.row_count if row_count is None else row_count,
        counts=atual.counts if counts is None else counts,
        completed_at=at if target.is_terminal else atual.completed_at,
        failure_reason=atual.failure_reason if failure_reason is None else failure_reason,
        superseded_by=atual.superseded_by if superseded_by is None else superseded_by,
    )


def _linhas_afetadas(resultado: str) -> int:
    """`'UPDATE 1'` → `1`. O asyncpg devolve a etiqueta de comando, não o número."""
    partes = resultado.split()
    return int(partes[-1]) if partes and partes[-1].isdigit() else 0
