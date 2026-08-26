"""Os repositórios do registro de intake, em SQL escrito à mão.

A TRADUÇÃO ENTRE LINHA E AGREGADO MORA AQUI, INTEIRA E VISÍVEL. É a parte que
um ORM esconderia, e escondê-la tem um custo específico neste domínio: a
diferença entre `files` e `stored_files` — entre o que foi prometido e o que
foi gravado — é uma decisão de modelagem, não um detalhe de carregamento. Com
lazy loading ela viraria uma consulta que dispara sozinha, e o `PENDING` que
não deveria contar contaria.

AS TRANSIÇÕES DE ESTADO SÃO CONDICIONAIS AO ESTADO ANTERIOR:

    UPDATE datasets SET lifecycle = $novo
    WHERE id = $id AND lifecycle = $esperado

`rowcount == 0` significa que outro processo mudou o estado antes. Isso é
controle de concorrência otimista feito onde ele de fato funciona. A
alternativa — ler, decidir em Python, escrever — deixa duas requisições
simultâneas lerem `UPLOADED`, ambas concluírem que podem validar, e ambas
seguirem.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any, Final, final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.datasets.files import (
    DatasetFile,
    DatasetFileId,
    FileStagingState,
)
from sports_intelligence.domain.datasets.formats import DatasetFormat
from sports_intelligence.domain.datasets.lifecycle import DatasetLifecycle
from sports_intelligence.domain.datasets.manifest import DatasetManifest, ManifestFile
from sports_intelligence.domain.datasets.models import (
    Dataset,
    DatasetFilter,
    DatasetSummary,
    Page,
)
from sports_intelligence.domain.datasets.schema import (
    ColumnObservation,
    DatasetSchemaObservation,
    DetectedType,
)
from sports_intelligence.domain.datasets.source import DatasetSource
from sports_intelligence.domain.datasets.validation import (
    DatasetValidationIssue,
    DatasetValidationReport,
    IssueCode,
    IssueSeverity,
    ValidatorVersion,
)
from sports_intelligence.domain.shared.identity import DatasetId, ProviderId
from sports_intelligence.domain.shared.provenance import (
    DataProvenance,
    LicenseClass,
    SourceType,
)
from sports_intelligence.domain.shared.temporal import (
    Instant,
    ObservationTimes,
    instant,
    parse_instant,
)
from sports_intelligence.domain.shared.versioning import DatasetVersion

_CAMPOS_DATASET: Final = """
    d.id, d.name, d.version_major, d.version_minor, d.description, d.lifecycle,
    d.declared_competitions, d.declared_seasons, d.latest_validation_id,
    d.created_at, d.created_by,
    s.source_name, s.source_type, s.license_class, s.retrieved_at,
    s.source_url, s.publisher, s.provider_id, s.notes
"""

_CAMPOS_ARQUIVO: Final = """
    id, dataset_id, version_major, version_minor, original_filename, safe_filename,
    media_type, format, sha256, size_bytes, object_key, staging_state,
    uploaded_at, uploaded_by, provenance, row_count, column_count
