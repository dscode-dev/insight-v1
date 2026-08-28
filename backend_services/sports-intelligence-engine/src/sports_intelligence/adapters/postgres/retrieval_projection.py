"""A projeção de recuperação em PostgreSQL, em SQL escrito à mão.

O QUE É PARTICULAR DESTE ARQUIVO:

O UNIVERSO INTEIRO VOLTA NUMA CONSULTA. Não há `LIMIT`, não há ordenação por
distância e não há orçamento: o `WHERE` é a definição do `CandidateUniverse` do
PR-06.1, e o que ele seleciona é exatamente o que o oráculo leria do Parquet. A
ordenação é do domínio, sobre `float64`, depois.

O PLANO ESPERADO É B-TREE. O índice `hspr_universo_idx` cobre a conjunção
inteira — versão, competição, fase, minuto, acréscimo, desempate — e o
planejador o usa sem precisar de dica nenhuma. Foi medido no experimento de
viabilidade: mil candidatos saem em 0,35 ms.

O `bytea` VOLTA COMO `bytes`, E O DECODE É DO DOMÍNIO. Este adapter não
interpreta número nenhum: ele entrega os bytes ao codec, que devolve `float64`
idênticos aos da origem. É essa fronteira que mantém a projeção fiel.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Final, final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.retrieval.projection.contract import (
    HistoricalRetrievalProjectionVersion,
    RetrievalProjectionBinding,
    RetrievalProjectionKind,
    RetrievalProjectionStatus,
)
from sports_intelligence.domain.retrieval.projection.payload import (
    decode_state_payload,
    decode_trajectory_payload,
)
from sports_intelligence.domain.shared.errors import ConflictError, NotFoundError
from sports_intelligence.ports.retrieval_projection import (
    CandidateUniverseFilter,
    ProjectedStateCandidate,
    ProjectedTrajectoryCandidate,
)

_COLUNAS_VERSAO: Final[str] = """
    id, projection_id, version, kind, status,
    source_dataset_version_id, source_dataset_version, source_reference_fingerprint,
    normalization_plan_fingerprint, artifact_set_fingerprint,
    candidate_policy_fingerprint, exact_payload_encoding,
    trajectory_window_fingerprint, trajectory_profile_fingerprint,
    trajectory_coverage_fingerprint,
    axis_count, horizons, row_count, content_fingerprint, fingerprint
