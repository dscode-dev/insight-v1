"""PostgreSQL/pgvector similarity storage (ATLAS-SIMILARITY-A: storage-only).

The repository is now pure storage: it runs the HNSW cosine query and maps rows
to `SimilarityMatch`. All business logic (confidence, coverage, distribution,
SimilarityContext construction, caching, metrics) lives in `SimilarityService`.

`confidence_for_matches` is re-exported here for backward compatibility with
existing callers/tests; its canonical home is `atlas.similarity.scoring`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.similarity.contracts import (
    SimilarityFilters,
    SimilarityMatch,
    SimilaritySearchRequest,
    SimilaritySearchResult,
)
from atlas.similarity.scoring import confidence_for_matches

__all__ = ["SimilarityRepository", "confidence_for_matches"]


class SimilarityRepository:
    """Pure online vector search over `atlas.atlas_vector_memory`."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        hnsw_ef_search: int = 100,
    ) -> None:
        self._sf = session_factory
        self._hnsw_ef_search = hnsw_ef_search

    # -- storage primitives (ATLAS-SIMILARITY-A) ------------------------------

    async def search_matches(self, request: SimilaritySearchRequest) -> list[SimilarityMatch]:
        """One nearest-neighbour query → ordered matches (no scoring)."""
        where_sql, params = _where(request.filters)
        params.update(
            {
                "embedding": _vector(request.embedding),
                "minimum_similarity": request.minimum_similarity,
                "top_k": request.top_k,
            }
        )
        statement = text(_search_sql(where_sql))
        async with self._sf() as session:
            async with session.begin():
                await self._apply_ef_search(session)
                rows = (await session.execute(statement, params)).mappings().all()
        return [_row_to_match(row) for row in rows]

    async def batch_search_matches(
        self, requests: Sequence[SimilaritySearchRequest]
    ) -> list[list[SimilarityMatch]]:
        """TRUE batch (Stage 3): one session, one transaction, one ef_search set,
        one query per request — minimising connection acquisition + round-trips.
        Order and per-request matches are preserved 1:1 with `requests`."""
        if not requests:
            return []
        results: list[list[SimilarityMatch]] = []
        async with self._sf() as session:
            async with session.begin():
                await self._apply_ef_search(session)
                for request in requests:
                    where_sql, params = _where(request.filters)
                    params.update(
                        {
                            "embedding": _vector(request.embedding),
                            "minimum_similarity": request.minimum_similarity,
                            "top_k": request.top_k,
                        }
                    )
                    rows = (
                        await session.execute(text(_search_sql(where_sql)), params)
                    ).mappings().all()
                    results.append([_row_to_match(row) for row in rows])
        return results

    async def _apply_ef_search(self, session: AsyncSession) -> None:
        await session.execute(
            text("SET LOCAL hnsw.ef_search = :ef_search"),
            {"ef_search": self._hnsw_ef_search},
        )

    async def explain_nearest(self, request: SimilaritySearchRequest) -> list[str]:
        where_sql, params = _where(request.filters)
        params.update(
            {
                "embedding": _vector(request.embedding),
                "minimum_similarity": request.minimum_similarity,
                "top_k": request.top_k,
            }
        )
        statement = text("EXPLAIN (FORMAT TEXT) " + _search_sql(where_sql))
        async with self._sf() as session:
            rows = (await session.execute(statement, params)).all()
        return [str(row[0]) for row in rows]

    # -- backward-compatible convenience wrappers -----------------------------
    # Prefer SimilarityService; these keep pre-ATLAS-SIMILARITY-A callers working.

    async def search(self, request: SimilaritySearchRequest) -> SimilaritySearchResult:
        matches = await self.search_matches(request)
        return SimilaritySearchResult(
            matches=matches,
            confidence=confidence_for_matches(
                matches, minimum_neighbors=request.minimum_neighbors
            ),
            filters=request.filters,
            top_k=request.top_k,
            minimum_similarity=request.minimum_similarity,
        )

    async def nearest(
        self,
        embedding: tuple[float, ...],
        *,
        top_k: int = 25,
        minimum_similarity: float = 0.72,
        filters: SimilarityFilters | None = None,
        minimum_neighbors: int = 3,
    ) -> SimilaritySearchResult:
        return await self.search(
            SimilaritySearchRequest(
                embedding=embedding,
                filters=filters or SimilarityFilters(),
                top_k=top_k,
                minimum_similarity=minimum_similarity,
                minimum_neighbors=minimum_neighbors,
            )
        )

    async def batch_nearest(
        self, requests: Iterable[SimilaritySearchRequest]
    ) -> list[SimilaritySearchResult]:
        request_list = list(requests)
        batched = await self.batch_search_matches(request_list)
        return [
            SimilaritySearchResult(
                matches=matches,
                confidence=confidence_for_matches(
                    matches, minimum_neighbors=request.minimum_neighbors
                ),
                filters=request.filters,
                top_k=request.top_k,
                minimum_similarity=request.minimum_similarity,
            )
            for request, matches in zip(request_list, batched, strict=True)
        ]