"""


@final
class PostgresDatasetRepository:
    """O dataset: criação idempotente, leitura e transição condicional."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def insert_if_absent(self, dataset: Dataset) -> tuple[Dataset, bool]:
        """Insere as duas linhas, ou devolve o que já está lá.

        `ON CONFLICT DO NOTHING` E NÃO "consultar antes de inserir". Consultar
        antes cria uma janela entre a leitura e a escrita, e dois processos
        que registram o mesmo dataset ao mesmo tempo passam os dois pela
        consulta e colidem só no INSERT — com o segundo levantando um erro de
        constraint em vez de convergir.
        """
        async with self._db.acquire() as conexao, conexao.transaction():
            inserido = await conexao.fetchval(
                """
                INSERT INTO datasets (
                    id, name, version_major, version_minor, description, lifecycle,
                    declared_competitions, declared_seasons, created_at, created_by
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """,
                dataset.id.value,
                dataset.name,
                dataset.version.major,
                dataset.version.minor,
                dataset.description,
                dataset.lifecycle.value,
                sorted(c.value for c in dataset.declared_competitions),
                list(dataset.declared_seasons),
                dataset.created_at,
                dataset.created_by,
            )
            if inserido is not None:
                fonte = dataset.source
                await conexao.execute(
                    """
                    INSERT INTO dataset_sources (
                        dataset_id, source_name, source_type, license_class,
                        retrieved_at, source_url, publisher, provider_id, notes
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    dataset.id.value,
                    fonte.source_name,
                    fonte.source_type.value,
                    fonte.license_class.value,
                    fonte.retrieved_at,
                    fonte.source_url,
                    fonte.publisher,
                    str(fonte.provider_id) if fonte.provider_id else None,
                    fonte.notes,
                )
                await conexao.execute(
                    """
                    INSERT INTO dataset_transitions
                        (dataset_id, from_state, to_state, reason, actor_id, at)
                    VALUES ($1, $2, $2, $3, $4, $5)
                    """,
                    dataset.id.value,
                    DatasetLifecycle.REGISTERED.value,
                    "dataset registrado",
                    dataset.created_by,
                    dataset.created_at,
                )
                return dataset, True

        existente = await self.by_id(dataset.id)
        if existente is None:  # pragma: no cover — só se alguém apagar entre as duas
            return dataset, True
        return existente, False

    async def by_id(self, dataset_id: DatasetId, *, with_files: bool = True) -> Dataset | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"""
                SELECT {_CAMPOS_DATASET}
                FROM datasets d
                JOIN dataset_sources s ON s.dataset_id = d.id
                WHERE d.id = $1
                """,
                dataset_id.value,
            )
            if linha is None:
                return None
            arquivos: tuple[DatasetFile, ...] = ()
            if with_files:
                arquivos = tuple(
                    _para_arquivo(r)
                    for r in await conexao.fetch(
                        f"SELECT {_CAMPOS_ARQUIVO} FROM dataset_files "
                        "WHERE dataset_id = $1 ORDER BY uploaded_at, id",
                        dataset_id.value,
                    )
                )
        return _para_dataset(linha, arquivos)

    async def by_name_version(self, name: str, version: DatasetVersion) -> Dataset | None:
        return await self.by_id(DatasetId.derive(name.strip().lower(), str(version)))

    async def list(
        self, *, filters: DatasetFilter, page: Page
    ) -> tuple[Sequence[DatasetSummary], int]:
        """A página e o total, numa consulta cada.

        O RESUMO NÃO CARREGA ARQUIVOS. As contagens saem de um agregado sobre
        `dataset_files` filtrado por `STORED` — a mesma regra que
        `stored_files` aplica no domínio, aqui em SQL. Se a contagem não
        filtrasse, uma listagem mostraria um dataset com três arquivos cujos
        bytes nunca chegaram.
        """
        condicoes: list[str] = []
        parametros: list[Any] = []

        def _param(valor: Any) -> str:
            parametros.append(valor)
            return f"${len(parametros)}"

        if filters.competition is not None:
            marcador = _param(filters.competition.value)
            condicoes.append(f"d.declared_competitions @> ARRAY[{marcador}]")
        if filters.lifecycle is not None:
            condicoes.append(f"d.lifecycle = {_param(filters.lifecycle.value)}")
        if filters.origin is not None:
            condicoes.append(f"s.source_type = {_param(filters.origin)}")
        if filters.source_name is not None:
            condicoes.append(f"s.source_name ILIKE {_param(f'%{filters.source_name}%')}")
        if filters.created_after is not None:
            condicoes.append(f"d.created_at >= {_param(filters.created_after)}")
        if filters.created_before is not None:
            condicoes.append(f"d.created_at <= {_param(filters.created_before)}")

        onde = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
        async with self._db.acquire() as conexao:
            total = await conexao.fetchval(
                f"SELECT count(*) FROM datasets d "
                f"JOIN dataset_sources s ON s.dataset_id = d.id {onde}",
                *parametros,
            )
            linhas = await conexao.fetch(
                f"""
                SELECT d.id, d.name, d.version_major, d.version_minor, d.lifecycle,
                       d.declared_competitions, d.created_at,
                       s.source_name, s.source_type, s.license_class,
                       coalesce(f.n, 0) AS file_count,
                       coalesce(f.bytes, 0) AS total_bytes
                FROM datasets d
                JOIN dataset_sources s ON s.dataset_id = d.id
                LEFT JOIN (
                    SELECT dataset_id, count(*) AS n, sum(size_bytes) AS bytes
                    FROM dataset_files
                    WHERE staging_state = 'STORED'
                    GROUP BY dataset_id
                ) f ON f.dataset_id = d.id
                {onde}
                ORDER BY d.created_at DESC, d.id
                LIMIT ${len(parametros) + 1} OFFSET ${len(parametros) + 2}
                """,
                *parametros,
                page.limit,
                page.offset,
            )
        return [_para_resumo(linha) for linha in linhas], int(total or 0)

    async def transition(
        self,
        dataset_id: DatasetId,
        *,
        expected: DatasetLifecycle,
        target: DatasetLifecycle,
        at: Instant,
        reason: str,
        actor_id: str,
    ) -> bool:
        """A transição e seu registro histórico, na mesma transação.

        JUNTOS, E NÃO EM DUAS ESCRITAS. Um estado que muda sem deixar rastro
        é indistinguível de um estado que sempre foi assim — e é justamente
        na investigação de "como este dataset chegou aqui" que a falta
        aparece.
        """
        async with self._db.acquire() as conexao, conexao.transaction():
            resultado = await conexao.execute(
                "UPDATE datasets SET lifecycle = $1, updated_at = $2 "
                "WHERE id = $3 AND lifecycle = $4",
                target.value,
                at,
                dataset_id.value,
                expected.value,
            )
            if _linhas_afetadas(resultado) == 0:
                return False
            await conexao.execute(
                """
                INSERT INTO dataset_transitions
                    (dataset_id, from_state, to_state, reason, actor_id, at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                dataset_id.value,
                expected.value,
                target.value,
                reason,
                actor_id,
                at,
            )
        return True

    async def transitions_of(self, dataset_id: DatasetId) -> Sequence[tuple[str, str, str, str]]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT from_state, to_state, reason, at FROM dataset_transitions "
                "WHERE dataset_id = $1 ORDER BY at, id",
                dataset_id.value,
            )
        return [(r["from_state"], r["to_state"], r["reason"], r["at"].isoformat()) for r in linhas]