"""

_LOTE_DE_ESCRITA: Final[int] = 500


def _condicoes(universe: CandidateUniverseFilter, inicio: int) -> tuple[str, list[Any]]:
    """As igualdades do universo como `WHERE`, com os parâmetros numerados.

    CINCO IGUALDADES E UMA DESIGUALDADE, e nenhuma é opcional: as cinco
    primeiras são `EXACT_MATCH_TIME_POINT` do PR-06.1, e a última é a exclusão
    da própria partida. Deixar uma de fora traria candidatos de outro minuto.
    """
    clausulas = [
        f"competition = ${inicio}",
        f"period = ${inicio + 1}",
        f"minute = ${inicio + 2}",
        f"stoppage = ${inicio + 3}",
        f"tie_break = ${inicio + 4}",
        f"match_id <> ${inicio + 5}",
    ]
    return " AND ".join(clausulas), [
        universe.competition,
        universe.period,
        universe.minute,
        universe.stoppage,
        universe.tie_break,
        universe.exclude_match_id,
    ]


@final
class PostgresRetrievalProjectionRepository:
    """O registro das versões — metadados, transições e publicação."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def ensure_projection(self, *, name: str, kind: RetrievalProjectionKind) -> str:
        async with self._db.acquire() as c:
            linha = await c.fetchrow(
                "SELECT id FROM historical_retrieval_projections WHERE name=$1 AND kind=$2",
                name,
                kind.value,
            )
            if linha is not None:
                return str(linha["id"])
            novo = uuid.uuid4()
            await c.execute(
                "INSERT INTO historical_retrieval_projections (id, name, kind) VALUES ($1,$2,$3)",
                novo,
                name,
                kind.value,
            )
            return str(novo)

    async def create_version(
        self,
        *,
        projection_id: str,
        version: int,
        kind: RetrievalProjectionKind,
        binding: RetrievalProjectionBinding,
        axis_count: int,
        horizons: Sequence[int],
    ) -> str:
        version_id = str(uuid.uuid4())
        async with self._db.acquire() as c:
            await c.execute(
                """
                INSERT INTO historical_retrieval_projection_versions (
                    id, projection_id, version, kind, status,
                    source_dataset_version_id, source_dataset_version,
                    source_reference_fingerprint, normalization_plan_fingerprint,
                    artifact_set_fingerprint, candidate_policy_fingerprint,
                    exact_payload_encoding, trajectory_window_fingerprint,
                    trajectory_profile_fingerprint, trajectory_coverage_fingerprint,
                    axis_count, horizons
                ) VALUES ($1,$2,$3,$4,'DRAFT',$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                """,
                uuid.UUID(version_id),
                uuid.UUID(projection_id),
                version,
                kind.value,
                uuid.UUID(binding.source_dataset_version_id),
                binding.source_dataset_version,
                binding.source_reference_fingerprint,
                binding.normalization_plan_fingerprint,
                binding.artifact_set_fingerprint,
                binding.candidate_policy_fingerprint,
                binding.exact_payload_encoding,
                binding.trajectory_window_fingerprint,
                binding.trajectory_profile_fingerprint,
                binding.trajectory_coverage_fingerprint,
                axis_count,
                list(horizons),
            )
        return version_id

    async def transition(
        self,
        *,
        version_id: str,
        expected: RetrievalProjectionStatus,
        target: RetrievalProjectionStatus,
    ) -> None:
        """`UPDATE ... WHERE status = $esperado` — serializa builds concorrentes.

        É ESSA CLÁUSULA QUE EVITA LOCK DISTRIBUÍDO: a segunda construção
        encontra o status já mudado e falha, em vez de sobrescrever o trabalho
        da primeira.
        """
        async with self._db.acquire() as c:
            resultado = await c.execute(
                """
                UPDATE historical_retrieval_projection_versions
                   SET status=$3,
                       published_at = CASE WHEN $3='READY' THEN now() ELSE published_at END
                 WHERE id=$1 AND status=$2
                """,
                uuid.UUID(version_id),
                expected.value,
                target.value,
            )
            if resultado.endswith(" 0"):
                raise ConflictError(
                    f"a versao {version_id} nao estava em {expected.value}: outra "
                    "construcao ja a moveu, e sobrescrever perderia o trabalho dela",
                    context={"expected": expected.value, "target": target.value},
                )

    async def finalize_content(
        self, *, version_id: str, row_count: int, content_fingerprint: str, fingerprint: str
    ) -> None:
        async with self._db.acquire() as c:
            await c.execute(
                "UPDATE historical_retrieval_projection_versions"
                " SET row_count=$2, content_fingerprint=$3, fingerprint=$4 WHERE id=$1",
                uuid.UUID(version_id),
                row_count,
                content_fingerprint,
                fingerprint,
            )

    async def record_validation(
        self,
        *,
        version_id: str,
        rows_expected: int,
        rows_found: int,
        content_fingerprint: str,
        payload_rows_verified: int,
        outcome: str,
        detail: Mapping[str, object],
    ) -> None:
        async with self._db.acquire() as c:
            await c.execute(
                """
                INSERT INTO historical_retrieval_projection_validations (
                    id, projection_version_id, rows_expected, rows_found,
                    content_fingerprint, payload_rows_verified, outcome, detail
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
                """,
                uuid.uuid4(),
                uuid.UUID(version_id),
                rows_expected,
                rows_found,
                content_fingerprint,
                payload_rows_verified,
                outcome,
                json.dumps(dict(detail), sort_keys=True),
            )

    async def get_version(self, version_id: str) -> HistoricalRetrievalProjectionVersion:
        async with self._db.acquire() as c:
            linha = await c.fetchrow(
                f"SELECT {_COLUNAS_VERSAO} FROM historical_retrieval_projection_versions"
                " WHERE id=$1",
                uuid.UUID(version_id),
            )
        if linha is None:
            raise NotFoundError(f"versao de projecao {version_id} nao encontrada")
        return _versao_de(linha)

    async def latest_ready(
        self, *, dataset_version_id: str, kind: RetrievalProjectionKind
    ) -> HistoricalRetrievalProjectionVersion:
        """A versão READY mais recente. SÓ READY.

        Uma projeção em `BUILDING` tem linhas pela metade, e respondê-la
        devolveria um top-K sobre um universo incompleto — que é pior que não
        responder, porque parece uma resposta.
        """
        async with self._db.acquire() as c:
            linha = await c.fetchrow(
                f"""SELECT {_COLUNAS_VERSAO}
                      FROM historical_retrieval_projection_versions
                     WHERE source_dataset_version_id=$1 AND kind=$2 AND status='READY'
                     ORDER BY published_at DESC, version DESC LIMIT 1""",
                uuid.UUID(dataset_version_id),
                kind.value,
            )
        if linha is None:
            raise NotFoundError(
                f"nenhuma projecao {kind.value} READY para o dataset {dataset_version_id}"
            )
        return _versao_de(linha)

    async def sizes(self, kind: RetrievalProjectionKind) -> Mapping[str, int]:
        tabela = (
            "historical_state_projection_rows"
            if kind is RetrievalProjectionKind.STATE
            else "historical_trajectory_projection_rows"
        )
        async with self._db.acquire() as c:
            linha = await c.fetchrow(
                "SELECT pg_relation_size($1::regclass) heap,"
                " pg_total_relation_size($1::regclass) total",
                tabela,
            )
        return {"heap_bytes": int(linha["heap"]), "total_bytes": int(linha["total"])}