def _search_sql(where_sql: str) -> str:
    return f"""
        WITH candidates AS (
            SELECT
                vector_id,
                source_match_id,
                embedding_version,
                feature_schema_version,
                signal_catalog_version,
                behavior_catalog_version,
                competition,
                season,
                market_type,
                match_phase,
                behavior,
                trends,
                signals,
                source_system,
                generation_id,
                lineage,
                similarity_metadata,
                created_at,
                embedding <=> CAST(:embedding AS vector) AS distance
            FROM atlas.atlas_vector_memory
            WHERE {where_sql}
            ORDER BY embedding <=> CAST(:embedding AS vector), created_at
            LIMIT :top_k
        )
        SELECT
            *,
            1 - distance AS similarity
        FROM candidates
        WHERE 1 - distance >= :minimum_similarity
        ORDER BY distance ASC, created_at ASC
    """


def _where(filters: SimilarityFilters) -> tuple[str, dict[str, Any]]:
    clauses = ["embedding_version = :embedding_version"]
    params: dict[str, Any] = {"embedding_version": filters.embedding_version}
    optional_columns = {
        "feature_schema_version": filters.feature_schema_version,
        "signal_catalog_version": filters.signal_catalog_version,
        "behavior_catalog_version": filters.behavior_catalog_version,
        "competition": filters.competition,
        "season": filters.season,
        "market_type": filters.market_type,
        "match_phase": filters.match_phase,
        "regime": filters.regime,
    }
    for column, value in optional_columns.items():
        if value is None:
            continue
        clauses.append(f"{column} = :{column}")
        params[column] = value
    if filters.exclude_match_id is not None:
        clauses.append("source_match_id <> :exclude_match_id")
        params["exclude_match_id"] = filters.exclude_match_id
    if filters.time_window is not None:
        if filters.time_window.start is not None:
            clauses.append("created_at >= :time_window_start")
            params["time_window_start"] = filters.time_window.start
        if filters.time_window.end is not None:
            clauses.append("created_at < :time_window_end")
            params["time_window_end"] = filters.time_window.end
    return " AND ".join(clauses), params


def _row_to_match(row: Any) -> SimilarityMatch:
    metadata = {
        "behavior": _json(row["behavior"]),
        "trends": _json(row["trends"]),
        "signals": _json(row["signals"]),
        "source_system": row["source_system"],
        "generation_id": row["generation_id"],
        "lineage": _json(row["lineage"]),
        **_json(row["similarity_metadata"]),
    }
    distance = float(row["distance"])
    similarity = max(0.0, min(1.0, float(row["similarity"])))
    explanation = [
        f"cosine_distance={distance:.6f}",
        f"similarity={similarity:.6f}",
        f"embedding_version={row['embedding_version']}",
    ]
    if row["competition"]:
        explanation.append(f"competition={row['competition']}")
    return SimilarityMatch(
        vector_id=row["vector_id"],
        match_id=row["source_match_id"],
        similarity=round(similarity, 6),
        distance=round(distance, 6),
        embedding_version=row["embedding_version"],
        feature_schema_version=row["feature_schema_version"],
        signal_catalog_version=row["signal_catalog_version"],
        behavior_catalog_version=row["behavior_catalog_version"],
        competition=row["competition"],
        season=row["season"],
        market_type=row["market_type"],
        match_phase=row["match_phase"],
        metadata=metadata,
        explanation=explanation,
    )


def _json(value: Any) -> Any:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return value


def _vector(values: tuple[float, ...]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"