@final
class PostgresDatasetFileRepository:
    """Os arquivos, e as duas metades do protocolo de três fases."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def register_intent(self, file: DatasetFile) -> DatasetFile:
        """Fase 1. `ON CONFLICT DO NOTHING` sobre (dataset, sha256).

        A CONSTRAINT É QUEM DECIDE, e por isso a idempotência é real: dois
        uploads simultâneos dos mesmos bytes chegam juntos, os dois inserem,
        e o segundo não cria linha. Ele então lê a do primeiro e continua a
        partir dela — em vez de levantar conflito para uma situação que
        convergiu.
        """
        async with self._db.acquire() as conexao:
            await conexao.execute(
                f"""
                INSERT INTO dataset_files ({_CAMPOS_ARQUIVO}, confirmed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                        $13, $14, $15, $16, $17, NULL)
                ON CONFLICT (dataset_id, sha256) DO NOTHING
                """,
                file.id.value,
                file.dataset_id.value,
                file.dataset_version.major,
                file.dataset_version.minor,
                file.original_filename,
                file.safe_filename,
                file.media_type,
                file.format.value,
                file.content_hash.value,
                file.size_bytes,
                file.object_key,
                file.staging_state.value,
                file.uploaded_at,
                file.uploaded_by,
                json.dumps(_provenance_para_json(file.provenance)),
                file.row_count,
                file.column_count,
            )
            linha = await conexao.fetchrow(
                f"SELECT {_CAMPOS_ARQUIVO} FROM dataset_files "
                "WHERE dataset_id = $1 AND sha256 = $2",
                file.dataset_id.value,
                file.content_hash.value,
            )
        return _para_arquivo(linha) if linha is not None else file

    async def confirm_stored(self, file_id: str) -> bool:
        """Fase 3. `False` quando já estava confirmado — retry convergindo."""
        async with self._db.acquire() as conexao:
            resultado = await conexao.execute(
                "UPDATE dataset_files SET staging_state = 'STORED', confirmed_at = now(), "
                "failure_reason = NULL WHERE id = $1 AND staging_state <> 'STORED'",
                uuid.UUID(file_id),
            )
        return _linhas_afetadas(resultado) > 0

    async def mark_failed(self, file_id: str, *, reason: str) -> None:
        async with self._db.acquire() as conexao:
            await conexao.execute(
                "UPDATE dataset_files SET staging_state = 'FAILED', confirmed_at = NULL, "
                "failure_reason = $2 WHERE id = $1",
                uuid.UUID(file_id),
                reason[:500],
            )

    async def by_dataset(self, dataset_id: DatasetId) -> Sequence[DatasetFile]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"SELECT {_CAMPOS_ARQUIVO} FROM dataset_files "
                "WHERE dataset_id = $1 ORDER BY uploaded_at, id",
                dataset_id.value,
            )
        return [_para_arquivo(linha) for linha in linhas]

    async def by_content(self, dataset_id: DatasetId, sha256: str) -> DatasetFile | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_CAMPOS_ARQUIVO} FROM dataset_files "
                "WHERE dataset_id = $1 AND sha256 = $2",
                dataset_id.value,
                sha256,
            )
        return _para_arquivo(linha) if linha is not None else None

    async def record_inspection(self, file_id: str, *, row_count: int, column_count: int) -> None:
        """O que a inspeção mediu. NÃO toca em hash, tamanho nem chave.

        A ausência de um `update` genérico é o contrato: as três colunas que
        provam identidade do conteúdo não têm caminho de escrita depois da
        gravação inicial.
        """
        async with self._db.acquire() as conexao:
            await conexao.execute(
                "UPDATE dataset_files SET row_count = $2, column_count = $3 WHERE id = $1",
                uuid.UUID(file_id),
                row_count,
                column_count,
            )

    async def pending_older_than(self, moment: Instant) -> Sequence[DatasetFile]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"SELECT {_CAMPOS_ARQUIVO} FROM dataset_files "
                "WHERE staging_state = 'PENDING' AND uploaded_at < $1 ORDER BY uploaded_at",
                moment,
            )
        return [_para_arquivo(linha) for linha in linhas]


@final
class PostgresDatasetValidationRepository:
    """Relatórios e issues. Append-only: não há `UPDATE` neste arquivo."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def save_report(self, report: DatasetValidationReport) -> None:
        async with self._db.acquire() as conexao, conexao.transaction():
            await conexao.execute(
                """
                INSERT INTO dataset_validation_runs (
                    id, dataset_id, version_major, version_minor, status,
                    validator_major, validator_minor, files_checked, rows_observed,
                    issue_count, truncated, schema_observations, execution_error,
                    started_at, generated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                """,
                uuid.UUID(report.id),
                report.dataset_id.value,
                report.dataset_version.major,
                report.dataset_version.minor,
                report.status.value,
                report.validator_version.major,
                report.validator_version.minor,
                report.files_checked,
                report.rows_observed,
                report.issue_count,
                report.truncated,
                json.dumps([_observacao_para_json(o) for o in report.schema_observations]),
                report.execution_error,
                report.started_at,
                report.generated_at,
            )
            if report.issues:
                await conexao.executemany(
                    """
                    INSERT INTO dataset_validation_issues
                        (run_id, ordinal, code, severity, message, file_id, location, occurrences)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    [
                        (
                            uuid.UUID(report.id),
                            ordem,
                            issue.code.value,
                            int(issue.severity),
                            issue.message,
                            uuid.UUID(issue.file_id) if issue.file_id else None,
                            issue.location,
                            issue.occurrences,
                        )
                        for ordem, issue in enumerate(report.issues)
                    ],
                )
            await conexao.execute(
                "UPDATE datasets SET latest_validation_id = $2 WHERE id = $1",
                report.dataset_id.value,
                uuid.UUID(report.id),
            )

    async def latest_for(self, dataset_id: DatasetId) -> DatasetValidationReport | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT * FROM dataset_validation_runs WHERE dataset_id = $1 "
                "ORDER BY generated_at DESC, id LIMIT 1",
                dataset_id.value,
            )
            if linha is None:
                return None
            issues = await self._issues(conexao, linha["id"])
        return _para_relatorio(linha, issues)

    async def by_id(self, report_id: str) -> DatasetValidationReport | None:
        try:
            identificador = uuid.UUID(report_id)
        except ValueError:
            return None
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT * FROM dataset_validation_runs WHERE id = $1", identificador
            )
            if linha is None:
                return None
            issues = await self._issues(conexao, identificador)
        return _para_relatorio(linha, issues)

    async def history_for(
        self, dataset_id: DatasetId, *, limit: int = 10
    ) -> Sequence[DatasetValidationReport]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT * FROM dataset_validation_runs WHERE dataset_id = $1 "
                "ORDER BY generated_at DESC, id LIMIT $2",
                dataset_id.value,
                min(limit, 50),
            )
            return [
                _para_relatorio(linha, await self._issues(conexao, linha["id"])) for linha in linhas
            ]

    @staticmethod
    async def _issues(conexao: Any, run_id: uuid.UUID) -> list[DatasetValidationIssue]:
        linhas = await conexao.fetch(
            "SELECT code, severity, message, file_id, location, occurrences "
            "FROM dataset_validation_issues WHERE run_id = $1 "
            "ORDER BY severity DESC, ordinal",
            run_id,
        )
        return [
            DatasetValidationIssue(
                code=IssueCode(linha["code"]),
                severity=IssueSeverity(linha["severity"]),
                message=linha["message"],
                file_id=str(linha["file_id"]) if linha["file_id"] else None,
                location=linha["location"],
                occurrences=linha["occurrences"],
            )
            for linha in linhas
        ]


@final
class PostgresDatasetManifestRepository:
    """Manifestos, endereçados pela impressão."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def save(self, manifest: DatasetManifest) -> None:
        """`ON CONFLICT DO NOTHING` sobre a impressão.

        Reemitir o mesmo manifesto produz a mesma impressão e a mesma linha —
        não uma segunda. É a idempotência caindo de graça do endereçamento
        por conteúdo (ADR-0015).
        """
        async with self._db.acquire() as conexao:
            await conexao.execute(
                """
                INSERT INTO dataset_manifests (
                    fingerprint, dataset_id, version_major, version_minor,
                    validation_id, body, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (fingerprint) DO NOTHING
                """,
                manifest.fingerprint.value,
                manifest.dataset_id.value,
                manifest.dataset_version.major,
                manifest.dataset_version.minor,
                uuid.UUID(manifest.validation_id),
                json.dumps(_manifesto_para_json(manifest)),
                manifest.created_at,
            )

    async def latest_for(self, dataset_id: DatasetId) -> DatasetManifest | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT body FROM dataset_manifests WHERE dataset_id = $1 "
                "ORDER BY created_at DESC, fingerprint LIMIT 1",
                dataset_id.value,
            )
        return _para_manifesto(linha["body"]) if linha is not None else None

    async def by_fingerprint(self, fingerprint: str) -> DatasetManifest | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT body FROM dataset_manifests WHERE fingerprint = $1", fingerprint
            )
        return _para_manifesto(linha["body"]) if linha is not None else None