def _versao_de(linha: Any) -> HistoricalRetrievalProjectionVersion:
    return HistoricalRetrievalProjectionVersion(
        version_id=str(linha["id"]),
        projection_id=str(linha["projection_id"]),
        kind=RetrievalProjectionKind(linha["kind"]),
        name=str(linha["projection_id"]),
        version=int(linha["version"]),
        status=RetrievalProjectionStatus(linha["status"]),
        axis_count=int(linha["axis_count"]),
        binding=RetrievalProjectionBinding(
            source_dataset_version_id=str(linha["source_dataset_version_id"]),
            source_dataset_version=linha["source_dataset_version"],
            source_reference_fingerprint=linha["source_reference_fingerprint"],
            normalization_plan_fingerprint=linha["normalization_plan_fingerprint"],
            artifact_set_fingerprint=linha["artifact_set_fingerprint"],
            candidate_policy_fingerprint=linha["candidate_policy_fingerprint"],
            exact_payload_encoding=linha["exact_payload_encoding"],
            trajectory_window_fingerprint=linha["trajectory_window_fingerprint"],
            trajectory_profile_fingerprint=linha["trajectory_profile_fingerprint"],
            trajectory_coverage_fingerprint=linha["trajectory_coverage_fingerprint"],
        ),
        row_count=int(linha["row_count"]),
        content_fingerprint=linha["content_fingerprint"],
    )