# ------------------------------------------------------------- tradução ----


def _linhas_afetadas(resultado: str) -> int:
    """asyncpg devolve `UPDATE 1`. O número é a última palavra."""
    try:
        return int(str(resultado).rsplit(" ", 1)[-1])
    except ValueError:  # pragma: no cover
        return 0


def _para_dataset(linha: Any, arquivos: tuple[DatasetFile, ...]) -> Dataset:
    return Dataset(
        id=DatasetId(linha["id"]),
        name=linha["name"],
        version=DatasetVersion(major=linha["version_major"], minor=linha["version_minor"]),
        source=DatasetSource(
            source_name=linha["source_name"],
            source_type=SourceType(linha["source_type"]),
            license_class=LicenseClass(linha["license_class"]),
            retrieved_at=instant(linha["retrieved_at"]),
            source_url=linha["source_url"],
            publisher=linha["publisher"],
            provider_id=ProviderId(linha["provider_id"]) if linha["provider_id"] else None,
            notes=linha["notes"],
        ),
        declared_competitions=frozenset(CompetitionCode(c) for c in linha["declared_competitions"]),
        declared_seasons=tuple(linha["declared_seasons"] or ()),
        lifecycle=DatasetLifecycle(linha["lifecycle"]),
        created_at=instant(linha["created_at"]),
        created_by=linha["created_by"],
        files=arquivos,
        description=linha["description"],
        latest_validation_id=(
            str(linha["latest_validation_id"]) if linha["latest_validation_id"] else None
        ),
    )


def _para_resumo(linha: Any) -> DatasetSummary:
    return DatasetSummary(
        id=DatasetId(linha["id"]),
        name=linha["name"],
        version=DatasetVersion(major=linha["version_major"], minor=linha["version_minor"]),
        lifecycle=DatasetLifecycle(linha["lifecycle"]),
        source_name=linha["source_name"],
        source_type=linha["source_type"],
        license_class=linha["license_class"],
        declared_competitions=frozenset(CompetitionCode(c) for c in linha["declared_competitions"]),
        file_count=int(linha["file_count"]),
        total_bytes=int(linha["total_bytes"]),
        created_at=instant(linha["created_at"]),
    )


def _para_arquivo(linha: Any) -> DatasetFile:
    return DatasetFile(
        id=DatasetFileId(linha["id"]),
        dataset_id=DatasetId(linha["dataset_id"]),
        dataset_version=DatasetVersion(major=linha["version_major"], minor=linha["version_minor"]),
        original_filename=linha["original_filename"],
        safe_filename=linha["safe_filename"],
        media_type=linha["media_type"],
        format=DatasetFormat(linha["format"]),
        content_hash=ContentHash(linha["sha256"]),
        size_bytes=int(linha["size_bytes"]),
        object_key=linha["object_key"],
        staging_state=FileStagingState(linha["staging_state"]),
        uploaded_at=instant(linha["uploaded_at"]),
        uploaded_by=linha["uploaded_by"],
        provenance=_json_para_provenance(linha["provenance"]),
        row_count=linha["row_count"],
        column_count=linha["column_count"],
    )