@final
class PostgresRetrievalProjectionWriter:
    """Escreve as linhas projetadas. OFFLINE, e por isso pode ser caro."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def insert_state_rows(self, *, version_id: str, rows: Sequence[Mapping[str, Any]]) -> int:
        if not rows:
            return 0
        escritas = 0
        async with self._db.acquire() as c:
            for i in range(0, len(rows), _LOTE_DE_ESCRITA):
                lote = rows[i : i + _LOTE_DE_ESCRITA]
                await c.executemany(
                    """INSERT INTO historical_state_projection_rows (
                        projection_version_id, semantic_key, competition, season, match_id,
                        period, minute, stoppage, tie_break,
                        exact_values, exact_mask, exact_payload_digest, usable_axes,
                        row_digest, representation_fingerprint
                       ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)""",
                    [
                        (
                            uuid.UUID(version_id),
                            r["semantic_key"],
                            r["competition"],
                            r["season"],
                            r["match_id"],
                            r["period"],
                            r["minute"],
                            r["stoppage"],
                            r["tie_break"],
                            r["exact_values"],
                            r["exact_mask"],
                            r["exact_payload_digest"],
                            r["usable_axes"],
                            r["row_digest"],
                            r["representation_fingerprint"],
                        )
                        for r in lote
                    ],
                )
                escritas += len(lote)
        return escritas

    async def insert_trajectory_rows(
        self, *, version_id: str, rows: Sequence[Mapping[str, Any]]
    ) -> int:
        if not rows:
            return 0
        escritas = 0
        async with self._db.acquire() as c:
            for i in range(0, len(rows), _LOTE_DE_ESCRITA):
                lote = rows[i : i + _LOTE_DE_ESCRITA]
                await c.executemany(
                    """INSERT INTO historical_trajectory_projection_rows (
                        projection_version_id, semantic_key, anchor_key, competition, season,
                        match_id, period, minute, stoppage, tie_break,
                        exact_values, exact_mask, exact_payload_digest,
                        usable_cells, usable_horizons, anchor_row_digest,
                        trajectory_fingerprint, representation_fingerprint, slot_lineage
                       ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                                 $16,$17,$18,$19::jsonb)""",
                    [
                        (
                            uuid.UUID(version_id),
                            r["semantic_key"],
                            r["anchor_key"],
                            r["competition"],
                            r["season"],
                            r["match_id"],
                            r["period"],
                            r["minute"],
                            r["stoppage"],
                            r["tie_break"],
                            r["exact_values"],
                            r["exact_mask"],
                            r["exact_payload_digest"],
                            r["usable_cells"],
                            r["usable_horizons"],
                            r["anchor_row_digest"],
                            r["trajectory_fingerprint"],
                            r["representation_fingerprint"],
                            json.dumps(r["slot_lineage"], sort_keys=True),
                        )
                        for r in lote
                    ],
                )
                escritas += len(lote)
        return escritas


@final
class PostgresRetrievalProjectionReader:
    """A leitura do universo exato. Implementa `RetrievalProjectionPort`.

    OS CONTADORES EXISTEM PARA O RELATÓRIO: uma consulta por query, e nunca uma
    por candidato — porque o N+1 aqui teria o mesmo efeito que teve na leitura
    do Parquet.
    """

    def __init__(self, database: Database) -> None:
        self._db = database
        self.universe_queries = 0
        self.payload_rows = 0

    def reset_counters(self) -> None:
        self.universe_queries = 0
        self.payload_rows = 0

    async def count_universe(
        self,
        *,
        projection_version: HistoricalRetrievalProjectionVersion,
        universe: CandidateUniverseFilter,
    ) -> int:
        tabela = (
            "historical_state_projection_rows"
            if projection_version.kind is RetrievalProjectionKind.STATE
            else "historical_trajectory_projection_rows"
        )
        cond, params = _condicoes(universe, 2)
        async with self._db.acquire() as c:
            linha = await c.fetchrow(
                f"SELECT count(*) t FROM {tabela} WHERE projection_version_id=$1 AND {cond}",
                uuid.UUID(projection_version.version_id),
                *params,
            )
        return int(linha["t"])

    async def load_state_universe(
        self,
        *,
        projection_version: HistoricalRetrievalProjectionVersion,
        universe: CandidateUniverseFilter,
        axis_keys: Sequence[str],
    ) -> Sequence[ProjectedStateCandidate]:
        cond, params = _condicoes(universe, 2)
        self.universe_queries += 1
        async with self._db.acquire() as c:
            linhas = await c.fetch(
                f"""SELECT semantic_key, match_id, competition, season,
                           exact_values, exact_mask, row_digest, representation_fingerprint
                      FROM historical_state_projection_rows
                     WHERE projection_version_id=$1 AND {cond}""",
                uuid.UUID(projection_version.version_id),
                *params,
            )
        self.payload_rows += len(linhas)
        return [
            ProjectedStateCandidate(
                semantic_key=linha["semantic_key"],
                match_id=linha["match_id"],
                competition=linha["competition"],
                season=linha["season"],
                payload=decode_state_payload(
                    axis_keys=axis_keys,
                    values=bytes(linha["exact_values"]),
                    mask=bytes(linha["exact_mask"]),
                    row_digest=linha["row_digest"],
                    representation_fingerprint=linha["representation_fingerprint"],
                ),
            )
            for linha in linhas
        ]

    async def load_trajectory_universe(
        self,
        *,
        projection_version: HistoricalRetrievalProjectionVersion,
        universe: CandidateUniverseFilter,
        axis_keys: Sequence[str],
        horizons: Sequence[int],
    ) -> Sequence[ProjectedTrajectoryCandidate]:
        cond, params = _condicoes(universe, 2)
        self.universe_queries += 1
        async with self._db.acquire() as c:
            linhas = await c.fetch(
                f"""SELECT semantic_key, anchor_key, match_id, competition, season,
                           exact_values, exact_mask, anchor_row_digest,
                           trajectory_fingerprint, representation_fingerprint,
                           slot_lineage
                      FROM historical_trajectory_projection_rows
                     WHERE projection_version_id=$1 AND {cond}""",
                uuid.UUID(projection_version.version_id),
                *params,
            )
        self.payload_rows += len(linhas)
        return [
            ProjectedTrajectoryCandidate(
                semantic_key=linha["semantic_key"],
                anchor_key=linha["anchor_key"],
                match_id=linha["match_id"],
                competition=linha["competition"],
                season=linha["season"],
                payload=decode_trajectory_payload(
                    axis_keys=axis_keys,
                    horizons=horizons,
                    displacements=bytes(linha["exact_values"]),
                    mask=bytes(linha["exact_mask"]),
                    anchor_row_digest=linha["anchor_row_digest"],
                    trajectory_fingerprint=linha["trajectory_fingerprint"],
                    representation_fingerprint=linha["representation_fingerprint"],
                ),
                slot_lineage=tuple(
                    json.loads(linha["slot_lineage"])
                    if isinstance(linha["slot_lineage"], str)
                    else linha["slot_lineage"]
                ),
            )
            for linha in linhas
        ]

    async def explain_state_universe(
        self,
        *,
        projection_version: HistoricalRetrievalProjectionVersion,
        universe: CandidateUniverseFilter,
    ) -> str:
        """`EXPLAIN (ANALYZE, BUFFERS)` da MESMA consulta que roda em produção."""
        cond, params = _condicoes(universe, 2)
        async with self._db.acquire() as c:
            linhas = await c.fetch(
                f"""EXPLAIN (ANALYZE, BUFFERS)
                    SELECT semantic_key, exact_values, exact_mask
                      FROM historical_state_projection_rows
                     WHERE projection_version_id=$1 AND {cond}""",
                uuid.UUID(projection_version.version_id),
                *params,
            )
        return "\n".join(linha[0] for linha in linhas)