def _para_relatorio(linha: Any, issues: list[DatasetValidationIssue]) -> DatasetValidationReport:
    """Reconstrói o relatório. `status` NÃO vem da coluna.

    A coluna existe para consulta e filtro; o valor autoritativo é derivado
    das issues, como no domínio. Ler o status da coluna criaria a
    possibilidade de um relatório cujo status contradiz as próprias issues —
    e ele passaria por qualquer verificação, porque a contradição é interna.
    """
    return DatasetValidationReport(
        id=str(linha["id"]),
        dataset_id=DatasetId(linha["dataset_id"]),
        dataset_version=DatasetVersion(major=linha["version_major"], minor=linha["version_minor"]),
        validator_version=ValidatorVersion(
            major=linha["validator_major"], minor=linha["validator_minor"]
        ),
        started_at=instant(linha["started_at"]),
        generated_at=instant(linha["generated_at"]),
        files_checked=linha["files_checked"],
        rows_observed=int(linha["rows_observed"]),
        issues=tuple(issues),
        schema_observations=tuple(
            _json_para_observacao(o) for o in json.loads(linha["schema_observations"])
        ),
        issue_count=linha["issue_count"],
        truncated=linha["truncated"],
        execution_error=linha["execution_error"],
    )


def _provenance_para_json(p: DataProvenance) -> dict[str, Any]:
    return {
        "source_type": p.source_type.value,
        "provider_id": str(p.provider_id) if p.provider_id else None,
        "source_record_id": p.source_record_id,
        "license_class": p.license_class.value,
        "occurred_at": p.times.occurred_at.isoformat(),
        "observed_at": p.times.observed_at.isoformat(),
        "received_at": p.times.received_at.isoformat(),
        "ingested_at": p.times.ingested_at.isoformat(),
    }


def _json_para_provenance(bruto: str | dict[str, Any]) -> DataProvenance:
    dados = json.loads(bruto) if isinstance(bruto, str) else bruto
    return DataProvenance(
        source_type=SourceType(dados["source_type"]),
        provider_id=ProviderId(dados["provider_id"]) if dados["provider_id"] else None,
        source_record_id=dados["source_record_id"],
        times=ObservationTimes(
            occurred_at=parse_instant(dados["occurred_at"]),
            observed_at=parse_instant(dados["observed_at"]),
            received_at=parse_instant(dados["received_at"]),
            ingested_at=parse_instant(dados["ingested_at"]),
        ),
        license_class=LicenseClass(dados["license_class"]),
    )


def _observacao_para_json(o: DatasetSchemaObservation) -> dict[str, Any]:
    return {
        "file_id": o.file_id,
        "row_count": o.row_count,
        "truncated_columns": o.truncated_columns,
        "columns": [
            {
                "name": c.name,
                "detected_type": c.detected_type.value,
                "nullable": c.nullable,
                "null_count": c.null_count,
                "samples": list(c.samples),
            }
            for c in o.columns
        ],
    }


def _json_para_observacao(dados: dict[str, Any]) -> DatasetSchemaObservation:
    return DatasetSchemaObservation(
        file_id=dados["file_id"],
        row_count=dados["row_count"],
        truncated_columns=dados.get("truncated_columns", False),
        columns=tuple(
            ColumnObservation(
                name=c["name"],
                detected_type=DetectedType(c["detected_type"]),
                nullable=c["nullable"],
                null_count=c["null_count"],
                samples=tuple(c["samples"]),
            )
            for c in dados["columns"]
        ),
    )


def _manifesto_para_json(m: DatasetManifest) -> dict[str, Any]:
    """A forma persistida do manifesto.

    ELA NÃO É A FORMA CANÔNICA. A canônica (`as_canonical`) é o que se hasheia
    e propositalmente omite `created_at`; esta guarda tudo, para que o
    manifesto volte do banco idêntico ao que foi emitido. Se a persistida
    fosse a canônica, `created_at` se perderia e a releitura produziria um
    objeto diferente do gravado.
    """
    return {
        "dataset_id": str(m.dataset_id),
        "dataset_name": m.dataset_name,
        "dataset_version": str(m.dataset_version),
        "files": [
            {
                "file_id": f.file_id,
                "filename": f.filename,
                "format": f.format,
                "sha256": f.sha256.value,
                "size_bytes": f.size_bytes,
                "row_count": f.row_count,
                "column_count": f.column_count,
            }
            for f in m.files
        ],
        "source_name": m.source_name,
        "source_type": m.source_type,
        "license_class": m.license_class,
        "source_url": m.source_url,
        "retrieved_at": m.retrieved_at.isoformat(),
        "declared_competitions": list(m.declared_competitions),
        "declared_seasons": list(m.declared_seasons),
        "validation_id": m.validation_id,
        "validation_status": m.validation_status,
        "validator_version": str(m.validator_version),
        "rows_observed": m.rows_observed,
        "issue_count": m.issue_count,
        "created_at": m.created_at.isoformat(),
        "schema_version": m.schema_version,
    }


def _para_manifesto(bruto: str | dict[str, Any]) -> DatasetManifest:
    dados = json.loads(bruto) if isinstance(bruto, str) else bruto
    return DatasetManifest(
        dataset_id=DatasetId.parse(dados["dataset_id"]),
        dataset_name=dados["dataset_name"],
        dataset_version=DatasetVersion.parse(dados["dataset_version"]),
        files=tuple(
            ManifestFile(
                file_id=f["file_id"],
                filename=f["filename"],
                format=f["format"],
                sha256=ContentHash(f["sha256"]),
                size_bytes=f["size_bytes"],
                row_count=f["row_count"],
                column_count=f["column_count"],
            )
            for f in dados["files"]
        ),
        source_name=dados["source_name"],
        source_type=dados["source_type"],
        license_class=dados["license_class"],
        source_url=dados["source_url"],
        retrieved_at=parse_instant(dados["retrieved_at"]),
        declared_competitions=tuple(dados["declared_competitions"]),
        declared_seasons=tuple(dados["declared_seasons"]),
        validation_id=dados["validation_id"],
        validation_status=dados["validation_status"],
        validator_version=ValidatorVersion.parse(dados["validator_version"]),
        rows_observed=dados["rows_observed"],
        issue_count=dados["issue_count"],
        created_at=parse_instant(dados["created_at"]),
        schema_version=dados["schema_version"],
    )
